const chartUrl = document.getElementById("chart-config").dataset.url;

if (window.Chart) {
    fetch(chartUrl)
        .then((response) => response.json())
        .then((data) => {
            const monthlyCanvas = document.getElementById("monthly-chart");
            if (!monthlyCanvas) return;

            new Chart(monthlyCanvas, {
                data: {
                    labels: data.monthly.map((item) => item.month),
                    datasets: [
                        { type: "bar", label: "거래 건수", data: data.monthly.map((item) => item.count), backgroundColor: "#b7d6c5", borderRadius: 3, yAxisID: "y" },
                        { type: "line", label: "평균금액 (만원)", data: data.monthly.map((item) => item.average), borderColor: "#d55b3f", backgroundColor: "#d55b3f", pointRadius: 2, tension: 0.3, yAxisID: "y1" },
                    ],
                },
                options: {
                    maintainAspectRatio: false,
                    interaction: { mode: "index", intersect: false },
                    plugins: { legend: { position: "bottom", align: "start", labels: { usePointStyle: true, boxWidth: 8, color: "#525c54", padding: 18 } } },
                    scales: {
                        x: { grid: { display: false }, ticks: { color: "#69736b", maxRotation: 0, autoSkip: true, maxTicksLimit: 10 } },
                        y: { beginAtZero: true, grid: { color: "#e9ece8" }, ticks: { color: "#69736b", precision: 0 } },
                        y1: { position: "right", grid: { drawOnChartArea: false }, ticks: { color: "#d55b3f" } },
                    },
                },
            });

            const districtCanvas = document.getElementById("district-chart");
            if (!districtCanvas) return;
            new Chart(districtCanvas, {
                type: "bar",
                data: { labels: data.districts.map((item) => item.name), datasets: [{ label: "거래 건수", data: data.districts.map((item) => item.count), backgroundColor: data.districts.map((_, index) => index === 0 ? "#d55b3f" : "#b7d6c5"), borderRadius: 3, barThickness: 13 }] },
                options: { indexAxis: "y", maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { beginAtZero: true, grid: { color: "#e9ece8" }, ticks: { precision: 0, color: "#69736b" } }, y: { grid: { display: false }, ticks: { color: "#525c54" } } } },
            });
        })
        .catch(() => { });
}