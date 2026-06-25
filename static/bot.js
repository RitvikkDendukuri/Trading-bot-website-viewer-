// Bot detail page: stats bar, equity chart (strategy vs SPY, live segment dashed),
// positions, methodology. Refreshes every 60s.

const botId = location.pathname.split("/").pop();
let chart = null;

function pct(x) { return (x === null || x === undefined) ? "—" : (x * 100).toFixed(2) + "%"; }
function money(x) { return (x === null || x === undefined) ? "—" : "$" + Number(x).toLocaleString(undefined, { maximumFractionDigits: 0 }); }
function num(x) { return (x === null || x === undefined) ? "—" : Number(x).toFixed(2); }
function cls(x) { return (x === null || x === undefined) ? "" : (x >= 0 ? "pos" : "neg"); }

function statItem(label, value, klass = "") {
  return `<div class="stat"><div class="label">${label}</div><div class="value ${klass}">${value}</div></div>`;
}

async function loadDetail() {
  const res = await fetch(`/api/bots/${botId}`);
  if (!res.ok) { document.getElementById("bot-name").textContent = "Bot not found"; return; }
  const bot = await res.json();
  const m = bot.metrics.strategy, spy = bot.metrics.spy, excess = bot.metrics.excess_return_vs_spy;

  document.getElementById("bot-name").textContent = bot.name;
  document.title = bot.name + " — Dashboard";
  document.getElementById("gh-link").href = bot.github_url || "#";
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
    statItem("Regime", `<span style="color:var(--accent)">${bot.regime || "—"}</span>`),
  ].join("");

  // positions table — each row shows today's move (color + arrow + % and $)
  function dayChange(p) {
    const cp = p.change_pct, ca = p.change_amt;
    if (cp === null || cp === undefined) return '<td class="muted">—</td>';
    const up = cp >= 0;
    const arrow = up ? "▲" : "▼";
    const cls = up ? "pos" : "neg";
    const amt = (ca >= 0 ? "+" : "−") + "$" + Math.abs(ca).toLocaleString(undefined, { maximumFractionDigits: 0 });
    return `<td class="chg ${cls}">${arrow} ${(cp * 100).toFixed(2)}% <span class="chg-amt">${amt}</span></td>`;
  }
  const tbody = bot.positions && bot.positions.length
    ? bot.positions.map(p => `<tr>
        <td>${p.symbol}</td>
        <td>${Number(p.qty).toLocaleString(undefined,{maximumFractionDigits:2})}</td>
        <td>${money(p.market_value)}</td>
        <td>${pct(p.weight)}</td>
        ${dayChange(p)}</tr>`).join("")
    : '<tr><td class="muted">No live positions yet.</td></tr>';
  document.getElementById("positions").innerHTML =
    `<thead><tr><th>Symbol</th><th>Qty</th><th>Market Value</th><th>Weight</th><th>Day Change</th></tr></thead><tbody>${tbody}</tbody>`;

  // ---- Risk & Benchmark metrics (under positions) ----
  const sp = bot.metrics.spy;
  // metric(label, info, value, spyValue, good) — good: true=green, false=red, null=neutral
  function metric(label, info, valueStr, spyStr, good) {
    const cls = good === true ? "pos" : good === false ? "neg" : "";
    const cmp = spyStr != null ? `<div class="cmp">SPY ${spyStr}</div>` : "";
    const ic = info ? `<span class="info" tabindex="0" data-tip="${info}">i</span>` : "";
    return `<div class="stat"><div class="label">${label} ${ic}</div><div class="value ${cls}">${valueStr}</div>${cmp}</div>`;
  }
  const better = (a, b) => (a == null || b == null) ? null : a >= b;
  document.getElementById("metricbar").innerHTML = [
    metric("Beta", "Sensitivity to SPY moves. 1 = moves with the market, &lt;1 = less, &gt;1 = more. Formula: cov(bot, SPY) ÷ var(SPY) on daily returns.",
      num(m.beta), null, null),
    metric("Alpha", "Annualized return beyond what SPY exposure (beta) explains. Formula: (bot − beta×SPY) daily mean × 252. Positive = adds value.",
      pct(m.alpha), null, m.alpha != null ? m.alpha >= 0 : null),
    metric("Calmar", "Return per unit of worst loss. Formula: CAGR ÷ |max drawdown|. Higher is better.",
      num(m.calmar), num(sp.calmar), better(m.calmar, sp.calmar)),
    metric("Sharpe", "Risk-adjusted return: annualized mean daily return ÷ annualized volatility.",
      num(m.sharpe), num(sp.sharpe), better(m.sharpe, sp.sharpe)),
    metric("Sortino", "Like Sharpe but only penalizes downside volatility.",
      num(m.sortino), num(sp.sortino), better(m.sortino, sp.sortino)),
    metric("Max Drawdown", "Largest peak-to-trough drop in equity. Smaller (closer to 0) is better.",
      pct(m.max_drawdown), pct(sp.max_drawdown), better(m.max_drawdown, sp.max_drawdown)),
    metric("Total Return", "Total % change in equity over the period.",
      pct(m.total_return), pct(sp.total_return), better(m.total_return, sp.total_return)),
    metric("vs SPY", "Bot total return minus SPY total return. Green = beating the benchmark.",
      pct(bot.metrics.excess_return_vs_spy), null, bot.metrics.excess_return_vs_spy != null ? bot.metrics.excess_return_vs_spy >= 0 : null),
  ].join("");
}

function buildSeries(points) {
  // one continuous line; remember where live begins so we can dash that segment
  const data = points.map((p) => ({ x: p.ts, y: p.value }));
  let liveStart = points.findIndex((p) => p.source === "live");
  if (liveStart < 0) liveStart = points.length;
  return { data, liveStart };
}

let chartData = { strategy: [], spy: [] };   // full series, filtered per range
let currentRange = "YTD";
let focusBot = false;   // when true, hide SPY so the y-axis zooms into the bot

function rangeCutoff(range, points) {
  if (!points.length) return null;
  const lastTs = points[points.length - 1].ts;
  const last = new Date(lastTs);
  const d = new Date(last);
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
  return points.filter((p) => new Date(p.ts) >= cutoff);
}

function renderChart() {
  const cutoff = rangeCutoff(currentRange, chartData.strategy);
  const strat = buildSeries(filterRange(chartData.strategy, cutoff));
  const spy = buildSeries(filterRange(chartData.spy, cutoff));

  const accent = "#ff4d00", spyc = "#16130f";
  // dash only the live portion (segments at/after liveStart)
  const dashLive = (s) => (ctx) =>
    ctx.p0DataIndex >= s.liveStart - 1 ? [4, 3] : undefined;
  const datasets = [
    { label: "Strategy", data: strat.data, borderColor: accent, backgroundColor: "transparent", borderWidth: 2.5, pointRadius: 0, tension: 0.1, segment: { borderDash: dashLive(strat) } },
    { label: "SPY", data: spy.data, borderColor: spyc, backgroundColor: "transparent", borderWidth: 1.5, pointRadius: 0, tension: 0.1, hidden: focusBot, segment: { borderDash: dashLive(spy) } },
  ];

  if (chart) {
    chart.data.datasets = datasets;
    if (chart.resetZoom) chart.resetZoom("none");
    chart.update("none");
    return;
  }

  chart = new Chart(document.getElementById("chart"), {
    type: "line",
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#16130f",
          borderColor: "#ff4d00",
          borderWidth: 2,
          cornerRadius: 0,
          padding: 10,
          titleFont: { family: "JetBrains Mono", weight: "700" },
          bodyFont: { family: "JetBrains Mono" },
          callbacks: {
            label: (c) => `${c.dataset.label}: $${Number(c.parsed.y).toLocaleString(undefined, { maximumFractionDigits: 0 })}`,
          },
        },
        zoom: {
          // zoom into a single day to see minute detail, zoom out for daily history
          zoom: { wheel: { enabled: true }, pinch: { enabled: true }, mode: "x" },
          pan: { enabled: true, mode: "x" },
        },
      },
      scales: {
        // no fixed unit: Chart.js auto-picks day/month when zoomed out, hours/minutes when zoomed in
        x: { type: "time", adapters: { date: { zone: "America/New_York" } }, grid: { color: "#ddd5c4" }, ticks: { color: "#5c554a", maxRotation: 0, autoSkip: true, font: { family: "JetBrains Mono" } } },
        y: { grid: { color: "#ddd5c4" }, ticks: { color: "#5c554a", font: { family: "JetBrains Mono" }, callback: (v) => "$" + (v / 1000) + "k" } },
      },
    },
  });
}

async function loadChart() {
  const res = await fetch(`/api/bots/${botId}/equity`);
  const data = await res.json();
  chartData = { strategy: data.strategy || [], spy: data.spy || [] };
  renderChart();
}

async function refresh() {
  try { await Promise.all([loadDetail(), loadChart()]); } catch (e) { /* keep last view */ }
}

// range selector
document.querySelectorAll("#ranges button").forEach((btn) => {
  btn.addEventListener("click", () => {
    currentRange = btn.dataset.range;
    document.querySelectorAll("#ranges button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    renderChart();
  });
});

// focus toggle: hide SPY so the y-axis auto-scales to just the bot's curve
document.getElementById("focus-toggle").addEventListener("click", (e) => {
  focusBot = !focusBot;
  e.currentTarget.classList.toggle("active", focusBot);
  e.currentTarget.textContent = focusBot ? "◉ Focus: Bot" : "◎ Focus: Bot";
  renderChart();
});

document.getElementById("reset-zoom").addEventListener("click", (e) => {
  e.preventDefault();
  if (chart) chart.resetZoom();
});

// ---- day detail panel: click on chart to see trades for that day ----
async function showDayDetail(dateStr) {
  const panel = document.getElementById("day-detail-panel");
  const content = document.getElementById("day-detail-content");
  const title = document.getElementById("day-detail-title");
  try {
    const res = await fetch(`/api/bots/${botId}/day/${dateStr}`);
    if (!res.ok) {
      panel.style.display = "none";
      return;
    }
    const d = await res.json();
    const up = d.portfolio_return >= 0;
    title.textContent = `Trade Detail — ${d.date}`;

    const summaryHTML = `<div class="day-summary">
      ${statItem("Equity", money(d.equity))}
      ${statItem("Day Return", pct(d.portfolio_return), cls(d.portfolio_return))}
      ${statItem("Leverage", num(d.leverage) + "×")}
      ${statItem("Regime", `<span style="color:var(--accent)">${d.regime || "—"}</span>`)}
    </div>`;

    const tradeRows = d.trades.map(t => {
      const retCls = t.day_return >= 0 ? "pos" : "neg";
      const contrCls = t.contribution >= 0 ? "pos" : "neg";
      const arrow = t.day_return >= 0 ? "▲" : "▼";
      const wBar = `<span class="weight-bar" style="width:${Math.round(t.weight * 200)}px"></span>`;
      const prevW = t.prev_weight > 0 ? `<span class="muted" style="font-size:11px">← ${(t.prev_weight*100).toFixed(1)}%</span>` : "";
      return `<tr>
        <td><span class="trade-action ${t.action}">${t.action}</span></td>
        <td style="font-weight:700">${t.symbol}</td>
        <td>${(t.weight*100).toFixed(1)}% ${wBar} ${prevW}</td>
        <td class="chg ${retCls}">${arrow} ${(t.day_return*100).toFixed(2)}%</td>
        <td class="chg ${contrCls}">${t.contribution >= 0 ? "+" : ""}${(t.contribution*100).toFixed(2)}%</td>
      </tr>`;
    }).join("");

    content.innerHTML = summaryHTML + `<table>
      <thead><tr><th>Action</th><th>Symbol</th><th>Weight</th><th>Day Return</th><th>Contribution</th></tr></thead>
      <tbody>${tradeRows || '<tr><td class="muted" colspan="5">No positions this day.</td></tr>'}</tbody>
    </table>`;
    panel.style.display = "";
    panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (e) {
    panel.style.display = "none";
  }
}

// Hook into chart click
function setupChartClick() {
  const canvas = document.getElementById("chart");
  canvas.addEventListener("click", (evt) => {
    if (!chart) return;
    const points = chart.getElementsAtEventForMode(evt, "index", { intersect: false }, false);
    if (!points.length) return;
    const idx = points[0].index;
    const ds = chart.data.datasets[0];
    if (!ds || !ds.data[idx]) return;
    const ts = ds.data[idx].x;
    const dateStr = ts.substring(0, 10);
    showDayDetail(dateStr);
  });
}

refresh();
setupChartClick();
setInterval(refresh, 60000);
