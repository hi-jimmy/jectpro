const configNode = document.getElementById("open-data-chart-config");

if (configNode && window.Chart) {
    fetch(configNode.dataset.url)
        .then((response) => response.json())
        .then((data) => {
            const timelineCanvas = document.getElementById("open-data-timeline");
            const leaderCanvas = document.getElementById("open-data-leaders");
            const muted = "#69736b";
            const grid = "#e9ece8";

            if (timelineCanvas) {
                new Chart(timelineCanvas, {
                    type: "bar",
                    data: {
                        labels: data.timeline.map((row) => row.period || "미분류"),
                        datasets: [{
                            label: configNode.dataset.label,
                            data: data.timeline.map((row) => row.total || row.count),
                            backgroundColor: "#b7d6c5",
                            borderRadius: 3,
                        }],
                    },
                    options: {
                        maintainAspectRatio: false,
                        plugins: { legend: { display: false } },
                        scales: {
                            x: { grid: { display: false }, ticks: { color: muted, maxRotation: 0, autoSkip: true, maxTicksLimit: 9 } },
                            y: { beginAtZero: true, grid: { color: grid }, ticks: { color: muted } },
                        },
                    },
                });
            }

            if (leaderCanvas) {
                new Chart(leaderCanvas, {
                    type: "bar",
                    data: {
                        labels: data.leaders.map((row) => row.name),
                        datasets: [{ label: configNode.dataset.label, data: data.leaders.map((row) => row.metric || row.count), backgroundColor: "#d55b3f", borderRadius: 3, barThickness: 13 }],
                    },
                    options: {
                        indexAxis: "y",
                        maintainAspectRatio: false,
                        plugins: { legend: { display: false } },
                        scales: {
                            x: { beginAtZero: true, grid: { color: grid }, ticks: { color: muted } },
                            y: { grid: { display: false }, ticks: { color: muted } },
                        },
                    },
                });
            }
        })
        .catch(() => { });
}