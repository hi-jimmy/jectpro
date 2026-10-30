import csv
import hashlib
import io
import re
import shutil
import tempfile
import zipfile
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from transactions.management.commands.sync_open_data import DATASETS, make_record
from transactions.models import SeoulOpenRecord


DATASET_INFO = {
    "living": {"id": "OA-22784", "url": "https://data.seoul.go.kr/dataList/OA-22784/S/1/datasetView.do", "inf_seq": "1", "model": SeoulOpenRecord.Dataset.LIVING},
    "store": {"id": "OA-15577", "url": "https://data.seoul.go.kr/dataList/OA-15577/S/1/datasetView.do", "inf_seq": "3", "model": SeoulOpenRecord.Dataset.STORE},
    "sales": {"id": "OA-15572", "url": "https://data.seoul.go.kr/dataList/OA-15572/S/1/datasetView.do", "inf_seq": "3", "model": SeoulOpenRecord.Dataset.SALES},
}
DOWNLOAD_URL = "https://datafile.seoul.go.kr/bigfile/iot/inf/nio_download.do?&useCache=false"


class ArchiveListParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.current = None
        self.files = []
        self.in_cell = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr" and re.fullmatch(r"fileTr_\d+", attrs.get("id", "")):
            self.current = {"cells": []}
        if self.current is not None and tag == "td":
            self.current["cells"].append("")
            self.in_cell = True
        if self.current is not None and tag in ("span", "a"):
            title = attrs.get("title", "")
            if title.lower().endswith(".zip"):
                self.current["name"] = title
            handler = attrs.get("onclick", "")
            match = re.search(r"downloadFile\(['\"]([^'\"]+)['\"]\)", handler)
            if match:
                self.current["seq"] = match.group(1)

    def handle_data(self, data):
        if self.current is not None and self.in_cell and self.current["cells"]:
            self.current["cells"][-1] += data.strip()

    def handle_endtag(self, tag):
        if tag == "td":
            self.in_cell = False
        if tag == "tr" and self.current is not None:
            if self.current.get("name") and self.current.get("seq"):
                try:
                    self.current["size_mb"] = float(self.current["cells"][3])
                except (IndexError, ValueError):
                    self.current["size_mb"] = 0
                self.files.append(self.current)
            self.current = None


def normalize_csv_row(row):
    return {
        str(key or "").strip().upper(): (value.strip() if isinstance(value, str) else value)
        for key, value in row.items()
        if key is not None
    }


def archive_period(name):
    match = re.search(r"(20\d{2})(\d{2})(\d{2})?\.zip$", name, re.IGNORECASE)
    if not match:
        return None
    year, month, day = match.groups()
    return date(int(year), int(month), int(day or 1))


class Command(BaseCommand):
    help = "Download and batch-import all visible official Seoul population/store/sales ZIP archives."

    def add_arguments(self, parser):
        parser.add_argument("--dataset", choices=("living", "store", "sales", "all"), default="all")
        parser.add_argument("--max-files", type=int, help="Import only the first N files per selected dataset; useful for a safe trial")
        parser.add_argument("--from-date", help="Include archive periods on or after YYYY-MM-DD")
        parser.add_argument("--to-date", help="Include archive periods on or before YYYY-MM-DD")
        parser.add_argument("--encoding", default="auto", help="CSV encoding (auto detects UTF-8 or CP949; either can be forced)")
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--force-large-import", action="store_true", help="Override the SQLite storage estimate safeguard for all living-population archives")

    def handle(self, *args, **options):
        if options["max_files"] is not None and options["max_files"] < 1:
            raise CommandError("--max-files must be at least 1")
        if options["batch_size"] < 1:
            raise CommandError("--batch-size must be at least 1")
        start_date = self.parse_date(options["from_date"], "--from-date")
        end_date = self.parse_date(options["to_date"], "--to-date")
        datasets = ("living", "store", "sales") if options["dataset"] == "all" else (options["dataset"],)
        for dataset in datasets:
            files = self.get_file_list(dataset)
            if start_date or end_date:
                files = [item for item in files if self.in_date_range(item["name"], start_date, end_date)]
            if options["max_files"]:
                files = files[:options["max_files"]]
            if not files:
                self.stdout.write(self.style.WARNING(f"{dataset}: no archives match the selected range"))
                continue
            if dataset == "living" and not options["max_files"] and not options["force_large_import"]:
                compressed_bytes = sum(item.get("size_mb", 0) for item in files) * 1024 * 1024
                estimated_db_bytes = compressed_bytes * 12
                free_bytes = shutil.disk_usage(Path.cwd()).free
                if estimated_db_bytes > free_bytes:
                    required_gb = estimated_db_bytes / (1024 ** 3)
                    free_gb = free_bytes / (1024 ** 3)
                    raise CommandError(
                        f"{len(files)} living-population archives total about {compressed_bytes / (1024 ** 3):.1f} GB compressed. "
                        f"A row database is conservatively estimated to need about {required_gb:.1f} GB, but this drive has {free_gb:.1f} GB free. "
                        "Use a larger MariaDB volume or limit the date range with --from-date/--to-date."
                    )
            self.stdout.write(f"{dataset}: {len(files)} archive(s) queued")
            for index, file_info in enumerate(files, 1):
                rows = self.import_archive(dataset, file_info, options)
                self.stdout.write(self.style.SUCCESS(f"[{index}/{len(files)}] {file_info['name']}: read {rows:,} rows (duplicate keys ignored)"))

    @staticmethod
    def parse_date(value, option_name):
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise CommandError(f"{option_name} must use YYYY-MM-DD") from exc

    @staticmethod
    def in_date_range(name, start_date, end_date):
        period = archive_period(name)
        if not period:
            return True
        if start_date and period < start_date.replace(day=1):
            return False
        if end_date and period > end_date:
            return False
        return True

    def get_file_list(self, dataset):
        info = DATASET_INFO[dataset]
        try:
            response = requests.get(info["url"], timeout=45)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise CommandError(f"Could not read official {dataset} archive list: {exc}") from exc
        parser = ArchiveListParser()
        parser.feed(response.text)
        if not parser.files:
            raise CommandError(f"No ZIP files were found on the official {dataset} page.")
        return parser.files

    def import_archive(self, dataset, file_info, options):
        info = DATASET_INFO[dataset]
        with requests.Session() as session:
            try:
                response = session.post(
                    DOWNLOAD_URL,
                    data={"infId": info["id"], "seqNo": "", "seq": file_info["seq"], "infSeq": info["inf_seq"]},
                    headers={"Referer": info["url"]},
                    stream=True,
                    timeout=(30, 180),
                )
                response.raise_for_status()
            except requests.RequestException as exc:
                raise CommandError(f"Download failed for {file_info['name']}: {exc}") from exc

            with tempfile.NamedTemporaryFile(prefix="seoul-archive-", suffix=".zip", delete=False) as temp_file:
                temp_path = Path(temp_file.name)
                try:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            temp_file.write(chunk)
                finally:
                    response.close()

        try:
            if not zipfile.is_zipfile(temp_path):
                raise CommandError(f"Official download did not return a ZIP for {file_info['name']}.")
            with zipfile.ZipFile(temp_path) as archive:
                csv_entries = [entry for entry in archive.infolist() if entry.filename.lower().endswith((".csv", ".txt"))]
                if not csv_entries:
                    raise CommandError(f"No CSV/TXT file found inside {file_info['name']}.")
                rows_read = 0
                for entry in csv_entries:
                    with archive.open(entry) as raw_file:
                        encoding = options["encoding"]
                        if encoding == "auto":
                            sample = raw_file.read(8192)
                            raw_file.seek(0)
                            try:
                                sample.decode("utf-8-sig")
                                encoding = "utf-8-sig"
                            except UnicodeDecodeError:
                                encoding = "cp949"
                        text_file = io.TextIOWrapper(raw_file, encoding=encoding, errors="replace", newline="")
                        reader = csv.DictReader(text_file)
                        batch = []
                        for source in reader:
                            row = normalize_csv_row(source)
                            record = make_record(dataset, row)
                            record.payload = row
                            if dataset == "living":
                                record.period = str(row.get("일자", record.period))
                                record.cell_id = str(row.get("250M격자", record.cell_id))
                            elif dataset in ("store", "sales"):
                                key_parts = (
                                    record.period,
                                    record.trade_code,
                                    str(row.get("SVC_INDUTY_CD", row.get("서비스_업종_코드", ""))),
                                )
                                record.record_key = hashlib.sha256("|".join(key_parts).encode("utf-8")).hexdigest()
                            batch.append(record)
                            rows_read += 1
                            if len(batch) >= options["batch_size"]:
                                self.save_batch(dataset, batch, options["batch_size"])
                                batch = []
                                if rows_read % 100000 == 0:
                                    self.stdout.write(f"  {file_info['name']}: {rows_read:,} rows streamed")
                        if batch:
                            self.save_batch(dataset, batch, options["batch_size"])
                        text_file.detach()
                return rows_read
        finally:
            temp_path.unlink(missing_ok=True)

    @staticmethod
    def save_batch(dataset, records, batch_size):
        with transaction.atomic():
            SeoulOpenRecord.objects.bulk_create(records, batch_size=batch_size, ignore_conflicts=True)