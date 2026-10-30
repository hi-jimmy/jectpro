import json
import tempfile
import zipfile
from pathlib import Path

import shapefile
from django.core.management.base import BaseCommand, CommandError

from transactions.models import SeoulOpenRecord


def json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


class Command(BaseCommand):
    help = "Import the official Seoul commercial-area ZIP or extracted shapefile (EPSG:5181)."

    def add_arguments(self, parser):
        parser.add_argument("source", help="Official ZIP or extracted .shp path; sidecar files must be present")

    def handle(self, *args, **options):
        source = Path(options["source"])
        if not source.is_file():
            raise CommandError(f"File not found: {source}")
        temporary_directory = None
        if source.suffix.lower() == ".zip":
            temporary_directory = tempfile.TemporaryDirectory(prefix="seoul-area-")
            try:
                with zipfile.ZipFile(source) as archive:
                    root = Path(temporary_directory.name).resolve()
                    for member in archive.infolist():
                        target = (root / member.filename).resolve()
                        if target != root and root not in target.parents:
                            raise CommandError("The ZIP contains a path outside its extraction directory.")
                    archive.extractall(root)
                candidates = list(root.rglob("*.shp"))
                if not candidates:
                    raise CommandError("No .shp file was found inside the ZIP.")
                shp_path = candidates[0]
            except zipfile.BadZipFile as exc:
                raise CommandError("The provided file is not a valid ZIP archive.") from exc
        elif source.suffix.lower() == ".shp":
            shp_path = source
        else:
            raise CommandError("Supply the official .zip or extracted .shp file.")

        projection_path = shp_path.with_suffix(".prj")
        if not projection_path.is_file():
            raise CommandError("The .prj projection sidecar is required to confirm EPSG:5181.")
        projection = projection_path.read_text(encoding="utf-8", errors="ignore").upper()
        if "5181" not in projection and "KOREAN 2000 / CENTRAL BELT" not in projection:
            raise CommandError("The commercial-area file is expected in EPSG:5181 according to the official page.")
        try:
            reader = shapefile.Reader(str(shp_path), encoding="utf-8")
        except (OSError, shapefile.ShapefileException) as exc:
            raise CommandError(f"Could not read shapefile: {exc}") from exc

        fields = [field[0] for field in reader.fields[1:]]
        field_lookup = {field.upper(): field for field in fields}

        def find_field(*names):
            return next((field_lookup[name] for name in names if name in field_lookup), None)

        code_field = find_field("TRDAR_CD", "상권_코드")
        name_field = find_field("TRDAR_CD_NM", "상권_코드_명")
        district_field = find_field("SIGNGU_CD_NM", "자치구_코드_명")
        x_field = find_field("XCNTS_VALUE", "엑스좌표_값")
        y_field = find_field("YDNTS_VALUE", "와이좌표_값")
        area_field = find_field("AREA", "AREA_VALUE", "영역_면적")
        if not code_field:
            raise CommandError(f"Could not identify the commercial-area code. Available fields: {', '.join(fields)}")

        count = 0
        for shape_record in reader.iterShapeRecords():
            properties = dict(zip(fields, list(shape_record.record)))
            record_code = str(properties.get(code_field, "")).strip()
            if not record_code:
                continue
            geometry = shape_record.shape.__geo_interface__
            SeoulOpenRecord.objects.update_or_create(
                dataset=SeoulOpenRecord.Dataset.TRADE_AREA,
                record_key=record_code,
                defaults={
                    "trade_code": record_code,
                    "trade_name": str(properties.get(name_field, "")) if name_field else "",
                    "district_name": str(properties.get(district_field, "")) if district_field else "",
                    "metric_value": properties.get(area_field) if area_field else None,
                    "metric_label": "영역 면적(㎡)",
                    "x_coordinate": properties.get(x_field) if x_field else None,
                    "y_coordinate": properties.get(y_field) if y_field else None,
                    "geometry": geometry,
                    "payload": {key: json_safe(value) for key, value in properties.items()},
                },
            )
            count += 1
        self.stdout.write(self.style.SUCCESS(f"Imported {count} commercial-area geometries; source coordinates are retained as EPSG:5181."))
        if temporary_directory:
            temporary_directory.cleanup()