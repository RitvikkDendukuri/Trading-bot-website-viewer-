// Landing page: render a card per bot, refresh every 60s.

function pct(x) {
  if (x === null || x === undefined) return "—";
  return (x * 100).toFixed(2) + "%";
}
function money(x) {
  if (x === null || x === undefined) return "—";
  return "$" + Number(x).toLocaleString(undefined, { maximumFractionDigits: 0 });
}
function num(x) {
  if (x === null || x === undefined) return "—";
  return Number(x).toFixed(2);
}
function cls(x) {
  if (x === null || x === undefined) return "";
  return x >= 0 ? "pos" : "neg";
}

function card(bot) {
  const m = bot.metrics.strategy;
  const excess = bot.metrics.excess_return_vs_spy;
  const liveBadge = bot.live
    ? '<span class="badge live">LIVE</span>'
    : '<span class="badge idle">seed</span>';
  return `
  <a class="card" href="/bot/${bot.id}">
    <div class="card-head">
      <h3>${bot.name}</h3>
      ${liveBadge}
    </div>
    <div class="tag">${bot.tagline || ""}</div>
    <div class="stats-row">
      <div class="stat"><div class="label">Equity</div><div class="value">${money(m.current_equity)}</div></div>
      <div class="stat"><div class="label">Total Return</div><div class="value ${cls(m.total_return)}">${pct(m.total_return)}</div></div>
      <div class="stat"><div class="label">vs SPY</div><div class="value ${cls(excess)}">${pct(excess)}</div></div>
    </div>
    <div class="stats-row">
      <div class="stat"><div class="label">Sharpe</div><div class="value">${num(m.sharpe)}</div></div>
      <div class="stat"><div class="label">Sortino</div><div class="value">${num(m.sortino)}</div></div>
      <div class="stat"><div class="label">Max DD</div><div class="value neg">${pct(m.max_drawdown)}</div></div>
    </div>
    <div class="regime">Regime: ${bot.regime || "—"}</div>
  </a>`;
}

async function load() {
  try {
    const res = await fetch("/api/bots");
    const data = await res.json();
    const grid = document.getElementById("grid");
    if (!data.bots.length) {
      grid.innerHTML = '<div class="loading">No bots registered.</div>';
      return;
    }
    grid.innerHTML = data.bots.map(card).join("");
  } catch (e) {
    document.getElementById("grid").innerHTML =
      '<div class="loading">Failed to load bots.</div>';
  }
}

function tick() {
  document.getElementById("clock").textContent =
    "Updated " + new Date().toLocaleTimeString();
}

load();
tick();
setInterval(() => { load(); tick(); }, 60000);
