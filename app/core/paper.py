# paper trading engine — marks portfolio to market every minute using Yahoo 1-min bars
# rebalances once per session, self-heals if server was down (Yahoo serves full day)
from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from app.core import db, registry

log = logging.getLogger("paper")

INITIAL_CAPITAL = float(os.environ.get("SEED_INITIAL_CAPITAL", "100000"))


def _fetch_1m(symbols: List[str]) -> pd.DataFrame:
    import yfinance as yf

    data = yf.download(
        symbols,
        period="1d",
        interval="1m",
        auto_adjust=False,
        progress=False,
        prepost=False,
    )
    if data is None or data.empty:
        return pd.DataFrame()

    if isinstance(data.columns, pd.MultiIndex):
        level0 = data.columns.get_level_values(0)
        field = "Adj Close" if "Adj Close" in level0 else "Close"
        data = data.xs(field, axis=1)
    elif "Close" in data.columns:
        data = data[["Close"]]
        data.columns = symbols[:1]

    if isinstance(data, pd.Series):
        data = data.to_frame(name=symbols[0])
    data = data.dropna(how="all")
    # ffill NaN gaps in thinly-traded ETFs so leverage math doesn't break
    return data.ffill().bfill()


def _load_state(bot_id: str) -> Optional[dict]:
    raw = db.get_meta(f"{bot_id}:paper_state")
    return json.loads(raw) if raw else None


def _save_state(bot_id: str, state: dict) -> None:
    db.set_meta(f"{bot_id}:paper_state", json.dumps(state))


def _start_equity(bot_id: str, series: str, session: str) -> float:
    v = db.last_value_before(bot_id, series, session)
    return float(v) if v is not None else INITIAL_CAPITAL


def tick(bot_id: str) -> None:
    meta = registry.get_metadata(bot_id)
    benchmark = meta.get("benchmark", "SPY")
    strat = registry.get_strategy(bot_id)

    try:
        weights, regime, leverage = strat.compute_live_targets()
    except Exception as e:
        log.warning("compute_live_targets failed for %s: %s", bot_id, e)
        return
    if not weights:
        return

    symbols = sorted(set(weights) | {benchmark})
    try:
        bars = _fetch_1m(symbols)
    except Exception as e:
        log.warning("1m fetch failed for %s: %s", bot_id, e)
        return
    bars = bars[[c for c in symbols if c in bars.columns]]
    if bars.empty:
        return

    session = str(bars.index[-1].date())
    state = _load_state(bot_id)

    if state is None or state.get("session") != session or "e0" not in state:
        if db.get_meta(f"{bot_id}:go_live") is None:
            db.set_meta(f"{bot_id}:go_live", session)

        open_row = bars.iloc[0]
        opens = {
            t: float(open_row[t])
            for t in weights
            if t in open_row and pd.notna(open_row[t]) and float(open_row[t]) > 0
        }
        spy_open = (
            float(open_row[benchmark])
            if benchmark in open_row and pd.notna(open_row[benchmark]) and float(open_row[benchmark]) > 0
            else None
        )
        state = {
            "session": session,
            "e0": _start_equity(bot_id, "strategy", session),
            "spy_e0": _start_equity(bot_id, "spy", session),
            "opens": opens,
            "spy_open": spy_open,
            "weights": {t: weights[t] for t in opens},
            "leverage": leverage,
            "regime": regime,
        }
        _save_state(bot_id, state)
        db.set_regime(bot_id, session, regime)
        log.info("Paper rebalance %s @ %s lev=%.2f -> %s", bot_id, session, leverage, list(opens))

        # Save daily allocation for the trade-detail panel
        prev_alloc_raw = db.get_daily_allocation(bot_id, (pd.Timestamp(session) - pd.Timedelta(days=1)).strftime("%Y-%m-%d"))
        prev_weights = {}
        if prev_alloc_raw:
            prev_data = json.loads(prev_alloc_raw)
            prev_weights = {s["symbol"]: s["weight"] for s in prev_data.get("sectors", [])}
        sectors = []
        for t, wt in weights.items():
            sectors.append({
                "symbol": t,
                "weight": round(wt, 4),
                "prev_weight": round(prev_weights.get(t, 0.0), 4),
                "day_return": 0.0,
                "contribution": 0.0,
            })
        alloc_data = {
            "date": session,
            "leverage": round(leverage, 3),
            "regime": regime,
            "portfolio_return": 0.0,
            "equity": round(state["e0"], 2),
            "sectors": sectors,
        }
        db.save_daily_allocation(bot_id, session, json.dumps(alloc_data))

    e0 = state["e0"]
    spy_e0 = state["spy_e0"]
    opens = state["opens"]
    spy_open = state["spy_open"]
    w = state["weights"]
    lev = state["leverage"]

    # return-based mark to market: eq = e0 * (1 + lev * portfolio_return)
    last_eq = None
    for ts, row in bars.iterrows():
        ret = 0.0
        for t, wt in w.items():
            px = row.get(t)
            if px is not None and pd.notna(px) and opens.get(t):
                ret += wt * (float(px) / opens[t] - 1.0)
        eq = e0 * max(1.0 + lev * ret, 0.01)
        ts_iso = ts.isoformat()
        db.add_live_point(bot_id, ts_iso, "strategy", eq)
        last_eq = eq
        spy_px = row.get(benchmark)
        if spy_open and spy_px is not None and pd.notna(spy_px):
            db.add_live_point(bot_id, ts_iso, "spy", spy_e0 * (float(spy_px) / spy_open))

    last_row = bars.iloc[-1]
    equity = last_eq or e0
    snapshot = []
    for t, wt in w.items():
        px = last_row.get(t)
        op = opens.get(t)
        if px is not None and pd.notna(px) and op:
            shares = (wt * lev) * e0 / op       # bought at the open, held for the day
            mv = shares * float(px)             # live market value
            snapshot.append(
                {
                    "symbol": t,
                    "qty": shares,
                    "market_value": mv,
                    "weight": (mv / equity) if equity else 0.0,
                    "change_pct": float(px) / op - 1.0,        # intraday move vs the open
                    "change_amt": shares * (float(px) - op),   # $ gain/loss on the day
                }
            )
    db.replace_positions(bot_id, snapshot)

    # Update daily allocation with live returns
    alloc_raw = db.get_daily_allocation(bot_id, session)
    if alloc_raw and equity:
        alloc = json.loads(alloc_raw)
        alloc["equity"] = round(equity, 2)
        alloc["portfolio_return"] = round(equity / e0 - 1.0, 4) if e0 > 0 else 0.0
        for sec in alloc.get("sectors", []):
            t = sec["symbol"]
            op = opens.get(t)
            px = last_row.get(t) if t in last_row.index else None
            if op and px is not None and pd.notna(px) and op > 0:
                sec["day_return"] = round(float(px) / op - 1.0, 4)
                sec["contribution"] = round(sec["weight"] * lev * sec["day_return"], 4)
        db.save_daily_allocation(bot_id, session, json.dumps(alloc))

    _maybe_execute_on_alpaca(bot_id, meta, weights, state["session"])


def _maybe_execute_on_alpaca(bot_id: str, meta: dict, weights: dict, session: str) -> None:
    from app.core.alpaca import AlpacaClient, AlpacaError

    client = AlpacaClient(env_prefix=meta.get("env_prefix", "ALPACA"))
    if not client.configured:
        return
    if db.get_meta(f"{bot_id}:alpaca_exec") == session:
        return
    try:
        client.sync_to_weights(weights)
        db.set_meta(f"{bot_id}:alpaca_exec", session)
        log.info("Mirrored %s rebalance to Alpaca paper account.", bot_id)
    except AlpacaError as e:
        log.warning("Alpaca execution failed for %s: %s", bot_id, e)
