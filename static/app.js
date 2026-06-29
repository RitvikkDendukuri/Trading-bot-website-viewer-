// Landing page: bot cards with sparklines, animations, WebSocket live refresh.

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

// ---- toast notifications ----
function ensureToastContainer() {
  var c = document.getElementById("toast-container");
  if (!c) {
    c = document.createElement("div");
    c.id = "toast-container";
    c.className = "toast-container";
    document.body.appendChild(c);
  }
  return c;
}
function toast(message, icon) {
  var c = ensureToastContainer();
  var el = document.createElement("div");
  el.className = "toast";
  el.innerHTML = '<span class="toast-icon">' + (icon || "●") + '</span><span>' + message + '</span>';
  c.appendChild(el);
  setTimeout(function () {
    el.classList.add("out");
    setTimeout(function () { el.remove(); }, 320);
  }, 2600);
}
window.appToast = toast;

// ---- skeleton loading ----
function skeletonCard() {
  return '<div class="skeleton-card">' +
    '<div class="skeleton skeleton-line" style="width:60%;height:20px;margin:22px 22px 14px"></div>' +
    '<div class="skeleton skeleton-line" style="width:85%;margin:0 22px 18px"></div>' +
    '<div class="skeleton" style="height:40px;margin:0 22px 16px"></div>' +
    '<div style="display:flex;gap:10px;margin:0 22px">' +
      '<div class="skeleton skeleton-stat" style="flex:1"></div>' +
      '<div class="skeleton skeleton-stat" style="flex:1"></div>' +
      '<div class="skeleton skeleton-stat" style="flex:1"></div>' +
    '</div>' +
  '</div>';
}
function skeletonGrid(n) {
  var out = "";
  for (var i = 0; i < n; i++) out += skeletonCard();
  return out;
}

function card(bot) {
  var m = bot.metrics.strategy;
  var excess = bot.metrics.excess_return_vs_spy;
  var liveBadge = bot.live
    ? '<span class="badge live">LIVE</span>'
    : '<span class="badge idle">seed</span>';
  return '\
  <a class="card" href="/bot/' + bot.id + '" data-bot-id="' + bot.id + '">\
    <div class="card-head">\
      <h3>' + bot.name + '</h3>\
      ' + liveBadge + '\
    </div>\
    <div class="tag">' + (bot.tagline || "") + '</div>\
    <div class="sparkline-wrap"><canvas class="sparkline" data-bot="' + bot.id + '"></canvas></div>\
    <div class="stats-row">\
      <div class="stat" data-field="current_equity"><div class="label">Equity</div><div class="value">' + money(m.current_equity) + '</div></div>\
      <div class="stat" data-field="cagr"><div class="label">CAGR</div><div class="value ' + cls(m.cagr) + '">' + pct(m.cagr) + '</div></div>\
      <div class="stat" data-field="excess"><div class="label">vs SPY</div><div class="value ' + cls(excess) + '">' + pct(excess) + '</div></div>\
    </div>\
    <div class="stats-row">\
      <div class="stat" data-field="sharpe"><div class="label">Sharpe</div><div class="value">' + num(m.sharpe) + '</div></div>\
      <div class="stat" data-field="sortino"><div class="label">Sortino</div><div class="value">' + num(m.sortino) + '</div></div>\
      <div class="stat" data-field="max_drawdown"><div class="label">Max DD</div><div class="value neg">' + pct(m.max_drawdown) + '</div></div>\
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
  var strokeColor = up ? (dark ? "#34c76a" : "#0a7d38") : (dark ? "#f05048" : "#d6332b");

  function pointAt(i) {
    var x = (i / (vals.length - 1)) * (w - pad * 2) + pad;
    var y = h - pad - ((vals[i] - min) / range) * (h - pad * 2);
    return [x, y];
  }

  // animate the line drawing left-to-right
  var start = null;
  var duration = 600;
  function frame(ts) {
    if (!start) start = ts;
    var elapsed = ts - start;
    var progress = Math.min(1, elapsed / duration);
    var visibleCount = Math.max(2, Math.round(progress * vals.length));

    ctx.clearRect(0, 0, w, h);
    ctx.strokeStyle = strokeColor;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (var i = 0; i < visibleCount; i++) {
      var p = pointAt(i);
      i === 0 ? ctx.moveTo(p[0], p[1]) : ctx.lineTo(p[0], p[1]);
    }
    ctx.stroke();

    if (progress < 1) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
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
var _firstLoad = true;
var _prevValues = {};   // bot.id -> { field: rawValue }

function flashChangedValues(bots) {
  bots.forEach(function (bot) {
    var m = bot.metrics.strategy;
    var excess = bot.metrics.excess_return_vs_spy;
    var current = {
      current_equity: m.current_equity,
      cagr: m.cagr,
      excess: excess,
      sharpe: m.sharpe,
      sortino: m.sortino,
      max_drawdown: m.max_drawdown,
    };
    var prev = _prevValues[bot.id];
    if (prev) {
      Object.keys(current).forEach(function (field) {
        if (prev[field] !== undefined && prev[field] !== current[field]) {
          var sel = document.querySelector('.card[data-bot-id="' + bot.id + '"] .stat[data-field="' + field + '"] .value');
          if (sel) {
            sel.classList.remove("value-flash");
            void sel.offsetWidth; // restart animation
            sel.classList.add("value-flash");
          }
        }
      });
    }
    _prevValues[bot.id] = current;
  });
}

function showRefreshIndicator() {
  var el = document.getElementById("refresh-indicator");
  if (!el) return;
  el.classList.add("active");
  clearTimeout(el._hideTimer);
  el._hideTimer = setTimeout(function () { el.classList.remove("active"); }, 1200);
}

async function load() {
  var grid = document.getElementById("grid");
  try {
    if (_firstLoad) {
      grid.innerHTML = skeletonGrid(3);
    }
    var res = await fetch("/api/bots");
    var data = await res.json();
    if (!data.bots.length) {
      grid.innerHTML = '<div class="loading">No bots registered.</div>';
      return;
    }
    _bots = data.bots;

    if (!_firstLoad) {
      // flash existing cards instead of a full re-render jolt
      flashChangedValues(data.bots);
      showRefreshIndicator();
    }

    grid.innerHTML = data.bots.map(card).join("");
    loadSparklines(data.bots);
    if (_firstLoad) flashChangedValues(data.bots);
    _firstLoad = false;
  } catch (e) {
    grid.innerHTML = '<div class="loading">Failed to load bots.</div>';
  }
}

function tick() {
  var el = document.getElementById("clock");
  el.textContent = "Updated " + new Date().toLocaleTimeString();
  el.classList.add("tick-flash");
  setTimeout(function () { el.classList.remove("tick-flash"); }, 400);
}

// redraw sparklines on theme change
window.onThemeChange = function () {
  if (_bots.length) loadSparklines(_bots);
};

// WebSocket: refresh on tick, with a toast the first time live data connects
var _wsToastShown = false;
window.onWsMessage = function (msg) {
  if (msg.type === "tick") {
    load();
    tick();
    if (!_wsToastShown) {
      toast("Live data connected", "⚡");
      _wsToastShown = true;
    }
  }
};

load();
tick();
// fallback polling in case WS is down
setInterval(function () { load(); tick(); }, 120000);
