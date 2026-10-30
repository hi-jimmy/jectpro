from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Sum
from django.db.models.functions import TruncMonth
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.core.paginator import Paginator

from .models import SeoulGridCell, SeoulOpenRecord, Transaction


DATASET_CONFIG = {
    "living": {"title": "내국인 생활인구(250m)", "source": "OA-22784", "cadence": "매일 1회 · 4일 전 자료", "metric": "생활인구(명)", "dimension": "격자·시간대"},
    "grid": {"title": "서울 격자 파일(250m, 5179, SHP)", "source": "서울 생활인구 격자", "cadence": "공간파일 · EPSG:5179", "metric": "격자", "dimension": "250m 공간격자"},
    "area": {"title": "상권영역", "source": "OA-15560", "cadence": "비정기 갱신 · 파일 제공", "metric": "영역 면적(㎡)", "dimension": "상권"},
    "store": {"title": "점포-상권", "source": "OA-15577", "cadence": "연간 파일 · 분기 데이터", "metric": "점포 수(개)", "dimension": "상권·업종"},
    "sales": {"title": "추정매출-상권", "source": "OA-15572", "cadence": "분기별 파일", "metric": "당월 매출액(원)", "dimension": "상권·업종"},
}


def filtered_transactions(request):
    queryset = Transaction.objects.all()
    year = request.GET.get("year", "")
    district = request.GET.get("district", "")
    building_use = request.GET.get("building_use", "")
    if year.isdigit():
        queryset = queryset.filter(contract_date__year=year)
    if district:
        queryset = queryset.filter(district_name=district)
    if building_use:
        queryset = queryset.filter(building_use=building_use)
    return queryset


@login_required
def dashboard(request):
    return redirect("analytics_dashboard")


@login_required
def analytics_dashboard(request):
    return render(request, "transactions/analytics_dashboard.html")


@login_required
def chart_data(request):
    queryset = filtered_transactions(request)
    monthly = queryset.exclude(contract_date=None).annotate(month=TruncMonth("contract_date")).values("month").annotate(
        count=Count("id"), average=Avg("amount_10k")
    ).order_by("month")
    districts = queryset.values("district_name").annotate(count=Count("id"), average=Avg("amount_10k")).order_by("-count")[:10]
    return JsonResponse({
        "monthly": [{"month": row["month"].strftime("%Y-%m"), "count": row["count"], "average": round(row["average"] or 0)} for row in monthly],
        "districts": [{"name": row["district_name"], "count": row["count"], "average": round(row["average"] or 0)} for row in districts],
    })


@login_required
def open_data_page(request, dataset):
    if dataset not in DATASET_CONFIG:
        raise Http404("Dataset not found")
    config = DATASET_CONFIG[dataset]
    is_grid = dataset == "grid"
    queryset = SeoulGridCell.objects.all() if is_grid else SeoulOpenRecord.objects.filter(dataset=dataset)
    period = request.GET.get("period", "")[:12]
    query = request.GET.get("q", "")[:100].strip()
    if period and not is_grid:
        queryset = queryset.filter(period=period)
    if query:
        if is_grid:
            queryset = queryset.filter(cell_id__icontains=query) | queryset.filter(administrative_code__icontains=query)
        else:
            queryset = queryset.filter(trade_name__icontains=query) | queryset.filter(cell_id__icontains=query) | queryset.filter(category_name__icontains=query) | queryset.filter(district_name__icontains=query) | queryset.filter(trade_code__icontains=query)
    if is_grid:
        summary = {"total": queryset.count(), "average": None, "volume": None}
        periods = []
        records = queryset.order_by("cell_id")
    else:
        summary = queryset.aggregate(total=Count("id"), average=Avg("metric_value"), volume=Sum("metric_value"))
        periods = SeoulOpenRecord.objects.filter(dataset=dataset).exclude(period="").values_list("period", flat=True).distinct().order_by("-period")[:36]
        records = queryset.order_by("-period", "trade_name", "cell_id")
    paginator = Paginator(records, 100)
    page_obj = paginator.get_page(request.GET.get("page", 1))
    if dataset == "area":
        empty_heading = "상권 영역 파일을 데이터베이스에 적재해 주세요."
        empty_description = "이 자료는 공식 페이지에서 ZIP/SHP 파일로 제공되며, Open API 명세는 확인되지 않았습니다."
        empty_command = "python manage.py import_seoul_area path\\to\\official_trade_area.zip"
        extra_note = "상권영역 미리보기에는 상권코드·명, 좌표, 자치구·행정동, 영역면적이 있습니다. 공식 페이지는 EPSG:5181을 안내합니다."
    elif is_grid:
        empty_heading = "서울 250m 격자 파일을 데이터베이스에 적재해 주세요."
        empty_description = "격자 다운로드 파일의 압축을 풀고 .shp, .shx, .dbf, .prj 파일을 같은 폴더에 두세요."
        empty_command = "python manage.py import_seoul_grid path\\to\\grid.shp"
        extra_note = "생활인구 CELL_ID와 연결할 수 있도록 격자 ID·속성·geometry를 EPSG:5179 좌표 그대로 저장합니다."
    else:
        empty_heading = "아직 데이터가 없습니다."
        empty_description = "관리자 권한으로 CSV, XLSX 또는 공식 ZIP 파일을 드래그해 원본 데이터를 적재할 수 있습니다."
        empty_command = f"/admin/transactions/seoulopenrecord/upload/{dataset}/"
        extra_note = "생활인구의 소수 인구 값은 *로 비식별 처리되어 원본 그대로 보존됩니다." if dataset == "living" else "전체 원본 열은 레코드의 payload에 그대로 보존됩니다."
    dataset_count = SeoulGridCell.objects.count() if is_grid else SeoulOpenRecord.objects.filter(dataset=dataset).count()
    return render(request, "transactions/open_data.html", {
        "dataset": dataset,
        "config": config,
        "summary": summary,
        "records": page_obj.object_list,
        "page_obj": page_obj,
        "periods": periods,
        "selected_period": period,
        "query": query,
        "has_data": queryset.exists(),
        "api_url": DATASET_API_URLS.get(dataset, ""),
        "empty_heading": empty_heading,
        "empty_description": empty_description,
        "empty_command": empty_command,
        "extra_note": extra_note,
        "chart_url": f"/api/open-data-chart/{dataset}/?period={period}",
        "is_grid": is_grid,
        "source_type": "SHP" if is_grid else "FILE" if dataset == "area" else "API",
        "dataset_count": dataset_count,
    })


@login_required
def open_data_chart(request, dataset):
    if dataset == "grid":
        return JsonResponse({"timeline": [], "leaders": [], "metric_label": "격자"})
    if dataset not in DATASET_CONFIG:
        return JsonResponse({"error": "Unknown dataset"}, status=404)
    queryset = SeoulOpenRecord.objects.filter(dataset=dataset)
    period = request.GET.get("period", "")[:12]
    if period:
        queryset = queryset.filter(period=period)
    timeline = queryset.values("period").annotate(
        count=Count("id"), total=Sum("metric_value"), average=Avg("metric_value")
    ).order_by("period")[:60]
    group_by = "cell_id" if dataset == "living" else "trade_name"
    leaders = queryset.exclude(**{f"{group_by}__exact": ""}).values(group_by).annotate(
        count=Count("id"), metric=Sum("metric_value")
    ).order_by("-metric", "-count")[:10]
    return JsonResponse({
        "timeline": [{"period": row["period"], "count": row["count"], "total": float(row["total"] or 0), "average": float(row["average"] or 0)} for row in timeline],
        "leaders": [{"name": row[group_by], "count": row["count"], "metric": float(row["metric"] or 0)} for row in leaders],
        "metric_label": DATASET_CONFIG[dataset]["metric"],
    })


DATASET_API_URLS = {
    "living": "https://data.seoul.go.kr/dataList/OA-22784/S/1/datasetView.do",
    "grid": "https://data.seoul.go.kr/dataVisual/seoul/seoulLivingPopulation.do",
    "area": "https://data.seoul.go.kr/dataList/OA-15560/S/1/datasetView.do",
    "store": "https://data.seoul.go.kr/dataList/OA-15577/S/1/datasetView.do",
    "sales": "https://data.seoul.go.kr/dataList/OA-15572/S/1/datasetView.do",
}