// Trend chart (spec §3.2): one light line per person, plotted on a 3-point
// status scale. Reads its data from the json_script block in the template.
(function () {
  const el = document.getElementById("trend");
  const dataEl = document.getElementById("trend-data");
  if (!el || !dataEl || typeof Chart === "undefined") return;

  const series = JSON.parse(dataEl.textContent);
  const palette = ["#2563eb", "#7c3aed", "#0891b2", "#c2410c", "#4d7c0f", "#be185d"];
  const STATUS_LABELS = { 1: "🔴 Blocked", 2: "🟡 At risk", 3: "🟢 On track" };

  new Chart(el, {
    type: "line",
    data: {
      datasets: series.map((s, i) => ({
        label: s.label,
        data: s.points,
        borderColor: palette[i % palette.length],
        backgroundColor: palette[i % palette.length],
        borderWidth: 2,
        pointRadius: 3,
        tension: 0.2,
        // Statuses are discrete, so hold the last value until the next
        // report rather than implying a smooth slide between them.
        stepped: "before",
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "nearest", intersect: false },
      scales: {
        x: {
          type: "linear",
          ticks: {
            maxTicksLimit: 6,
            callback: (v) => new Date(v).toLocaleDateString(),
          },
          grid: { display: false },
        },
        y: {
          min: 0.5,
          max: 3.5,
          ticks: {
            stepSize: 1,
            callback: (v) => STATUS_LABELS[v] || "",
          },
        },
      },
      plugins: {
        legend: { position: "bottom", labels: { boxWidth: 12 } },
        tooltip: {
          callbacks: {
            title: (items) => new Date(items[0].parsed.x).toLocaleString(),
            label: (item) => `${item.dataset.label}: ${STATUS_LABELS[item.parsed.y]}`,
          },
        },
      },
    },
  });
})();
