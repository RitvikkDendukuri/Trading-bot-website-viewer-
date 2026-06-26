# performance metrics — takes [{ts, value}] points, returns plain floats
from __future__ import annotations

import math
from typing import List, Optional

TRADING_DAYS = 252


def _values(points: List[dict]) -> List[float]:
    return [float(p["value"]) for p in points if p.get("value") is not None]


def hourly_except_latest(points: List[dict]) -> List[dict]:
    # minute detail for today, hourly for older days
    if not points:
        return points
    latest_date = max(p["ts"][:10] for p in points)
    by_hour: dict = {}              # 'YYYY-MM-DDTHH' -> last point in that hour
    order: List[str] = []
    today_points: List[dict] = []
    for p in points:
        if p["ts"][:10] == latest_date:
            today_points.append(p)
        else:
            hour = p["ts"][:13]
            if hour not in by_hour:
                order.append(hour)
            by_hour[hour] = p
    older = [by_hour[h] for h in sorted(order)]
    today_points.sort(key=lambda p: p["ts"])
    return older + today_points


def to_daily(points: List[dict]) -> List[dict]:
    if not points:
        return points
    by_date: dict = {}
    order: List[str] = []
    for p in points:
        day = p["ts"][:10]
        if day not in by_date:
            order.append(day)
        by_date[day] = p
    return [by_date[d] for d in sorted(order)]


def _daily_returns(values: List[float]) -> List[float]:
    rets = []
    for prev, cur in zip(values, values[1:]):
        if prev and prev != 0:
            rets.append(cur / prev - 1.0)
    return rets


def total_return(points: List[dict]) -> Optional[float]:
    v = _values(points)
    if len(v) < 2 or v[0] == 0:
        return None
    return v[-1] / v[0] - 1.0


def max_drawdown(points: List[dict]) -> Optional[float]:
    v = _values(points)
    if len(v) < 2:
        return None
    peak = v[0]
    mdd = 0.0
    for x in v:
        peak = max(peak, x)
        if peak > 0:
            mdd = min(mdd, x / peak - 1.0)
    return mdd


def _annualized_vol(rets: List[float]) -> float:
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(TRADING_DAYS)


def sharpe(points: List[dict], rf: float = 0.0) -> Optional[float]:
    rets = _daily_returns(_values(points))
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    daily_rf = rf / TRADING_DAYS
    vol = _annualized_vol(rets)
    if vol == 0:
        return None
    return (mean - daily_rf) * TRADING_DAYS / vol


def sortino(points: List[dict], rf: float = 0.0) -> Optional[float]:
    rets = _daily_returns(_values(points))
    if len(rets) < 2:
        return None
    daily_rf = rf / TRADING_DAYS
    mean = sum(rets) / len(rets)
    downside = [min(0.0, r - daily_rf) for r in rets]
    dd_var = sum(d ** 2 for d in downside) / len(downside)
    dd = math.sqrt(dd_var) * math.sqrt(TRADING_DAYS)
    if dd == 0:
        return None
    return (mean - daily_rf) * TRADING_DAYS / dd


def cagr(points: List[dict]) -> Optional[float]:
    v = _values(points)
    if len(v) < 2 or v[0] <= 0:
        return None
    years = max(len(v) / TRADING_DAYS, 1e-9)
    return (v[-1] / v[0]) ** (1.0 / years) - 1.0


def calmar(points: List[dict]) -> Optional[float]:
    c = cagr(points)
    mdd = max_drawdown(points)
    if c is None or mdd is None or mdd == 0:
        return None
    return c / abs(mdd)


def _aligned_returns(strategy_pts: List[dict], spy_pts: List[dict]):
    sd = {p["ts"][:10]: p["value"] for p in to_daily(strategy_pts)}
    pd_ = {p["ts"][:10]: p["value"] for p in to_daily(spy_pts)}
    dates = sorted(set(sd) & set(pd_))
    sr, pr = [], []
    for prev, cur in zip(dates, dates[1:]):
        if sd[prev] and pd_[prev]:
            sr.append(sd[cur] / sd[prev] - 1.0)
            pr.append(pd_[cur] / pd_[prev] - 1.0)
    return sr, pr


def beta(strategy_pts: List[dict], spy_pts: List[dict]) -> Optional[float]:
    # cov(strat, SPY) / var(SPY) on daily returns
    sr, pr = _aligned_returns(strategy_pts, spy_pts)
    if len(pr) < 2:
        return None
    mp = sum(pr) / len(pr)
    ms = sum(sr) / len(sr)
    var_p = sum((p - mp) ** 2 for p in pr)
    if var_p == 0:
        return None
    cov = sum((s - ms) * (p - mp) for s, p in zip(sr, pr))
    return cov / var_p


def alpha(strategy_pts: List[dict], spy_pts: List[dict], rf: float = 0.0) -> Optional[float]:
    # annualized CAPM alpha: (strat - beta * SPY) daily mean * 252
    b = beta(strategy_pts, spy_pts)
    if b is None:
        return None
    sr, pr = _aligned_returns(strategy_pts, spy_pts)
    if not sr:
        return None
    daily_rf = rf / TRADING_DAYS
    ms = sum(sr) / len(sr)
    mp = sum(pr) / len(pr)
    daily_alpha = (ms - daily_rf) - b * (mp - daily_rf)
    return daily_alpha * TRADING_DAYS


def summary(strategy_pts: List[dict], spy_pts: List[dict]) -> dict:
    # metrics use daily reduction so ratios annualize correctly
    latest_equity = _values(strategy_pts)[-1] if strategy_pts else None
    latest_start = _values(strategy_pts)[0] if strategy_pts else None
    strategy_pts = to_daily(strategy_pts)
    spy_pts = to_daily(spy_pts)
    strat = {
        "total_return": total_return(strategy_pts),
        "cagr": cagr(strategy_pts),
        "sharpe": sharpe(strategy_pts),
        "sortino": sortino(strategy_pts),
        "max_drawdown": max_drawdown(strategy_pts),
        "calmar": calmar(strategy_pts),
        "beta": beta(strategy_pts, spy_pts),
        "alpha": alpha(strategy_pts, spy_pts),
        "current_equity": latest_equity,
        "start_equity": latest_start,
    }
    spy = {
        "total_return": total_return(spy_pts),
        "sharpe": sharpe(spy_pts),
        "sortino": sortino(spy_pts),
        "max_drawdown": max_drawdown(spy_pts),
        "calmar": calmar(spy_pts),
        "beta": 1.0,    # SPY vs itself
        "alpha": 0.0,
    }
    excess = None
    if strat["total_return"] is not None and spy["total_return"] is not None:
        excess = strat["total_return"] - spy["total_return"]
    return {"strategy": strat, "spy": spy, "excess_return_vs_spy": excess}
