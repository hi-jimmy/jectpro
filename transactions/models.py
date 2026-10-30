from django.db import models


class SeoulOpenRecord(models.Model):
    class Dataset(models.TextChoices):
        LIVING = "living", "내국인 생활인구(250m)"
        TRADE_AREA = "trade_area", "상권영역"
        STORE = "store", "점포-상권"
        SALES = "sales", "추정매출-상권"

    dataset = models.CharField("데이터 종류", max_length=20, choices=Dataset.choices, db_index=True)
    record_key = models.CharField("원본 식별키", max_length=64)
    period = models.CharField("기준 시점", max_length=12, blank=True, db_index=True)
    cell_id = models.CharField("250m 격자 ID", max_length=40, blank=True, db_index=True)
    trade_code = models.CharField("상권 코드", max_length=20, blank=True, db_index=True)
    trade_name = models.CharField("상권명", max_length=150, blank=True, db_index=True)
    district_name = models.CharField("자치구", max_length=30, blank=True, db_index=True)
    category_name = models.CharField("업종", max_length=100, blank=True)
    metric_value = models.DecimalField("주요 값", max_digits=20, decimal_places=2, null=True)
    metric_label = models.CharField("주요 값 이름", max_length=40, blank=True)
    x_coordinate = models.DecimalField("X 좌표", max_digits=14, decimal_places=3, null=True)
    y_coordinate = models.DecimalField("Y 좌표", max_digits=14, decimal_places=3, null=True)
    geometry = models.JSONField("공간 도형", null=True, blank=True)
    payload = models.JSONField("원본 데이터", default=dict)
    imported_at = models.DateTimeField("수집 시각", auto_now=True)

    class Meta:
        ordering = ["-period", "trade_name", "cell_id"]
        constraints = [models.UniqueConstraint(fields=["dataset", "record_key"], name="unique_seoul_open_record")]
        indexes = [models.Index(fields=["dataset", "period"]), models.Index(fields=["dataset", "trade_code"])]

    def __str__(self):
        return f"{self.get_dataset_display()} · {self.trade_name or self.cell_id or self.record_key}"

    @property
    def display_name(self):
        return self.trade_name or self.cell_id or self.trade_code or "-"


class SeoulGridCell(models.Model):
    cell_id = models.CharField("250m 격자 ID", max_length=40, unique=True, db_index=True)
    administrative_code = models.CharField("행정동 코드", max_length=12, blank=True)
    geometry = models.JSONField("EPSG:5179 격자 도형")
    properties = models.JSONField("원본 속성", default=dict)
    imported_at = models.DateTimeField("수집 시각", auto_now=True)

    class Meta:
        ordering = ["cell_id"]

    def __str__(self):
        return self.cell_id


class Transaction(models.Model):
    receipt_year = models.CharField("접수연도", max_length=4, blank=True, db_index=True)
    district_code = models.CharField("자치구코드", max_length=5, blank=True)
    district_name = models.CharField("자치구명", max_length=30, blank=True, db_index=True)
    neighborhood_code = models.CharField("법정동코드", max_length=5, blank=True)
    neighborhood_name = models.CharField("법정동명", max_length=50, blank=True)
    lot_type = models.CharField("지번구분", max_length=2, blank=True)
    lot_type_name = models.CharField("지번구분명", max_length=20, blank=True)
    main_lot = models.CharField("본번", max_length=4, blank=True)
    sub_lot = models.CharField("부번", max_length=4, blank=True)
    building_name = models.CharField("건물명", max_length=150, blank=True)
    contract_date = models.DateField("계약일", null=True, db_index=True)
    amount_10k = models.PositiveBigIntegerField("거래금액(만원)", null=True)
    building_area = models.DecimalField("건물면적(㎡)", max_digits=10, decimal_places=2, null=True)
    land_area = models.DecimalField("토지면적(㎡)", max_digits=10, decimal_places=2, null=True)
    floor = models.DecimalField("층", max_digits=6, decimal_places=1, null=True)
    right_type = models.CharField("권리구분", max_length=30, blank=True)
    cancellation_date = models.CharField("취소일", max_length=10, blank=True)
    construction_year = models.CharField("건축년도", max_length=4, blank=True)
    building_use = models.CharField("건물용도", max_length=30, blank=True, db_index=True)
    report_type = models.CharField("신고구분", max_length=30, blank=True)
    agent_district = models.CharField("중개사 시군구", max_length=60, blank=True)
    source_updated_at = models.DateTimeField("원본 수집 시각", auto_now=True)

    class Meta:
        ordering = ["-contract_date", "-id"]
        indexes = [models.Index(fields=["district_name", "contract_date"])]

    def __str__(self):
        return f"{self.contract_date} {self.district_name} {self.building_name}"