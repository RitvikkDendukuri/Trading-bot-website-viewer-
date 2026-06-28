// Bot detail page: stats, equity chart, drawdown chart, positions, methodology.
// Refreshes via WebSocket push, falls back to 120s polling.

var botId = location.pathname.split("/").pop();
var chart = null;
var ddChart = null;

function pct(x) { return (x === null || x === undefined) ? "—" : (x * 100).toFixed(2) + "%"; }
function money(x) { return (x === null || x === undefined) ? "—" : "$" + Number(x).toLocaleString(undefined, { maximumFractionDigits: 0 }); }
function num(x) { return (x === null || x === undefined) ? "—" : Number(x).toFixed(2); }
function cls(x) { return (x === null || x === undefined) ? "" : (x >= 0 ? "pos" : "neg"); }

function statItem(label, value, klass) {
  klass = klass || "";
  return '<div class="stat"><div class="label">' + label + '</div><div class="value ' + klass + '">' + value + '</div></div>';
}

function isDark() { return document.documentElement.getAttribute("data-theme") === "dark"; }
function gridColor() { return isDark() ? "#2e2a24" : "#ddd5c4"; }
function tickColor() { return isDark() ? "#9a9082" : "#5c554a"; }

async function loadDetail() {
  var res = await fetch("/api/bots/" + botId);
  if (!res.ok) { document.getElementById("bot-name").textContent = "Bot not found"; return; }
  var bot = await res.json();
  var m = bot.metrics.strategy, spy = bot.metrics.spy, excess = bot.metrics.excess_return_vs_spy;

  document.getElementById("bot-name").textContent = bot.name;
  document.title = bot.name + " — Dashboard";
  document.getElementById("gh-link").href = bot.github_url || "#";
  document.getElementById("trades-link").href = "/bot/" + botId + "/trades";
  document.getElementById("live-badge").innerHTML = bot.live
    ? '<span class="badge live">LIVE</span>'
    : '<span class="badge idle">seed</span>';
  document.getElementById("methodology").textContent = bot.methodology || "";

  document.getElementById("statbar").innerHTML = [
    statItem("Equity", money(m.current_equity)),
    statItem("Total Return", pct(m.total_return), cls(m.total_return)),
    statItem("vs SPY", pct(excess), cls(excess)),
    statItem("CAGR", pct(m.cagr), cls(m.cagr)),
    statItem("Sharpe", num(m.sharpe)),
    statItem("Sortino", num(m.sortino)),
    statItem("Max DD", pct(m.max_drawdown), "neg"),
    statItem("Regime", '<span style="color:var(--accent)">' + (bot.regime || "—") + '</span>'),
  ].join("");

  function dayChange(p) {
    var cp = p.change_pct, ca = p.change_amt;
    if (cp === null || cp === undefined) return '<td class="muted">—</td>';
    var up = cp >= 0;
    var arrow = up ? "▲" : "▼";
    var c = up ? "pos" : "neg";
    var amt = (ca >= 0 ? "+" : "−") + "$" + Math.abs(ca).toLocaleString(undefined, { maximumFractionDigits: 0 });
    return '<td class="chg ' + c + '">' + arrow + ' ' + (cp * 100).toFixed(2) + '% <span class="chg-amt">' + amt + '</span></td>';
  }
  var tbody = bot.positions && bot.positions.length
    ? bot.positions.map(function (p) {
        return '<tr><td>' + p.symbol + '</td><td>' + Number(p.qty).toLocaleString(undefined, {maximumFractionDigits:2}) + '</td><td>' + money(p.market_value) + '</td><td>' + pct(p.weight) + '</td>' + dayChange(p) + '</tr>';
      }).join("")
    : '<tr><td class="muted">No live positions yet.</td></tr>';
  document.getElementById("positions").innerHTML =
    '<thead><tr><th>Symbol</th><th>Qty</th><th>Market Value</th><th>Weight</th><th>Day Change</th></tr></thead><tbody>' + tbody + '</tbody>';

  var sp = bot.metrics.spy;
  function metric(label, info, valueStr, spyStr, good) {
    var c = good === true ? "pos" : good === false ? "neg" : "";
    var cmp = spyStr != null ? '<div class="cmp">SPY ' + spyStr + '</div>' : "";
    var ic = info ? '<span class="info" tabindex="0" data-tip="' + info + '">i</span>' : "";
    return '<div class="stat"><div class="label">' + label + ' ' + ic + '</div><div class="value ' + c + '">' + valueStr + '</div>' + cmp + '</div>';
  }
  var better = function (a, b) { return (a == null || b == null) ? null : a >= b; };
  document.getElementById("metricbar").innerHTML = [
    metric("Beta", "Sensitivity to SPY moves. 1 = moves with the market, &lt;1 = less, &gt;1 = more.",
      num(m.beta), null, null),
    metric("Alpha", "Annualized return beyond what SPY exposure (beta) explains. Positive = adds value.",
      pct(m.alpha), null, m.alpha != null ? m.alpha >= 0 : null),
    metric("Calmar", "Return per unit of worst loss. CAGR / |max drawdown|. Higher is better.",
      num(m.calmar), num(sp.calmar), better(m.calmar, sp.calmar)),
    metric("Sharpe", "Risk-adjusted return: annualized mean daily return / annualized volatility.",
      num(m.sharpe), num(sp.sharpe), better(m.sharpe, sp.sharpe)),
    metric("Sortino", "Like Sharpe but only penalizes downside volatility.",
      num(m.sortino), num(sp.sortino), better(m.sortino, sp.sortino)),
    metric("Max Drawdown", "Largest peak-to-trough drop in equity. Closer to 0 is better.",
      pct(m.max_drawdown), pct(sp.max_drawdown), better(m.max_drawdown, sp.max_drawdown)),
    metric("Total Return", "Total % change in equity over the period.",
      pct(m.total_return), pct(sp.total_return), better(m.total_return, sp.total_return)),
    metric("vs SPY", "Bot total return minus SPY total return. Green = beating the benchmark.",
      pct(bot.metrics.excess_return_vs_spy), null, bot.metrics.excess_return_vs_spy != null ? bot.metrics.excess_return_vs_spy >= 0 : null),
  ].join("");
}

// ---- equity chart ----

function buildSeries(points) {
  var data = points.map(function (p) { return { x: p.ts, y: p.value }; });
  var liveStart = points.findIndex(function (p) { return p.source === "live"; });
  if (liveStart < 0) liveStart = points.length;
  return { data: data, liveStart: liveStart };
}

var chartData = { strategy: [], spy: [] };
var currentRange = "YTD";
var focusBot = false;

function rangeCutoff(range, points) {
  if (!points.length) return null;
  var lastTs = points[points.length - 1].ts;
  var last = new Date(lastTs);
  var d = new Date(last);
  switch (range) {
    case "1D": d.setDate(d.getDate() - 1); break;
    case "1W": d.setDate(d.getDate() - 7); break;
    case "1M": d.setMonth(d.getMonth() - 1); break;
    case "6M": d.setMonth(d.getMonth() - 6); break;
    case "1Y": d.setFullYear(d.getFullYear() - 1); break;
    case "YTD": return new Date(last.getFullYear(), 0, 1);
    default: return null;
  }
  return d;
}

function filterRange(points, cutoff) {
  if (!cutoff) return points;
  return points.filter(function (p) { return new Date(p.ts) >= cutoff; });
}

function chartColors() {
  var dark = isDark();
  return {
    accent: dark ? "#ff6a2f" : "#ff4d00",
    spyc: dark ? "#e8e2d6" : "#16130f",
    tooltipBg: dark ? "#2e2a24" : "#16130f",
    tooltipText: dark ? "#e8e2d6" : "#fffdf7",
    tooltipBorder: dark ? "#ff6a2f" : "#ff4d00",
  };
}

function renderChart() {
  var cutoff = rangeCutoff(currentRange, chartData.strategy);
  var strat = buildSeries(filterRange(chartData.strategy, cutoff));
  var spy = buildSeries(filterRange(chartData.spy, cutoff));
  var c = chartColors();

  var dashLive = function (s) { return function (ctx) {
    return ctx.p0DataIndex >= s.liveStart - 1 ? [4, 3] : undefined;
  }; };
  var datasets = [
    { label: "Strategy", data: strat.data, borderColor: c.accent, backgroundColor: "transparent", borderWidth: 2.5, pointRadius: 0, tension: 0.1, segment: { borderDash: dashLive(strat) } },
    { label: "SPY", data: spy.data, borderColor: c.spyc, backgroundColor: "transparent", borderWidth: 1.5, pointRadius: 0, tension: 0.1, hidden: focusBot, segment: { borderDash: dashLive(spy) } },
  ];

  if (chart) {
    chart.data.datasets = datasets;
    chart.options.scales.x.grid.color = gridColor();
    chart.options.scales.y.grid.color = gridColor();
    chart.options.scales.x.ticks.color = tickColor();
    chart.options.scales.y.ticks.color = tickColor();
    if (chart.resetZoom) chart.resetZoom("none");
    chart.update("none");
    return;
  }

  chart = new Chart(document.getElementById("chart"), {
    type: "line",
    data: { datasets: datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: c.tooltipBg, titleColor: c.tooltipText, bodyColor: c.tooltipText,
          borderColor: c.tooltipBorder,
          borderWidth: 2, cornerRadius: 0, padding: 10,
          titleFont: { family: "JetBrains Mono", weight: "700" },
          bodyFont: { family: "JetBrains Mono" },
          callbacks: {
            label: function (ctx) { return ctx.dataset.label + ": $" + Number(ctx.parsed.y).toLocaleString(undefined, { maximumFractionDigits: 0 }); },
          },
        },
        zoom: {
          zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: "x" },
          pan: { enabled: true, mode: "x" },
        },
      },
      scales: {
        x: { type: "time", adapters: { date: { zone: "America/New_York" } }, grid: { color: gridColor() }, ticks: { color: tickColor(), maxRotation: 0, autoSkip: true, font: { family: "JetBrains Mono" } } },
        y: { grid: { color: gridColor() }, ticks: { color: tickColor(), font: { family: "JetBrains Mono" }, callback: function (v) { return "$" + (v / 1000) + "k"; } } },
      },
    },
  });
}

// ---- drawdown chart ----

var ddData = { strategy: [], spy: [] };

function renderDDChart() {
  if (!ddData.strategy.length && !ddData.spy.length) return;
  var canvas = document.getElementById("dd-chart");
  if (!canvas) return;
  var cutoff = rangeCutoff(currentRange, chartData.strategy.length ? chartData.strategy : ddData.strategy);
  var stratPts = filterRange(ddData.strategy, cutoff).map(function (p) { return { x: p.ts, y: p.value * 100 }; });
  var spyPts = filterRange(ddData.spy, cutoff).map(function (p) { return { x: p.ts, y: p.value * 100 }; });
  var c = chartColors();

  var datasets = [
    { label: "Strategy DD", data: stratPts, borderColor: c.accent, backgroundColor: c.accent + "1a", fill: true, borderWidth: 1.5, pointRadius: 0, tension: 0.1 },
    { label: "SPY DD", data: spyPts, borderColor: c.spyc, backgroundColor: "transparent", fill: false, borderWidth: 1, pointRadius: 0, tension: 0.1, hidden: focusBot },
  ];

  if (ddChart) {
    ddChart.data.datasets = datasets;
    ddChart.options.scales.x.grid.color = gridColor();
    ddChart.options.scales.y.grid.color = gridColor();
    ddChart.options.scales.x.ticks.color = tickColor();
    ddChart.options.scales.y.ticks.color = tickColor();
    ddChart.update("none");
    return;
  }

  ddChart = new Chart(document.getElementById("dd-chart"), {
    type: "line",
    data: { datasets: datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: c.tooltipBg, titleColor: c.tooltipText, bodyColor: c.tooltipText,
          borderColor: c.tooltipBorder,
          borderWidth: 2, cornerRadius: 0, padding: 10,
          titleFont: { family: "JetBrains Mono", weight: "700" },
          bodyFont: { family: "JetBrains Mono" },
          callbacks: {
            label: function (ctx) { return ctx.dataset.label + ": " + ctx.parsed.y.toFixed(2) + "%"; },
          },
        },
      },
      scales: {
        x: { type: "time", adapters: { date: { zone: "America/New_York" } }, grid: { color: gridColor() }, ticks: { color: tickColor(), maxRotation: 0, autoSkip: true, font: { family: "JetBrains Mono" } } },
        y: { grid: { color: gridColor() }, ticks: { color: tickColor(), font: { family: "JetBrains Mono" }, callback: function (v) { return v.toFixed(0) + "%"; } } },
      },
    },
  });
}

// ---- data loading ----

async function loadChart() {
  var res = await fetch("/api/bots/" + botId + "/equity");
  var data = await res.json();
  var sortByTs = function (arr) { return arr.slice().sort(function (a, b) { return a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0; }); };
  chartData = { strategy: sortByTs(data.strategy || []), spy: sortByTs(data.spy || []) };
  renderChart();
}

async function loadDrawdown() {
  try {
    var res = await fetch("/api/bots/" + botId + "/drawdown");
    var data = await res.json();
    var sortByTs = function (arr) { return arr.slice().sort(function (a, b) { return a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0; }); };
    ddData = { strategy: sortByTs(data.strategy || []), spy: sortByTs(data.spy || []) };
    renderDDChart();
  } catch (e) { /* drawdown chart is optional */ }
}

async function refresh() {
  try {
    await Promise.all([loadDetail(), loadChart()]);
    await loadDrawdown();
  } catch (e) { /* keep last view */ }
}

// ---- range selector ----
document.querySelectorAll("#ranges button").forEach(function (btn) {
  btn.addEventListener("click", function () {
    currentRange = btn.dataset.range;
    document.querySelectorAll("#ranges button").forEach(function (b) { b.classList.remove("active"); });
    btn.classList.add("active");
    renderChart();
    renderDDChart();
  });
});

// ---- focus toggle ----
document.getElementById("focus-toggle").addEventListener("click", function (e) {
  focusBot = !focusBot;
  e.currentTarget.classList.toggle("active", focusBot);
  e.currentTarget.textContent = focusBot ? "◉ Focus: Bot" : "◎ Focus: Bot";
  renderChart();
  renderDDChart();
});

document.getElementById("reset-zoom").addEventListener("click", function (e) {
  e.preventDefault();
  if (chart) chart.resetZoom();
});

// ---- theme change: update chart colors ----
window.onThemeChange = function () {
  if (chart) {
    chart.destroy();
    chart = null;
    renderChart();
  }
  if (ddChart) {
    ddChart.destroy();
    ddChart = null;
    renderDDChart();
  }
};

// ---- day detail panel ----
async function showDayDetail(dateStr) {
  var panel = document.getElementById("day-detail-panel");
  var content = document.getElementById("day-detail-content");
  var title = document.getElementById("day-detail-title");
  try {
    var res = await fetch("/api/bots/" + botId + "/day/" + dateStr);
    if (!res.ok) { panel.style.display = "none"; return; }
    var d = await res.json();
    title.textContent = "Trade Detail — " + d.date;

    var summaryHTML = '<div class="day-summary">' +
      statItem("Equity", money(d.equity)) +
      statItem("Day Return", pct(d.portfolio_return), cls(d.portfolio_return)) +
      statItem("Leverage", num(d.leverage) + "×") +
      statItem("Regime", '<span style="color:var(--accent)">' + (d.regime || "—") + '</span>') +
    '</div>';

    var tradeRows = d.trades.map(function (t) {
      var retCls = t.day_return >= 0 ? "pos" : "neg";
      var contrCls = t.contribution >= 0 ? "pos" : "neg";
      var arrow = t.day_return >= 0 ? "▲" : "▼";
      var wBar = '<span class="weight-bar" style="width:' + Math.round(t.weight * 200) + 'px"></span>';
      var prevW = t.prev_weight > 0 ? '<span class="muted" style="font-size:11px">← ' + (t.prev_weight*100).toFixed(1) + '%</span>' : "";
      return '<tr>' +
        '<td><span class="trade-action ' + t.action + '">' + t.action + '</span></td>' +
        '<td style="font-weight:700">' + t.symbol + '</td>' +
        '<td>' + (t.weight*100).toFixed(1) + '% ' + wBar + ' ' + prevW + '</td>' +
        '<td class="chg ' + retCls + '">' + arrow + ' ' + (t.day_return*100).toFixed(2) + '%</td>' +
        '<td class="chg ' + contrCls + '">' + (t.contribution >= 0 ? "+" : "") + (t.contribution*100).toFixed(2) + '%</td>' +
      '</tr>';
    }).join("");

    content.innerHTML = summaryHTML + '<table>' +
      '<thead><tr><th>Action</th><th>Symbol</th><th>Weight</th><th>Day Return</th><th>Contribution</th></tr></thead>' +
      '<tbody>' + (tradeRows || '<tr><td class="muted" colspan="5">No positions this day.</td></tr>') + '</tbody>' +
    '</table>';
    panel.style.display = "";
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (e) { panel.style.display = "none"; }
}

function setupChartClick() {
  document.getElementById("chart").addEventListener("click", function (evt) {
    if (!chart) return;
    var points = chart.getElementsAtEventForMode(evt, "index", { intersect: false }, false);
    if (!points.length) return;
    var idx = points[0].index;
    var ds = chart.data.datasets[0];
    if (!ds || !ds.data[idx]) return;
    var ts = ds.data[idx].x;
    showDayDetail(ts.substring(0, 10));
  });
}

// ---- WebSocket: refresh on server tick ----
window.onWsMessage = function (msg) {
  if (msg.type === "tick") refresh();
};

refresh();
setupChartClick();
// fallback polling
setInterval(refresh, 120000);
