import os
import time
from urllib.parse import quote
from datetime import datetime

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from transactions.models import Transaction


API_URL = "http://openapi.seoul.go.kr:8088"
SERVICE = "tbLnOpendataRtmsV"
FIELD_MAP = {
    "RCPT_YR": "receipt_year", "CGG_CD": "district_code", "CGG_NM": "district_name",
    "STDG_CD": "neighborhood_code", "STDG_NM": "neighborhood_name", "LOTNO_SE": "lot_type",
    "LOTNO_SE_NM": "lot_type_name", "MNO": "main_lot", "SNO": "sub_lot", "BLDG_NM": "building_name",
    "CTRT_DAY": "contract_date", "THING_AMT": "amount_10k", "ARCH_AREA": "building_area",
    "LAND_AREA": "land_area", "FLR": "floor", "RGHT_SE": "right_type", "RTRCN_DAY": "cancellation_date",
    "ARCH_YR": "construction_year", "BLDG_USG": "building_use", "DCLR_SE": "report_type",
    "OPBIZ_RESTAGNT_SGG_NM": "agent_district",
}


class Command(BaseCommand):
    help = "Fetch Seoul real-estate transactions from OA-21275 and save them locally."

    def add_arguments(self, parser):
        parser.add_argument("--year", help="Receipt year, for example 2025")
        parser.add_argument("--district-code", help="Five-digit Seoul district code")
        parser.add_argument("--building-use", help="Optional value: 아파트, 단독다가구, 연립다세대, 오피스텔")
        parser.add_argument("--limit", type=int, default=1000, help="Maximum rows requested (API allows at most 1000 per request)")
        parser.add_argument("--sample", action="store_true", help="Use Seoul's documented sample key; limited sample data only")

    def handle(self, *args, **options):
        key = "sample" if options["sample"] else os.getenv("SEOUL_API_KEY", "").strip()
        if not key:
            raise CommandError("SEOUL_API_KEY is not set. Request a key from Seoul Open Data Plaza, then set it in the environment.")
        if options["limit"] < 1:
            raise CommandError("--limit must be at least 1")

        inserted = updated = 0
        total = None
        page_size = min(options["limit"], 1000)
        for start in range(1, options["limit"] + 1, page_size):
            end = min(start + page_size - 1, options["limit"])
            segments = [options["year"] or "", options["district_code"] or ""]
            if options["building_use"]:
                segments.extend([""] * 8)
                segments.append(options["building_use"])
            while segments and not segments[-1]:
                segments.pop()
            filter_path = "/".join(quote(str(value), safe="") for value in segments)
            url = f"{API_URL}/{key}/json/{SERVICE}/{start}/{end}/"
            if filter_path:
                url += f"{filter_path}/"
            try:
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                payload = response.json().get(SERVICE, {})
            except (requests.RequestException, ValueError) as exc:
                raise CommandError(f"Seoul API request failed: {exc}") from exc

            result = payload.get("RESULT", {})
            if result.get("CODE") not in (None, "INFO-000", "INFO-200"):
                raise CommandError(f"Seoul API error {result.get('CODE')}: {result.get('MESSAGE')}")
            total = payload.get("list_total_count", total)
            rows = payload.get("row", [])
            if not rows:
                break
            with transaction.atomic():
                for source in rows:
                    values = {field: source.get(api_name) for api_name, field in FIELD_MAP.items()}
                    raw_date = str(values.pop("contract_date") or "")
                    try:
                        values["contract_date"] = datetime.strptime(raw_date, "%Y%m%d").date() if raw_date else None
                    except ValueError:
                        values["contract_date"] = None
                    for numeric_field in ("amount_10k", "building_area", "land_area", "floor"):
                        raw_value = values.get(numeric_field)
                        try:
                            values[numeric_field] = raw_value if raw_value not in (None, "") else None
                        except (TypeError, ValueError):
                            values[numeric_field] = None
                    item, created = Transaction.objects.update_or_create(
                        district_code=values.get("district_code", ""),
                        neighborhood_code=values.get("neighborhood_code", ""),
                        contract_date=values.get("contract_date"),
                        building_name=values.get("building_name", ""),
                        amount_10k=values.get("amount_10k"),
                        building_area=values.get("building_area"),
                        defaults=values,
                    )
                    if created:
                        inserted += 1
                    else:
                        updated += 1
            self.stdout.write(f"Fetched {len(rows)} rows ({start}-{end})")
            if len(rows) < end - start + 1:
                break
            if end < options["limit"]:
                time.sleep(0.15)

        self.stdout.write(self.style.SUCCESS(f"Done: {inserted} inserted, {updated} updated; API total={total or 0}"))