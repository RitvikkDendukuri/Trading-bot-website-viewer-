# FastAPI app — JSON API + WebSocket push + static dashboard
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core import db, registry, scheduler, stats, ws

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


@asynccontextmanager
async def lifespan(application: FastAPI):
    db.init_db()
    ws.set_loop(asyncio.get_running_loop())
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="Trading Bots Platform", lifespan=lifespan)


def _bot_summary(bot_id: str) -> dict:
    meta = registry.get_metadata(bot_id)
    series = db.get_equity_series(bot_id)
    metrics = stats.summary(series["strategy"], series["spy"])
    has_live = db.last_live_ts(bot_id) is not None
    return {
        "id": bot_id,
        "name": meta["name"],
        "tagline": meta.get("tagline"),
        "github_url": meta.get("github_url"),
        "benchmark": meta.get("benchmark"),
        "regime": db.latest_regime(bot_id),
        "live": has_live,
        "metrics": metrics,
    }


@app.get("/api/bots")
def list_bots() -> dict:
    return {"bots": [_bot_summary(b["id"]) for b in registry.all_bots()]}


@app.get("/api/bots/{bot_id}")
def bot_detail(bot_id: str) -> dict:
    if bot_id not in registry.bot_ids():
        raise HTTPException(404, "Unknown bot")
    meta = registry.get_metadata(bot_id)
    summary = _bot_summary(bot_id)
    summary["methodology"] = meta.get("methodology")
    summary["positions"] = db.get_positions(bot_id)
    return summary


@app.get("/api/bots/{bot_id}/equity")
def bot_equity(bot_id: str) -> dict:
    if bot_id not in registry.bot_ids():
        raise HTTPException(404, "Unknown bot")
    series = db.get_equity_series(bot_id)
    last_live = db.last_live_ts(bot_id)
    return {
        "strategy": stats.hourly_except_latest(series["strategy"]),
        "spy": stats.hourly_except_latest(series["spy"]),
        "live_start_ts": last_live,
        "benchmark": registry.get_metadata(bot_id).get("benchmark"),
    }


@app.get("/api/bots/{bot_id}/drawdown")
def bot_drawdown(bot_id: str) -> dict:
    if bot_id not in registry.bot_ids():
        raise HTTPException(404, "Unknown bot")
    series = db.get_equity_series(bot_id)
    strat_dd = _compute_drawdown(series["strategy"])
    spy_dd = _compute_drawdown(series["spy"])
    return {"strategy": strat_dd, "spy": spy_dd}


def _compute_drawdown(points: list[dict]) -> list[dict]:
    if not points:
        return []
    peak = points[0]["value"]
    out = []
    for p in points:
        v = p["value"]
        if v > peak:
            peak = v
        dd = (v / peak - 1.0) if peak > 0 else 0.0
        out.append({"ts": p["ts"], "value": round(dd, 6)})
    return stats.hourly_except_latest(out)


@app.get("/api/bots/{bot_id}/trades")
def bot_trades(bot_id: str, limit: int = 60, offset: int = 0, month: str = "") -> dict:
    if bot_id not in registry.bot_ids():
        raise HTTPException(404, "Unknown bot")
    rows = db.get_trade_history(bot_id, 500, 0)
    if month:
        rows = [r for r in rows if r["date"][:7] == month]
    total = len(rows)
    rows = rows[offset:offset + limit]
    has_more = (offset + limit) < total
    return {"trades": rows, "has_more": has_more, "offset": offset, "total": total}


@app.get("/api/bots/{bot_id}/trades/months")
def bot_trade_months(bot_id: str) -> dict:
    if bot_id not in registry.bot_ids():
        raise HTTPException(404, "Unknown bot")
    return {"months": db.get_trade_months(bot_id)}


@app.get("/api/bots/{bot_id}/day/{date}")
def bot_day_detail(bot_id: str, date: str) -> dict:
    if bot_id not in registry.bot_ids():
        raise HTTPException(404, "Unknown bot")
    raw = db.get_daily_allocation(bot_id, date)
    if not raw:
        raise HTTPException(404, "No data for this date")
    data = json.loads(raw)
    sectors = data.get("sectors", [])
    cur_syms = {s["symbol"] for s in sectors}

    from datetime import datetime as _dt, timedelta as _td
    prev_sectors = {}
    for delta in range(1, 6):
        pd_str = (_dt.strptime(date, "%Y-%m-%d") - _td(days=delta)).strftime("%Y-%m-%d")
        prev_raw = db.get_daily_allocation(bot_id, pd_str)
        if prev_raw:
            prev_data = json.loads(prev_raw)
            prev_sectors = {s["symbol"]: s for s in prev_data.get("sectors", [])}
            break

    trades = []
    for s in sectors:
        cur_w = s.get("weight", 0.0)
        if cur_w < 0.001:
            continue
        prev_w = s.get("prev_weight", 0.0)
        if prev_w < 0.001 and s["symbol"] in prev_sectors:
            prev_w = prev_sectors[s["symbol"]].get("weight", 0.0)
        action = "hold"
        if prev_w < 0.001 and cur_w > 0.001:
            action = "buy"
        elif abs(cur_w - prev_w) > 0.005:
            action = "increase" if cur_w > prev_w else "decrease"
        trades.append({
            "symbol": s["symbol"],
            "action": action,
            "weight": s["weight"],
            "prev_weight": round(prev_w, 4),
            "day_return": s.get("day_return", 0),
            "contribution": s.get("contribution", 0),
        })
    for sym, ps in prev_sectors.items():
        if sym not in cur_syms and ps.get("weight", 0) > 0.001:
            trades.append({
                "symbol": sym,
                "action": "sell",
                "weight": 0.0,
                "prev_weight": round(ps.get("weight", 0), 4),
                "day_return": 0.0,
                "contribution": 0.0,
            })
    trades.sort(key=lambda t: abs(t["contribution"]), reverse=True)
    return {
        "date": data["date"],
        "regime": data.get("regime", ""),
        "leverage": data.get("leverage", 1.0),
        "portfolio_return": data.get("portfolio_return", 0),
        "equity": data.get("equity", 0),
        "trades": trades,
    }


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "bots": registry.bot_ids()}


# ---- WebSocket push ----
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await ws.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws.disconnect(websocket)


# ---- static dashboard ----
@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/bot/{bot_id}")
def bot_page(bot_id: str) -> FileResponse:
    return FileResponse(STATIC_DIR / "bot.html")


@app.get("/bot/{bot_id}/trades")
def trades_page(bot_id: str) -> FileResponse:
    return FileResponse(STATIC_DIR / "trades.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
