// Landing page: bot cards with sparklines, WebSocket live refresh.

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
  var m = bot.metrics.strategy;
  var excess = bot.metrics.excess_return_vs_spy;
  var liveBadge = bot.live
    ? '<span class="badge live">LIVE</span>'
    : '<span class="badge idle">seed</span>';
  return '\
  <a class="card" href="/bot/' + bot.id + '">\
    <div class="card-head">\
      <h3>' + bot.name + '</h3>\
      ' + liveBadge + '\
    </div>\
    <div class="tag">' + (bot.tagline || "") + '</div>\
    <div class="sparkline-wrap"><canvas class="sparkline" data-bot="' + bot.id + '"></canvas></div>\
    <div class="stats-row">\
      <div class="stat"><div class="label">Equity</div><div class="value">' + money(m.current_equity) + '</div></div>\
      <div class="stat"><div class="label">CAGR</div><div class="value ' + cls(m.cagr) + '">' + pct(m.cagr) + '</div></div>\
      <div class="stat"><div class="label">vs SPY</div><div class="value ' + cls(excess) + '">' + pct(excess) + '</div></div>\
    </div>\
    <div class="stats-row">\
      <div class="stat"><div class="label">Sharpe</div><div class="value">' + num(m.sharpe) + '</div></div>\
      <div class="stat"><div class="label">Sortino</div><div class="value">' + num(m.sortino) + '</div></div>\
      <div class="stat"><div class="label">Max DD</div><div class="value neg">' + pct(m.max_drawdown) + '</div></div>\
    </div>\
    <div class="regime">Regime: ' + (bot.regime || "—") + '</div>\
  </a>';
}

function drawSparkline(canvas, points) {
  if (!points || points.length < 2) return;
  var ctx = canvas.getContext("2d");
  var dpr = window.devicePixelRatio || 1;
  var w = canvas.parentElement.clientWidth;
  var h = 40;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  canvas.style.width = w + "px";
  canvas.style.height = h + "px";
  ctx.scale(dpr, dpr);

  var vals = points.map(function (p) { return p.value; });
  var min = Math.min.apply(null, vals);
  var max = Math.max.apply(null, vals);
  var range = max - min || 1;
  var pad = 2;

  var dark = document.documentElement.getAttribute("data-theme") === "dark";
  var up = vals[vals.length - 1] >= vals[0];
  ctx.strokeStyle = up ? (dark ? "#34c76a" : "#0a7d38") : (dark ? "#f05048" : "#d6332b");
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  for (var i = 0; i < vals.length; i++) {
    var x = (i / (vals.length - 1)) * (w - pad * 2) + pad;
    var y = h - pad - ((vals[i] - min) / range) * (h - pad * 2);
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  }
  ctx.stroke();
}

function loadSparklines(bots) {
  bots.forEach(function (bot) {
    fetch("/api/bots/" + bot.id + "/equity")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var canvas = document.querySelector('.sparkline[data-bot="' + bot.id + '"]');
        if (canvas && data.strategy) {
          var daily = {};
          data.strategy.forEach(function (p) {
            daily[p.ts.substring(0, 10)] = p;
          });
          var pts = Object.keys(daily).sort().map(function (d) { return daily[d]; });
          drawSparkline(canvas, pts);
        }
      })
      .catch(function () {});
  });
}

var _bots = [];

async function load() {
  try {
    var res = await fetch("/api/bots");
    var data = await res.json();
    var grid = document.getElementById("grid");
    if (!data.bots.length) {
      grid.innerHTML = '<div class="loading">No bots registered.</div>';
      return;
    }
    _bots = data.bots;
    grid.innerHTML = data.bots.map(card).join("");
    loadSparklines(data.bots);
  } catch (e) {
    document.getElementById("grid").innerHTML =
      '<div class="loading">Failed to load bots.</div>';
  }
}

function tick() {
  document.getElementById("clock").textContent =
    "Updated " + new Date().toLocaleTimeString();
}

// redraw sparklines on theme change
window.onThemeChange = function () {
  if (_bots.length) loadSparklines(_bots);
};

// WebSocket: refresh on tick
window.onWsMessage = function (msg) {
  if (msg.type === "tick") { load(); tick(); }
};

load();
tick();
// fallback polling in case WS is down
setInterval(function () { load(); tick(); }, 120000);
