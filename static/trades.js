// Trade history / log page with month dropdown navigation
(function () {
  var parts = location.pathname.split("/");
  var botId = parts[2];
  var PAGE_SIZE = 30;
  var offset = 0;
  var currentMonth = "";

  document.getElementById("back-link").href = "/bot/" + botId;

  function pct(x) { return (x === null || x === undefined) ? "—" : (x * 100).toFixed(2) + "%"; }
  function money(x) { return (x === null || x === undefined) ? "—" : "$" + Number(x).toLocaleString(undefined, { maximumFractionDigits: 0 }); }
  function cls(x) { return (x === null || x === undefined) ? "" : (x >= 0 ? "pos" : "neg"); }

  function monthLabel(m) {
    var p = m.split("-");
    var names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    return names[parseInt(p[1], 10) - 1] + " " + p[0];
  }

  fetch("/api/bots/" + botId)
    .then(function (r) { return r.json(); })
    .then(function (bot) {
      document.getElementById("page-title").textContent = bot.name + " — Trade Log";
      document.title = bot.name + " — Trade Log";
    })
    .catch(function () {});

  fetch("/api/bots/" + botId + "/trades/months")
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var sel = document.getElementById("month-select");
      if (!data.months || !data.months.length) return;
      data.months.forEach(function (m) {
        var opt = document.createElement("option");
        opt.value = m;
        opt.textContent = monthLabel(m);
        sel.appendChild(opt);
      });
      sel.addEventListener("change", function () {
        currentMonth = sel.value;
        offset = 0;
        load();
      });
    })
    .catch(function () {});

  function renderDay(day) {
    var retCls = cls(day.portfolio_return);
    var retArrow = day.portfolio_return >= 0 ? "▲" : "▼";

    var header = '<div class="day-summary" style="margin-bottom:8px">' +
      '<div class="stat"><div class="label">Date</div><div class="value" style="font-size:15px">' + day.date + '</div></div>' +
      '<div class="stat"><div class="label">Equity</div><div class="value">' + money(day.equity) + '</div></div>' +
      '<div class="stat"><div class="label">Day Return</div><div class="value ' + retCls + '">' + retArrow + ' ' + pct(day.portfolio_return) + '</div></div>' +
      '<div class="stat"><div class="label">Regime</div><div class="value"><span style="color:var(--accent)">' + (day.regime || "—") + '</span></div></div>' +
      '<div class="stat"><div class="label">Leverage</div><div class="value">' + (day.leverage || 1).toFixed(2) + '×</div></div>' +
    '</div>';

    if (!day.sectors || !day.sectors.length) {
      return header + '<p class="muted" style="margin:0 0 20px;font-size:13px">No sector data.</p>';
    }

    var rows = day.sectors
      .filter(function (s) { return s.weight > 0.001; })
      .sort(function (a, b) { return Math.abs(b.contribution || 0) - Math.abs(a.contribution || 0); })
      .map(function (s) {
        var sCls = (s.day_return || 0) >= 0 ? "pos" : "neg";
        var cCls = (s.contribution || 0) >= 0 ? "pos" : "neg";
        var arrow = (s.day_return || 0) >= 0 ? "▲" : "▼";
        var wBar = '<span class="weight-bar" style="width:' + Math.round(s.weight * 150) + 'px"></span>';
        return '<tr>' +
          '<td style="font-weight:700">' + s.symbol + '</td>' +
          '<td>' + (s.weight * 100).toFixed(1) + '% ' + wBar + '</td>' +
          '<td class="chg ' + sCls + '">' + arrow + ' ' + ((s.day_return || 0) * 100).toFixed(2) + '%</td>' +
          '<td class="chg ' + cCls + '">' + ((s.contribution || 0) >= 0 ? "+" : "") + ((s.contribution || 0) * 100).toFixed(2) + '%</td>' +
        '</tr>';
      }).join("");

    return header + '<table style="margin-bottom:24px">' +
      '<thead><tr><th>Symbol</th><th>Weight</th><th>Day Return</th><th>Contribution</th></tr></thead>' +
      '<tbody>' + rows + '</tbody></table>';
  }

  function load() {
    var container = document.getElementById("trades-list");
    container.innerHTML = '<div class="loading">Loading...</div>';

    var url = "/api/bots/" + botId + "/trades?limit=" + PAGE_SIZE + "&offset=" + offset;
    if (currentMonth) url += "&month=" + currentMonth;

    fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.trades.length) {
          container.innerHTML = '<div class="loading">No trade history' + (currentMonth ? ' for ' + monthLabel(currentMonth) : '') + '.</div>';
          document.getElementById("pagination").innerHTML = "";
          return;
        }
        container.innerHTML = data.trades.map(renderDay).join('<hr style="border:none;border-top:3px solid var(--ink);margin:20px 0">');

        var pag = document.getElementById("pagination");
        var prevDisabled = offset === 0 ? " disabled" : "";
        var nextDisabled = !data.has_more ? " disabled" : "";
        var page = Math.floor(offset / PAGE_SIZE) + 1;
        var totalPages = Math.ceil((data.total || data.trades.length) / PAGE_SIZE);
        pag.innerHTML =
          '<button id="prev-btn"' + prevDisabled + '>&#8592; Newer</button>' +
          '<span>Page ' + page + (totalPages > 1 ? ' / ' + totalPages : '') + '</span>' +
          '<button id="next-btn"' + nextDisabled + '>Older &#8594;</button>';

        document.getElementById("prev-btn").addEventListener("click", function () {
          offset = Math.max(0, offset - PAGE_SIZE);
          load();
          window.scrollTo({ top: 0, behavior: "smooth" });
        });
        document.getElementById("next-btn").addEventListener("click", function () {
          offset += PAGE_SIZE;
          load();
          window.scrollTo({ top: 0, behavior: "smooth" });
        });
      })
      .catch(function () {
        container.innerHTML = '<div class="loading">Failed to load trades.</div>';
      });
  }

  load();
})();
