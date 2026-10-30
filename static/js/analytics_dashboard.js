(() => {
  const $ = (id) => document.getElementById(id);
  const datasetSelect = $("analysis-dataset");
  const periodSelect = $("analysis-period");
  const districtSelect = $("analysis-district");
  const hourSelect = $("analysis-hour");
  const categorySelect = $("analysis-category");
  const metricSelect = $("analysis-metric");
  const charts = {};
  const datasetLabels = {
    living: "내국인 생활인구",
    sales: "추정매출",
    store: "점포 현황",
    area: "상권영역",
  };
  const storeMetrics = [
    { key: "store_count", label: "점포 수(개)", unit: "개" },
    { key: "open_count", label: "개업 점포 수(개)", unit: "개" },
    { key: "close_count", label: "폐업 점포 수(개)", unit: "개" },
    { key: "franchise_count", label: "프랜차이즈 점포 수(개)", unit: "개" },
  ];
  const livingMetrics = [
    { key: "average_daily_population", label: "일평균 생활인구(명)", unit: "명" },
    { key: "average_daily_observed_cells", label: "일평균 유효 격자 수", unit: "개" },
  ];
  let payload;

  function showError(message) {
    const error = $("analysis-error");
    error.textContent = message;
    error.hidden = false;
    $("analysis-status").textContent = "분석 데이터 오류";
  }

  function setOptions(select, options, selectedValue) {
    select.replaceChildren();
    for (const option of options) {
      select.add(new Option(option.label, option.value));
    }
    if (selectedValue && options.some((option) => option.value === selectedValue)) {
      select.value = selectedValue;
    }
  }

  function formatPeriod(value) {
    if (/^\d{6}$/.test(value)) {
      return `${value.slice(0, 4)}년 ${Number(value.slice(4))}월`;
    }
    if (/^\d{5}$/.test(value)) {
      return `${value.slice(0, 4)}년 ${value.slice(4)}분기`;
    }
    return value || "전체";
  }

  function valueOf(row, dataset, metric) {
    if (dataset === "sales") return row.metrics?.[metric] ?? 0;
    return Number(row[metric] ?? 0);
  }

  function selectedRows(dataset) {
    return dataset === "area" ? payload.trade_areas || [] : payload[dataset] || [];
  }

  function metricOptions(dataset) {
    if (dataset === "living") return livingMetrics;
    if (dataset === "store") return storeMetrics;
    if (dataset === "area") {
      return [
        { key: "trade_area_count", label: "상권영역 수(개)", unit: "개" },
        { key: "area_m2", label: "상권영역 면적(㎡)", unit: "㎡" },
      ];
    }
    const metrics = new Set();
    for (const row of selectedRows("sales")) {
      for (const key of Object.keys(row.metrics || {})) metrics.add(key);
    }
    const options = [...metrics].sort().map((key) => ({
      key,
      label: key.replaceAll("_", " "),
      unit: key.includes("금액") ? "원" : "건",
    }));
    return options.length ? options : [{ key: "", label: "분석 지표 없음", unit: "" }];
  }

  function updateFilters() {
    const dataset = datasetSelect.value;
    const rows = selectedRows(dataset);
    const oldPeriod = periodSelect.value;
    const oldDistrict = districtSelect.value;
    const oldCategory = categorySelect.value;
    const oldMetric = metricSelect.value;
    const periods = [...new Set(rows.map((row) => row.period).filter(Boolean))].sort().reverse();
    setOptions(
      periodSelect,
      periods.length
        ? periods.map((value) => ({ value, label: formatPeriod(value) }))
        : [{ value: "", label: "해당 없음" }],
      periods.includes(oldPeriod) ? oldPeriod : periods[0]
    );
    const districts = [...new Set(
      dataset === "area"
        ? rows.map((row) => row.district)
        : payload.districts.map((district) => district.name)
    )].filter(Boolean).sort((a, b) => a.localeCompare(b, "ko"));
    setOptions(
      districtSelect,
      [{ value: "", label: "서울 전체" }, ...districts.map((value) => ({ value, label: value }))],
      oldDistrict
    );
    const categories = [...new Set(rows.map((row) => row.category).filter(Boolean))]
      .sort((a, b) => a.localeCompare(b, "ko"));
    setOptions(
      categorySelect,
      [{ value: "", label: "전체 업종" }, ...categories.map((value) => ({ value, label: value }))],
      oldCategory
    );
    const metrics = metricOptions(dataset);
    setOptions(metricSelect, metrics.map((item) => ({ value: item.key, label: item.label })), oldMetric);
    $("analysis-hour-filter").hidden = dataset !== "living";
    $("analysis-category-filter").hidden = !["store", "sales"].includes(dataset);
    $("timeline-title").textContent = dataset === "area" ? "자치구별 상권 면적" : "기간별 흐름";
    $("rank-title").textContent = dataset === "area" ? "자치구별 상권 수" : "자치구 비교";
    $("profile-title").textContent = dataset === "living"
      ? "시간대별 생활인구"
      : dataset === "area" ? "상권영역 면적 분포" : "업종별 구성";
    renderDashboard();
  }

  function chosenMetric(dataset) {
    const options = metricOptions(dataset);
    return options.find((item) => item.key === metricSelect.value) || options[0];
  }

  function aggregate(rows, keyFunction, metric, dataset) {
    const totals = new Map();
    for (const row of rows) {
      const key = keyFunction(row);
      if (!key) continue;
      totals.set(key, (totals.get(key) || 0) + valueOf(row, dataset, metric));
    }
    return [...totals.entries()].map(([label, value]) => ({ label, value }));
  }

  function chart(id, config) {
    if (charts[id]) charts[id].destroy();
    const context = $(id).getContext("2d");
    charts[id] = new Chart(context, config);
  }

  function chartOptions(horizontal = false) {
    return {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: horizontal ? "y" : "x",
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (context) => formatNumber(context.parsed[horizontal ? "x" : "y"]) } },
      },
      scales: {
        x: { grid: { color: "#edf0ec" }, ticks: { color: "#6c776f", maxRotation: 0 } },
        y: { grid: { color: horizontal ? "#edf0ec" : "transparent" }, ticks: { color: "#6c776f" } },
      },
    };
  }

  function renderChart(id, entries, type, horizontal = false) {
    const options = chartOptions(horizontal);
    chart(id, {
      type,
      data: {
        labels: entries.map((item) => item.label),
        datasets: [{
          data: entries.map((item) => item.value),
          backgroundColor: type === "line" ? "rgba(49, 87, 68, 0.12)" : "#b7d6c5",
          borderColor: "#315744",
          borderWidth: 2,
          pointRadius: type === "line" ? 3 : 0,
          pointBackgroundColor: "#d55b3f",
          fill: type === "line",
          tension: 0.28,
        }],
      },
      options,
    });
  }

  function formatNumber(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "-";
    return new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 1 }).format(number);
  }

  function districtFilter(rows) {
    const district = districtSelect.value;
    return district ? rows.filter((row) => row.district === district) : rows;
  }

  function periodFilter(rows) {
    const period = periodSelect.value;
    return period ? rows.filter((row) => row.period === period) : rows;
  }

  function renderDashboard() {
    const dataset = datasetSelect.value;
    const rows = selectedRows(dataset);
    const metric = chosenMetric(dataset);
    const periodRows = periodFilter(rows);
    const selected = districtFilter(periodRows).filter((row) => {
      if (dataset === "living") return Number(row.hour) === Number(hourSelect.value);
      if (["store", "sales"].includes(dataset) && categorySelect.value) {
        return row.category === categorySelect.value;
      }
      return true;
    });

    $("analysis-error").hidden = true;
    $("analysis-status").textContent = rows.length ? "집계 데이터 준비 완료" : "데이터 없음";
    $("analysis-generated").textContent = payload.metadata.generated_at
      ? `최종 집계 ${new Date(payload.metadata.generated_at).toLocaleString("ko-KR")}`
      : "ZIP 원본 스트리밍 집계";
    $("timeline-unit").textContent = metric.unit;
    $("rank-unit").textContent = metric.unit;
    $("profile-unit").textContent = metric.unit;

    let timeline;
    let ranking;
    let profile;
    if (dataset === "area") {
      const filteredAreas = districtFilter(rows);
      timeline = aggregate(filteredAreas, (row) => row.district, metric.key, dataset)
        .sort((a, b) => a.label.localeCompare(b.label, "ko"));
      ranking = [...timeline].sort((a, b) => b.value - a.value).slice(0, 12);
      profile = [...timeline].sort((a, b) => b.value - a.value).slice(0, 10);
    } else {
      const trendRows = districtFilter(rows).filter((row) => {
        if (dataset === "living") return Number(row.hour) === Number(hourSelect.value);
        return !categorySelect.value || row.category === categorySelect.value;
      });
      timeline = aggregate(trendRows, (row) => row.period, metric.key, dataset)
        .sort((a, b) => a.label.localeCompare(b.label));
      const selectedForRank = periodFilter(rows).filter((row) => {
        if (dataset === "living") return Number(row.hour) === Number(hourSelect.value);
        return !categorySelect.value || row.category === categorySelect.value;
      });
      ranking = aggregate(selectedForRank, (row) => row.district, metric.key, dataset)
        .sort((a, b) => b.value - a.value).slice(0, 12);
      if (dataset === "living") {
        const selectedForProfile = districtFilter(periodRows);
        profile = aggregate(selectedForProfile, (row) => `${String(row.hour).padStart(2, "0")}시`, metric.key, dataset)
          .sort((a, b) => a.label.localeCompare(b.label));
      } else {
        const selectedForProfile = districtFilter(periodRows);
        profile = aggregate(selectedForProfile, (row) => row.category, metric.key, dataset)
          .sort((a, b) => b.value - a.value).slice(0, 10);
      }
    }

    renderChart("analysis-timeline", timeline, dataset === "area" ? "bar" : "line");
    renderChart("analysis-rank", ranking, "bar", true);
    renderChart("analysis-profile", profile, "bar");
    renderTable(selected, dataset, metric);
    renderMetrics(selected, rows, dataset, metric);
    renderNotes(dataset);
  }

  function renderTable(rows, dataset, metric) {
    let entries;
    if (dataset === "area") {
      entries = aggregate(rows, (row) => row.district, metric.key, dataset)
        .map((item) => ({ district: item.label, category: "상권영역", value: item.value }));
    } else if (dataset === "living") {
      entries = aggregate(rows, (row) => row.district, metric.key, dataset)
        .map((item) => ({ district: item.label, category: `${hourSelect.value}시`, value: item.value }));
    } else {
      const grouped = new Map();
      for (const row of rows) {
        const key = `${row.district}\u0000${row.category}`;
        grouped.set(key, (grouped.get(key) || 0) + valueOf(row, dataset, metric.key));
      }
      entries = [...grouped.entries()].map(([key, value]) => {
        const [district, category] = key.split("\u0000");
        return { district, category, value };
      });
    }
    entries.sort((a, b) => b.value - a.value);
    const body = $("analysis-results");
    body.replaceChildren();
    $("table-count").textContent = `${formatPeriod(periodSelect.value)} · 상위 ${Math.min(entries.length, 20)}건`;
    if (!entries.length) {
      const row = body.insertRow();
      const cell = row.insertCell();
      cell.colSpan = 4;
      cell.className = "empty-cell";
      cell.textContent = "선택한 조건에 해당하는 집계 결과가 없습니다.";
      return;
    }
    for (const [index, item] of entries.slice(0, 20).entries()) {
      const row = body.insertRow();
      row.insertCell().textContent = String(index + 1).padStart(2, "0");
      row.insertCell().textContent = item.district || "미분류";
      row.insertCell().textContent = item.category || "-";
      const value = row.insertCell();
      value.className = "number-cell";
      value.textContent = `${formatNumber(item.value)} ${metric.unit}`;
    }
  }

  function renderMetrics(rows, allRows, dataset, metric) {
    const valueSum = rows.reduce((total, row) => total + valueOf(row, dataset, metric.key), 0);
    $("metric-title-1").textContent = "분석 기간";
    $("metric-value-1").textContent = dataset === "area"
      ? "파일 기준"
      : formatPeriod(periodSelect.value);
    $("metric-note-1").textContent = dataset === "living"
      ? `시작 ${formatPeriod(payload.metadata.living.period_start)} · 종료 ${formatPeriod(payload.metadata.living.period_end)}`
      : `${datasetLabels[dataset]} 원본 기준`;
    $("metric-title-2").textContent = "집계 레코드";
    $("metric-value-2").textContent = formatNumber(rows.length);
    $("metric-note-2").textContent = "현재 선택 조건";
    $("metric-title-3").textContent = metric.label;
    $("metric-value-3").textContent = formatNumber(valueSum);
    $("metric-note-3").textContent = "선택 조건 합계";
    $("metric-value-4").textContent = formatNumber(payload.metadata.grid.cell_count || 0);
    $("analysis-source-count").textContent =
      `원본 행 ${formatNumber(payload.metadata[dataset]?.source_rows || payload.metadata.trade_area.records)} · 집계 ${formatNumber(allRows.length)}행`;
  }

  function renderNotes(dataset) {
    const notes = [];
    if (dataset === "living") {
      notes.push("생활인구는 월·시간대·자치구별 일평균으로 집계했습니다.");
      notes.push(`합계가 *로 비식별된 ${formatNumber(payload.metadata.living.masked_rows)}개 원본 행은 수치에서 제외했습니다.`);
      notes.push("유효 격자 수와 인구 합계는 공개자료의 비식별 처리로 실제 값과 차이가 날 수 있습니다.");
    } else if (dataset === "sales") {
      notes.push("추정매출은 분기·자치구·업종별 합계입니다. 금액 단위는 원입니다.");
      notes.push(`동일 내용의 중복 CSV ${formatNumber(payload.metadata.sales.duplicate_csv_files_skipped)}개는 한 번만 반영했습니다.`);
    } else if (dataset === "store") {
      notes.push("점포 자료는 분기·자치구·업종별 점포 및 개·폐업 수 합계입니다.");
      notes.push("상권코드와 상권영역 파일을 연결해 자치구 단위로 묶었습니다.");
    } else {
      notes.push("상권영역 SHP의 자치구별 영역 수와 면적을 요약했습니다.");
      notes.push("면적 단위는 원본 SHP 속성 기준 ㎡이며, 지도 경계는 표시하지 않습니다.");
    }
    notes.push(`분석 원본: ${payload.metadata.sources.length}개 ZIP 파일`);
    const list = $("analysis-notes");
    list.replaceChildren();
    for (const note of notes) {
      const item = document.createElement("li");
      item.textContent = note;
      list.append(item);
    }
  }

  async function initialize() {
    if (typeof Chart === "undefined") {
      showError("차트 라이브러리를 불러오지 못했습니다. 네트워크 연결을 확인한 뒤 새로고침해 주세요.");
      return;
    }
    try {
      const response = await fetch($("analysis-data-config").dataset.url, { credentials: "same-origin" });
      if (!response.ok) throw new Error(`분석 JSON 요청 실패 (HTTP ${response.status})`);
      payload = await response.json();
      if (!payload.metadata || !Array.isArray(payload.districts)) {
        throw new Error("분석 JSON 형식이 올바르지 않습니다.");
      }
      setOptions(hourSelect, Array.from({ length: 24 }, (_, hour) => ({
        value: String(hour),
        label: `${String(hour).padStart(2, "0")}시`,
      })), "12");
      datasetSelect.addEventListener("change", updateFilters);
      for (const select of [periodSelect, districtSelect, hourSelect, categorySelect, metricSelect]) {
        select.addEventListener("change", renderDashboard);
      }
      updateFilters();
    } catch (error) {
      showError(`분석 데이터를 표시할 수 없습니다: ${error.message}`);
    }
  }

  initialize();
})();
