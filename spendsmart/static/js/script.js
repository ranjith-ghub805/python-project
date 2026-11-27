(() => {
  "use strict";

  const menuToggle = document.getElementById("menuToggle");
  const sidebar = document.getElementById("sidebar");
  if (menuToggle && sidebar) {
    menuToggle.addEventListener("click", () => sidebar.classList.toggle("open"));
    document.addEventListener("click", (event) => {
      if (window.innerWidth <= 780 && sidebar.classList.contains("open")
          && !sidebar.contains(event.target) && !menuToggle.contains(event.target)) {
        sidebar.classList.remove("open");
      }
    });
  }

  document.querySelectorAll(".flash-close").forEach((button) => {
    button.addEventListener("click", () => button.parentElement.remove());
  });
  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  const categorySelect = document.getElementById("categorySelect");
  const typeRadios = document.querySelectorAll('input[name="kind"]');
  const syncCategories = () => {
    if (!categorySelect) return;
    const kind = document.querySelector('input[name="kind"]:checked')?.value || "expense";
    const options = [...categorySelect.options];
    options.forEach((option) => {
      option.hidden = option.dataset.kind !== kind;
    });
    if (categorySelect.selectedOptions[0]?.dataset.kind !== kind) {
      const firstOption = options.find((option) => option.dataset.kind === kind);
      if (firstOption) categorySelect.value = firstOption.value;
    }
  };
  typeRadios.forEach((radio) => radio.addEventListener("change", syncCategories));
  syncCategories();

  const countUpElements = document.querySelectorAll(".count-up[data-count]");
  const formatMoney = (amount) => {
    const absolute = Math.abs(amount).toLocaleString("en-IN", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    return `${amount < 0 ? "−" : ""}₹${absolute}`;
  };
  countUpElements.forEach((element, index) => {
    const target = Number(element.dataset.count);
    if (!Number.isFinite(target)) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      element.textContent = formatMoney(target);
      return;
    }
    const duration = 950;
    const start = performance.now() + index * 75;
    const animate = (now) => {
      const progress = Math.min(1, Math.max(0, (now - start) / duration));
      const eased = 1 - (1 - progress) ** 4;
      element.textContent = formatMoney(target * eased);
      if (progress < 1) requestAnimationFrame(animate);
    };
    requestAnimationFrame(animate);
  });

  if (typeof Chart === "undefined") return;
  Chart.defaults.color = "#858ba5";
  Chart.defaults.font.family = '"DM Sans", sans-serif';
  Chart.defaults.font.size = 10;

  const palette = ["#a58aff", "#5bc4ba", "#f4b96c", "#ed7f9d", "#6ea7ef", "#a4db8b", "#d18cf0"];
  const currencyTick = (value) => `₹${Number(value).toLocaleString("en-IN")}`;

  const overviewCanvas = document.getElementById("overviewChart");
  if (overviewCanvas && window.spendSmartCharts) {
    const chart = window.spendSmartCharts;
    new Chart(overviewCanvas, {
      type: "bar",
      data: {
        labels: chart.months.map((month) => new Date(`${month}-01T00:00:00`).toLocaleDateString("en", { month: "short" })),
        datasets: [
          { label: "Income", data: chart.income, backgroundColor: "#69d8ad", borderRadius: 4, maxBarThickness: 18 },
          { label: "Expenses", data: chart.expenses, backgroundColor: "#9b80f0", borderRadius: 4, maxBarThickness: 18 },
        ],
      },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 6, padding: 18 } } },
        scales: {
          x: { grid: { display: false }, border: { display: false } },
          y: { beginAtZero: true, grid: { color: "#ffffff0b" }, border: { display: false }, ticks: { callback: currencyTick } },
        },
      },
    });
  }

  const categoryCanvas = document.getElementById("categoryChart");
  if (categoryCanvas && window.spendSmartCharts?.categoryLabels.length) {
    new Chart(categoryCanvas, {
      type: "doughnut",
      data: { labels: window.spendSmartCharts.categoryLabels, datasets: [{ data: window.spendSmartCharts.categoryValues, backgroundColor: palette, borderColor: "#171a2c", borderWidth: 4, hoverOffset: 5 }] },
      options: { maintainAspectRatio: false, cutout: "76%", plugins: { legend: { display: false }, tooltip: { callbacks: { label: (context) => `${context.label}: ${currencyTick(context.raw)}` } } } },
    });
  }

  const reportBar = document.getElementById("reportBarChart");
  if (reportBar && window.spendSmartReport) {
    const report = window.spendSmartReport;
    new Chart(reportBar, {
      type: "bar",
      data: {
        labels: report.labels,
        datasets: [
          { label: "Income", data: report.income, backgroundColor: "#69d8ad", borderRadius: 4, maxBarThickness: 25 },
          { label: "Expenses", data: report.expenses, backgroundColor: "#9b80f0", borderRadius: 4, maxBarThickness: 25 },
        ],
      },
      options: {
        maintainAspectRatio: false,
        plugins: { legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 6, padding: 18 } } },
        scales: {
          x: { grid: { display: false }, border: { display: false } },
          y: { beginAtZero: true, grid: { color: "#ffffff0b" }, border: { display: false }, ticks: { callback: currencyTick } },
        },
      },
    });
  }
  const reportPie = document.getElementById("reportPieChart");
  if (reportPie && window.spendSmartReport) {
    const report = window.spendSmartReport;
    new Chart(reportPie, {
      type: "doughnut",
      data: { labels: report.categories, datasets: [{ data: report.categoryValues, backgroundColor: palette, borderColor: "#171a2c", borderWidth: 4, hoverOffset: 5 }] },
      options: { maintainAspectRatio: false, cutout: "68%", plugins: { legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 6, padding: 12 } }, tooltip: { callbacks: { label: (context) => `${context.label}: ${currencyTick(context.raw)}` } } } },
    });
  }
})();
