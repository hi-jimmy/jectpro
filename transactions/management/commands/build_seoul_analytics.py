import csv
import io
import json
import math
import re
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import shapefile
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


def normalize_row(row):
    return {
        str(key or "").strip().upper(): (value.strip() if isinstance(value, str) else value)
        for key, value in row.items()
        if key is not None
    }


def first_value(row, *names):
    for name in names:
        value = row.get(name.upper())
        if value not in (None, ""):
            return str(value).strip()
    return ""


def number_value(value):
    if value in (None, "", "*"):
        return None
    try:
        parsed = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def csv_encoding(sample):
    if sample.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    try:
        utf8_text = sample.decode("utf-8")
    except UnicodeDecodeError:
        return "cp949"
    if any("\uac00" <= char <= "\ud7a3" for char in utf8_text):
        return "utf-8"
    try:
        cp949_text = sample.decode("cp949")
    except UnicodeDecodeError:
        return "utf-8"
    return "cp949" if any("\uac00" <= char <= "\ud7a3" for char in cp949_text) else "utf-8"


def iter_csv_rows(archive, member):
    buffered = io.BufferedReader(archive.open(member))
    encoding = csv_encoding(buffered.peek(8192))
    text = io.TextIOWrapper(buffered, encoding=encoding, errors="strict", newline="")
    try:
        yield from csv.DictReader(text)
    finally:
        text.close()


def classify_archive(name):
    if name.startswith("250_LOCAL_RESD_"):
        return "living"
    if "점포" in name:
        return "store"
    if "추정매출" in name:
        return "sales"
    if "영역" in name:
        return "area"
    if "격자" in name:
        return "grid"
    if "행정동" in name:
        return "admin"
    return ""


def dbf_field(fields, *prefixes):
    for prefix in prefixes:
        for field in fields:
            if field.upper().startswith(prefix.upper()):
                return field
    return None


class Command(BaseCommand):
    help = "Stream the supplied Seoul ZIP archives into a compact dashboard analysis file."

    def add_arguments(self, parser):
        parser.add_argument("source_dir", help="Directory containing the supplied ZIP archives")
        parser.add_argument(
            "--output",
            default=str(settings.BASE_DIR / "static" / "data" / "seoul_analytics.json"),
            help="Output JSON path (defaults to static/data/seoul_analytics.json)",
        )
        parser.add_argument(
            "--max-living-files",
            type=int,
            help="Process only the first N daily population CSVs; intended for a quick test",
        )

    def handle(self, *args, **options):
        source_dir = Path(options["source_dir"])
        if not source_dir.is_dir():
            raise CommandError(f"Source directory does not exist: {source_dir}")
        if options["max_living_files"] is not None and options["max_living_files"] < 1:
            raise CommandError("--max-living-files must be at least 1")

        archives = sorted(source_dir.glob("*.zip"))
        selected = [(path, classify_archive(path.name)) for path in archives]
        selected = [(path, kind) for path, kind in selected if kind]
        kinds = {kind for _, kind in selected}
        required = {"living", "grid", "area", "store", "sales", "admin"}
        missing = sorted(required - kinds)
        if missing:
            raise CommandError(f"Required archive type(s) not found: {', '.join(missing)}")

        area_by_code, area_summary, area_rows = self.read_areas(selected)
        admin_by_code, admin_metadata = self.read_admin_codes(selected)
        grid_metadata = self.read_grid(selected)
        living, living_metadata = self.read_living(
            selected, area_by_code, admin_by_code, options["max_living_files"]
        )
        stores, store_metadata = self.read_stores(selected, area_by_code)
        sales, sales_metadata = self.read_sales(selected, area_by_code)

        district_names = {
            entry["district_code"]: entry["district"]
            for entry in area_by_code.values()
            if entry["district_code"] and entry["district"]
        }
        payload = {
            "metadata": {
                "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "sources": [path.name for path, _ in selected],
                "district_count": len(district_names),
                "living": living_metadata,
                "store": store_metadata,
                "sales": sales_metadata,
                "trade_area": {"records": area_rows},
                "grid": grid_metadata,
                "administrative_codes": admin_metadata,
            },
            "districts": [
                {"code": code, "name": name}
                for code, name in sorted(district_names.items())
            ],
            "living": living,
            "store": stores,
            "sales": sales,
            "trade_areas": area_summary,
        }

        output = Path(options["output"])
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with output.open("w", encoding="utf-8", newline="\n") as file_handle:
                json.dump(payload, file_handle, ensure_ascii=False, separators=(",", ":"))
        except OSError as exc:
            raise CommandError(f"Could not write analysis file {output}: {exc}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Created {output} ({output.stat().st_size:,} bytes): "
                f"{living_metadata['source_rows']:,} living rows, "
                f"{store_metadata['source_rows']:,} store rows, "
                f"{sales_metadata['source_rows']:,} sales rows"
            )
        )
        if options["max_living_files"]:
            self.stdout.write(self.style.WARNING("Population data is a partial test run."))

    def read_areas(self, selected):
        path = next(path for path, kind in selected if kind == "area")
        try:
            with zipfile.ZipFile(path) as archive:
                members = archive.infolist()
                shp = next((item for item in members if item.filename.lower().endswith(".shp")), None)
                sidecars = {
                    Path(item.filename).suffix.lower(): item
                    for item in members
                    if Path(item.filename).suffix.lower() in (".shx", ".dbf")
                }
                if shp is None or ".dbf" not in sidecars:
                    raise CommandError(f"{path.name} must contain a shapefile and DBF attributes.")
                reader = shapefile.Reader(
                    shp=io.BytesIO(archive.read(shp)),
                    shx=io.BytesIO(archive.read(sidecars[".shx"])) if ".shx" in sidecars else None,
                    dbf=io.BytesIO(archive.read(sidecars[".dbf"])),
                    encoding="utf-8",
                )
                fields = [field[0] for field in reader.fields[1:]]
                code_field = dbf_field(fields, "TRDAR_CD")
                name_field = dbf_field(fields, "TRDAR_CD_N")
                district_code_field = dbf_field(fields, "SIGNGU_CD")
                district_name_field = dbf_field(fields, "SIGNGU_CD_")
                area_field = dbf_field(fields, "RELM_AR")
                if not code_field or not district_code_field or not district_name_field:
                    raise CommandError(f"Unexpected commercial-area fields in {path.name}: {fields}")
                area_by_code = {}
                district_totals = defaultdict(lambda: [0, 0.0])
                for shape_record in reader.iterShapeRecords():
                    properties = dict(zip(fields, list(shape_record.record)))
                    code = str(properties.get(code_field) or "").strip()
                    district_code = str(properties.get(district_code_field) or "").strip()
                    district = str(properties.get(district_name_field) or "").strip()
                    if not code:
                        continue
                    area = number_value(properties.get(area_field)) if area_field else 0
                    area_by_code[code] = {"district_code": district_code, "district": district}
                    district_totals[district][0] += 1
                    district_totals[district][1] += area or 0
                area_summary = [
                    {"district": district, "trade_area_count": values[0], "area_m2": round(values[1], 2)}
                    for district, values in sorted(district_totals.items())
                ]
                reader.close()
                return area_by_code, area_summary, sum(item["trade_area_count"] for item in area_summary)
        except (OSError, zipfile.BadZipFile, shapefile.ShapefileException) as exc:
            raise CommandError(f"Could not read commercial-area archive {path.name}: {exc}") from exc

    def read_admin_codes(self, selected):
        path = next(path for path, kind in selected if kind == "admin")
        try:
            with zipfile.ZipFile(path) as archive:
                members = [
                    item for item in archive.infolist()
                    if item.filename.lower().endswith(".csv")
                    and re.search(r"ADMI_20\d{4}\.csv$", item.filename, re.IGNORECASE)
                ]
                if not members:
                    raise CommandError(f"No monthly administrative-code CSVs found in {path.name}.")
                latest = max(members, key=lambda item: item.filename)
                codes = {}
                row_count = 0
                for source in iter_csv_rows(archive, latest):
                    row = normalize_row(source)
                    administrative_code = first_value(row, "ADMI_CD", "행정동코드")
                    district = first_value(row, "SGG_NM", "자치구명")
                    if administrative_code and district:
                        codes[administrative_code[:5]] = district
                    row_count += 1
                return codes, {
                    "latest_period": re.search(r"20\d{4}", latest.filename).group(0),
                    "latest_file_rows": row_count,
                    "available_months": len(members),
                }
        except (OSError, zipfile.BadZipFile, UnicodeError, csv.Error) as exc:
            raise CommandError(f"Could not read administrative-code archive {path.name}: {exc}") from exc

    def read_grid(self, selected):
        path = next(path for path, kind in selected if kind == "grid")
        try:
            with zipfile.ZipFile(path) as archive:
                members = archive.infolist()
                shp = next((item for item in members if item.filename.lower().endswith(".shp")), None)
                dbf = next((item for item in members if item.filename.lower().endswith(".dbf")), None)
                if shp is None or dbf is None:
                    raise CommandError(f"{path.name} must contain a .shp and .dbf file.")
                reader = shapefile.Reader(
                    shp=io.BytesIO(archive.read(shp)),
                    dbf=io.BytesIO(archive.read(dbf)),
                    encoding="utf-8",
                )
                fields = [field[0] for field in reader.fields[1:]]
                cell_field = dbf_field(fields, "CELL_ID")
                x_field = dbf_field(fields, "CELL_X")
                y_field = dbf_field(fields, "CELL_Y")
                if not cell_field or not x_field or not y_field:
                    raise CommandError(f"Unexpected 250m-grid attributes in {path.name}: {fields}")
                xs, ys, cell_ids = [], [], set()
                for record in reader.iterRecords():
                    cell_ids.add(str(record[fields.index(cell_field)]).strip())
                    xs.append(float(record[fields.index(x_field)]))
                    ys.append(float(record[fields.index(y_field)]))
                reader.close()
                return {
                    "cell_count": len(cell_ids),
                    "coordinate_system": "EPSG:5179",
                    "x_extent_m": [min(xs), max(xs)] if xs else [],
                    "y_extent_m": [min(ys), max(ys)] if ys else [],
                }
        except (OSError, zipfile.BadZipFile, shapefile.ShapefileException, ValueError) as exc:
            raise CommandError(f"Could not read grid archive {path.name}: {exc}") from exc

    def read_living(self, selected, area_by_code, admin_by_code, max_files):
        paths = [path for path, kind in selected if kind == "living"]
        aggregates = {}
        district_by_code = {}
        for area in area_by_code.values():
            district_by_code.setdefault(area["district_code"], area["district"])
        source_rows = masked_rows = processed_files = 0
        available_days = defaultdict(set)
        for path in paths:
            try:
                with zipfile.ZipFile(path) as archive:
                    members = sorted(
                        (item for item in archive.infolist() if item.filename.lower().endswith(".csv")),
                        key=lambda item: item.filename,
                    )
                    for member in members:
                        if max_files is not None and processed_files >= max_files:
                            break
                        for source in iter_csv_rows(archive, member):
                            row = normalize_row(source)
                            period = first_value(row, "YMD", "일자")
                            if len(period) < 6 or not period[:6].isdigit():
                                continue
                            month = period[:6]
                            hour_value = first_value(row, "TT", "시간")
                            hour_match = re.search(r"\d{1,2}", hour_value)
                            if not hour_match:
                                continue
                            hour = int(hour_match.group(0))
                            if hour > 23:
                                continue
                            administrative_code = first_value(row, "H_DNG_CD", "행정동코드")
                            district_code = administrative_code[:5]
                            district = district_by_code.get(district_code)
                            if not district:
                                district = admin_by_code.get(district_code, district_code or "미분류")
                            total_value = number_value(first_value(row, "SPOP", "생활인구합계"))
                            key = (month, hour, district_code, district)
                            item = aggregates.setdefault(
                                key, {"total": 0.0, "rows": 0, "observed": 0, "masked": 0}
                            )
                            item["rows"] += 1
                            source_rows += 1
                            available_days[key].add(period[:8])
                            if total_value is None:
                                item["masked"] += 1
                                masked_rows += 1
                            else:
                                item["total"] += total_value
                                item["observed"] += 1
                        processed_files += 1
                        if processed_files % 25 == 0:
                            self.stdout.write(f"Living population CSVs streamed: {processed_files}")
                    if max_files is not None and processed_files >= max_files:
                        break
            except (OSError, zipfile.BadZipFile, UnicodeError, csv.Error) as exc:
                raise CommandError(f"Could not stream living-population archive {path.name}: {exc}") from exc

        records = []
        for key, values in sorted(aggregates.items()):
            month, hour, district_code, district = key
            days = len(available_days[key])
            records.append({
                "period": month,
                "hour": hour,
                "district_code": district_code,
                "district": district,
                "average_daily_population": round(values["total"] / days, 2) if days else 0,
                "average_daily_observed_cells": round(values["observed"] / days, 2) if days else 0,
                "source_rows": values["rows"],
                "masked_rows": values["masked"],
                "days": days,
            })
        periods = sorted({item["period"] for item in records})
        return records, {
            "archives": len(paths),
            "processed_csv_files": processed_files,
            "periods": periods,
            "period_start": periods[0] if periods else "",
            "period_end": periods[-1] if periods else "",
            "source_rows": source_rows,
            "masked_rows": masked_rows,
            "aggregate_rows": len(records),
            "note": "Daily district/hour totals exclude cells whose total population is masked as *.",
        }

    def read_stores(self, selected, area_by_code):
        aggregates = {}
        source_rows = 0
        fingerprints = set()
        for path, kind in selected:
            if kind != "store":
                continue
            try:
                with zipfile.ZipFile(path) as archive:
                    for member in archive.infolist():
                        if not member.filename.lower().endswith(".csv"):
                            continue
                        fingerprint = (member.file_size, member.CRC)
                        if fingerprint in fingerprints:
                            continue
                        fingerprints.add(fingerprint)
                        for source in iter_csv_rows(archive, member):
                            row = normalize_row(source)
                            quarter = first_value(row, "STDR_YYQU_CD", "기준_년분기_코드")
                            trade_code = first_value(row, "TRDAR_CD", "상권_코드")
                            category = first_value(row, "SVC_INDUTY_CD_NM", "서비스_업종_코드_명")
                            trade = area_by_code.get(trade_code, {})
                            district_code = trade.get("district_code", "")
                            district = trade.get("district", "미분류")
                            key = (quarter, district_code, district, category)
                            item = aggregates.setdefault(
                                key, {"store_count": 0.0, "open_count": 0.0, "close_count": 0.0, "franchise_count": 0.0}
                            )
                            for metric, names in (
                                ("store_count", ("STOR_CO", "점포_수")),
                                ("open_count", ("OPBIZ_STOR_CO", "개업_점포_수")),
                                ("close_count", ("CLSBIZ_STOR_CO", "폐업_점포_수")),
                                ("franchise_count", ("FRC_STOR_CO", "프랜차이즈_점포_수")),
                            ):
                                item[metric] += number_value(first_value(row, *names)) or 0
                            source_rows += 1
            except (OSError, zipfile.BadZipFile, UnicodeError, csv.Error) as exc:
                raise CommandError(f"Could not read store archive {path.name}: {exc}") from exc
        records = [
            {"period": key[0], "district_code": key[1], "district": key[2], "category": key[3], **values}
            for key, values in sorted(aggregates.items())
        ]
        return records, {"source_rows": source_rows, "aggregate_rows": len(records), "periods": sorted({r["period"] for r in records})}

    def read_sales(self, selected, area_by_code):
        aggregates = {}
        source_rows = 0
        fingerprints = set()
        duplicate_files_skipped = 0
        for path, kind in selected:
            if kind != "sales":
                continue
            try:
                with zipfile.ZipFile(path) as archive:
                    for member in archive.infolist():
                        if not member.filename.lower().endswith(".csv"):
                            continue
                        fingerprint = (member.file_size, member.CRC)
                        if fingerprint in fingerprints:
                            duplicate_files_skipped += 1
                            continue
                        fingerprints.add(fingerprint)
                        for source in iter_csv_rows(archive, member):
                            row = normalize_row(source)
                            quarter = first_value(row, "STDR_YYQU_CD", "기준_년분기_코드")
                            trade_code = first_value(row, "TRDAR_CD", "상권_코드")
                            category = first_value(row, "SVC_INDUTY_CD_NM", "서비스_업종_코드_명")
                            trade = area_by_code.get(trade_code, {})
                            district_code = trade.get("district_code", "")
                            district = trade.get("district", "미분류")
                            key = (quarter, district_code, district, category)
                            item = aggregates.setdefault(key, defaultdict(float))
                            for metric, value in row.items():
                                if "매출_금액" not in metric and "매출_건수" not in metric:
                                    continue
                                parsed = number_value(value)
                                if parsed is not None:
                                    item[metric] += parsed
                            source_rows += 1
            except (OSError, zipfile.BadZipFile, UnicodeError, csv.Error) as exc:
                raise CommandError(f"Could not read sales archive {path.name}: {exc}") from exc
        records = [
            {
                "period": key[0],
                "district_code": key[1],
                "district": key[2],
                "category": key[3],
                "metrics": {metric: round(value, 2) for metric, value in sorted(values.items())},
            }
            for key, values in sorted(aggregates.items())
        ]
        return records, {
            "source_rows": source_rows,
            "aggregate_rows": len(records),
            "periods": sorted({record["period"] for record in records}),
            "duplicate_csv_files_skipped": duplicate_files_skipped,
        }
