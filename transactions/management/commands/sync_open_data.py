import hashlib
import json
import os
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from transactions.models import SeoulOpenRecord


API_URL = "http://openapi.seoul.go.kr:8088"
DATASETS = {
    "living": {"service": "Se250MSpopLocalResd", "model": SeoulOpenRecord.Dataset.LIVING},
    "store": {"service": "VwsmTrdarStorQq", "model": SeoulOpenRecord.Dataset.STORE, "filter": "STDR_YYQU_CD"},
    "sales": {"service": "VwsmTrdarSelngQq", "model": SeoulOpenRecord.Dataset.SALES, "filter": "STDR_YYQU_CD"},
}


def first_value(row, *keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return ""


def decimal_value(value):
    if value in (None, "", "*"):
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def make_record(dataset, row):
    data_type = DATASETS[dataset]["model"] if dataset in DATASETS else SeoulOpenRecord.Dataset.TRADE_AREA
    period = str(first_value(row, "YMD", "STDR_YYQU_CD", "기준_년분기_코드", "일자"))
    cell_id = str(first_value(row, "CELL_ID", "GRID_ID", "250M격자", "250m격자", "250M격자ID"))
    trade_code = str(first_value(row, "TRDAR_CD", "TRDAR_CODE", "상권_코드"))
    trade_name = str(first_value(row, "TRDAR_CD_NM", "TRDAR_NM", "TRDAR_NAME", "상권_코드_명"))
    category_name = str(first_value(row, "SVC_INDUTY_CD_NM", "SVC_INDUTY_NM", "INDUTY_NM", "서비스_업종_코드_명"))
    service_code = str(first_value(row, "SVC_INDUTY_CD", "서비스_업종_코드"))
    metric_label = "생활인구" if dataset == "living" else "점포 수" if dataset == "store" else "당월 매출액"
    metric_value = first_value(row, "SPOP", "SIMILR_INDUTY_STOR_CO", "SIMILR_INDUTY_STOR_CO", "THSMON_SELNG_AMT", "당월_매출_금액", "생활인구합계", "영역_면적")
    key_fields = {
        "living": (
            period.strip(),
            str(first_value(row, "TT", "시간")).strip(),
            str(first_value(row, "H_DNG_CD", "행정동코드")).strip(),
            cell_id.strip(),
        ),
        "store": (period, trade_code, service_code),
        "sales": (period, trade_code, service_code),
        "area": (trade_code or trade_name,),
    }.get(dataset, ())
    key_payload = "|".join(key_fields)
    if not any(key_fields):
        key_payload = json.dumps(row, ensure_ascii=False, sort_keys=True)
    record_key = hashlib.sha256(key_payload.encode("utf-8")).hexdigest()
    return SeoulOpenRecord(
        dataset=data_type,
        record_key=record_key,
        period=period,
        cell_id=cell_id,
        trade_code=trade_code,
        trade_name=trade_name,
        district_name=str(first_value(row, "SIGNGU_CD_NM", "SIGNGU_NM", "CGG_NM")),
        category_name=category_name,
        metric_value=decimal_value(metric_value),
        metric_label=metric_label,
        x_coordinate=decimal_value(first_value(row, "XCNTS_VALUE", "X_VALUE", "X", "엑스좌표_값")),
        y_coordinate=decimal_value(first_value(row, "YDNTS_VALUE", "Y_VALUE", "Y", "와이좌표_값")),
        payload=row,
    )


class Command(BaseCommand):
    help = "Import Seoul living-population, store, sales, or trade-area data."

    def add_arguments(self, parser):
        parser.add_argument("--dataset", required=True, choices=("living", "store", "sales"))
        parser.add_argument("--limit", type=int, default=1000, help="Maximum API rows (each request is limited to 1000)")
        parser.add_argument("--quarter", help="Optional YYYYQ quarter code such as 20252, for store/sales")
        parser.add_argument("--sample", action="store_true", help="Use Seoul's public sample key (up to 5 rows)")

    def handle(self, *args, **options):
        dataset = options["dataset"]
        if options["limit"] < 1:
            raise CommandError("--limit must be at least 1")
        key = "sample" if options["sample"] else os.getenv("SEOUL_API_KEY", "").strip()
        if not key:
            raise CommandError("SEOUL_API_KEY is not set. Request an OpenAPI key from Seoul Open Data Plaza.")
        service = DATASETS[dataset]["service"]
        page_size = min(options["limit"], 1000)
        inserted = updated = 0
        api_total = 0
        for start in range(1, options["limit"] + 1, page_size):
            end = min(start + page_size - 1, options["limit"])
            url = f"{API_URL}/{quote(key, safe='')}/json/{service}/{start}/{end}/"
            if options["quarter"] and dataset in ("store", "sales"):
                url += f"{quote(options['quarter'], safe='')}/"
            try:
                response = requests.get(url, timeout=45)
                response.raise_for_status()
                payload = response.json().get(service, {})
            except (requests.RequestException, ValueError) as exc:
                raise CommandError(f"Seoul API request failed: {exc}") from exc
            result = payload.get("RESULT", {})
            if result.get("CODE") not in (None, "INFO-000", "INFO-200"):
                raise CommandError(f"Seoul API error {result.get('CODE')}: {result.get('MESSAGE')}")
            api_total = int(payload.get("list_total_count") or api_total)
            rows = payload.get("row", [])
            if not rows:
                break
            with transaction.atomic():
                for source in rows:
                    record = make_record(dataset, source)
                    _, created = SeoulOpenRecord.objects.update_or_create(
                        dataset=record.dataset,
                        record_key=record.record_key,
                        defaults={
                            "period": record.period,
                            "cell_id": record.cell_id,
                            "trade_code": record.trade_code,
                            "trade_name": record.trade_name,
                            "district_name": record.district_name,
                            "category_name": record.category_name,
                            "metric_value": record.metric_value,
                            "metric_label": record.metric_label,
                            "x_coordinate": record.x_coordinate,
                            "y_coordinate": record.y_coordinate,
                            "payload": record.payload,
                        },
                    )
                    inserted += int(created)
                    updated += int(not created)
            self.stdout.write(f"Imported rows {start}-{end}")
            if len(rows) < end - start + 1:
                break
            if end < options["limit"]:
                time.sleep(0.15)
        self.stdout.write(self.style.SUCCESS(f"Done: {inserted} inserted, {updated} updated; API total={api_total}"))

