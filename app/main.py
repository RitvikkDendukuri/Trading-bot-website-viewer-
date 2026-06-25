# FastAPI app — JSON API + static dashboard
from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core import db, registry, scheduler, stats

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"

app = FastAPI(title="Trading Bots Platform")


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    scheduler.start()


@app.on_event("shutdown")
def _shutdown() -> None:
    scheduler.stop()


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
    # minute resolution for today, hourly for older dates
    return {
        "strategy": stats.hourly_except_latest(series["strategy"]),
        "spy": stats.hourly_except_latest(series["spy"]),
        "live_start_ts": last_live,
        "benchmark": registry.get_metadata(bot_id).get("benchmark"),
    }


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

    # Find previous day's allocation to detect sells
    from datetime import datetime as _dt, timedelta as _td
    prev_date = (_dt.strptime(date, "%Y-%m-%d") - _td(days=1)).strftime("%Y-%m-%d")
    # Search backwards up to 5 days for the most recent prior allocation
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
    # Add sold positions (were in prev day, not in today)
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


# ---- static dashboard ----
@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/bot/{bot_id}")
def bot_page(bot_id: str) -> FileResponse:
    return FileResponse(STATIC_DIR / "bot.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
