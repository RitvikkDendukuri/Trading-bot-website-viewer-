// WebSocket client — auto-reconnects, calls window.onWsMessage on each push
(function () {
  var dot = document.getElementById("ws-dot");
  var ws, retryMs = 1000;

  function url() {
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    return proto + "//" + location.host + "/ws";
  }

  function connect() {
    try { ws = new WebSocket(url()); } catch (e) { schedule(); return; }

    ws.onopen = function () {
      retryMs = 1000;
      if (dot) { dot.classList.add("connected"); dot.title = "Live"; }
    };

    ws.onmessage = function (evt) {
      try {
        var msg = JSON.parse(evt.data);
        if (typeof window.onWsMessage === "function") window.onWsMessage(msg);
      } catch (e) { /* ignore bad frames */ }
    };

    ws.onclose = function () {
      if (dot) { dot.classList.remove("connected"); dot.title = "Reconnecting..."; }
      schedule();
    };

    ws.onerror = function () { ws.close(); };
  }

  function schedule() {
    setTimeout(connect, retryMs);
    retryMs = Math.min(retryMs * 1.5, 15000);
  }

  connect();
})();
