# adapter for the sector rotation strategy — builds data in memory, normalizes equity to platform start
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

_BOT_DIR = Path(__file__).resolve().parent
if str(_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_BOT_DIR))

import sector as sec  # noqa: E402
import update_macro as um  # noqa: E402

GITHUB_URL = "https://github.com/RitvikkDendukuri/Macro-Economic-Sector-Rotation-Trading-Bot"

METHODOLOGY = """
The Macro-Economic Sector Rotation strategy rotates capital across sector ETFs
based on the prevailing macroeconomic regime.

1. Regime detection — z-scored moving averages of four macro inputs
   (Consumer/XLY, Labor/SPY, Inflation/XLE, Credit/XLF) are combined into
   Growth, Inflation-pressure, and Financial-stress scores. Rolling quantiles
   classify the economy into one of seven regimes: Recovery, Goldilocks,
   Reflation, Overheat, Stagflation, Slowdown, Crisis. The regime is smoothed
   with a 14-day rolling mode to avoid whipsaws.

2. Candidate selection — each regime maps to a basket of ETFs historically
   favored in that environment (e.g. Energy/Gold/Utilities in Stagflation;
   Treasuries/Gold/Dollar in Crisis).

3. Ranking & filtering — candidates are scored on 126-day momentum, 63-day
   relative strength vs SPY, and screened for excessive volatility. The top
   names are kept.

4. Portfolio construction — selected ETFs are weighted (capped at 25% each)
   and a volatility-targeting overlay scales leverage (0.5x–2.0x) toward an
   18% annualized volatility target.

5. Rebalancing — the portfolio is rebalanced DAILY, and immediately whenever
   the detected regime changes.
""".strip()

METADATA = {
    "id": "sector_rotation",
    "name": "Macro-Economic Sector Rotation",
    "tagline": "Rotates sector ETFs by macro regime, daily rebalanced.",
    "github_url": GITHUB_URL,
    "benchmark": "SPY",
    "env_prefix": "ALPACA",  # which env vars hold this bot's Alpaca keys
    "methodology": METHODOLOGY,
}

_cache: Dict[str, object] = {"built_at": None, "macro": None, "prices": None}
_CACHE_TTL = timedelta(hours=6)


def _build_data() -> Tuple[pd.DataFrame, pd.DataFrame]:
    now = datetime.utcnow()
    built_at = _cache["built_at"]
    if built_at and now - built_at < _CACHE_TTL and _cache["macro"] is not None:
        return _cache["macro"], _cache["prices"]  # type: ignore[return-value]

    all_tickers = (
        set(um.coreTickers.values())
        | set(um.extraTickers.values())
        | set(um.sectorTickers)
    )
    raw = {}
    for t in sorted(all_tickers):
        s = None
        for attempt in range(3):  # Yahoo occasionally times out; retry
            try:
                s = um.downloadSeries(t)
            except Exception:
                s = None
            if s is not None and not s.empty:
                break
        if s is not None and not s.empty:
            raw[t] = s

    # macro indicators
    macro_cols = {}
    for name, ticker in um.coreTickers.items():
        if ticker in raw:
            macro_cols[name] = um.transformCore(name, raw[ticker])
    if "^TNX" in raw and "^IRX" in raw:
        ty, tm = raw["^TNX"].align(raw["^IRX"], join="inner")
        macro_cols["yield_curve"] = ty - tm
    if "^VIX" in raw:
        macro_cols["volatility"] = raw["^VIX"]

    # missing core tickers silently zero out indicators and produce bogus regimes
    missing = [t for t in um.coreTickers.values() if t not in raw]
    if missing or "SPY" not in raw:
        raise RuntimeError(f"Incomplete download; missing core tickers: {missing or ['SPY']}")

    macro = pd.DataFrame(macro_cols).sort_index().ffill().dropna()
    macro = macro.resample("D").ffill()

    # sector prices
    price_cols = {t: raw[t] for t in um.sectorTickers if t in raw}
    prices = pd.DataFrame(price_cols).sort_index().ffill()
    prices = prices.loc[prices.index >= macro.index.min()].resample("D").ffill()

    # single-day >50% moves are bad Yahoo prints — mask and ffill
    spike = prices.pct_change().abs() > 0.5
    if spike.to_numpy().any():
        prices = prices.mask(spike).ffill()

    _cache.update({"built_at": now, "macro": macro, "prices": prices})
    return macro, prices


def _align(macro: pd.DataFrame, prices: pd.DataFrame):
    start = max(macro.index.min(), prices.index.min())
    end = min(macro.index.max(), prices.index.max())
    return macro.loc[start:end], prices.loc[start:end]


def _build_hourly_prices(window_days: int) -> pd.DataFrame:
    now = datetime.utcnow()
    built = _cache.get("hourly_built_at")
    if built and now - built < _CACHE_TTL and _cache.get("hourly") is not None:
        return _cache["hourly"]  # type: ignore[return-value]

    import yfinance as yf

    start = (now - timedelta(days=window_days)).strftime("%Y-%m-%d")
    data = yf.download(
        sorted(set(um.sectorTickers)),
        start=start,
        interval="1h",
        auto_adjust=False,
        progress=False,
    )
    if data is None or data.empty:
        return pd.DataFrame()
    if isinstance(data.columns, pd.MultiIndex):
        level0 = data.columns.get_level_values(0)
        field = "Adj Close" if "Adj Close" in level0 else "Close"
        data = data.xs(field, axis=1)
    if data.index.tz is None:
        data.index = data.index.tz_localize("UTC")
    else:
        data.index = data.index.tz_convert("UTC")
    data = data.dropna(how="all")
    _cache.update({"hourly_built_at": now, "hourly": data})
    return data


def run_backtest(
    start_date: str, initial_capital: float, hourly_window_days: Optional[int] = None
) -> Dict[str, List[tuple]]:
    # daily backtest is authoritative, hourly prices fill in intraday detail
    if hourly_window_days is None:
        days = (datetime.utcnow().date() - pd.Timestamp(start_date).date()).days
        hourly_window_days = max(days + 5, 35)
    macro, prices = _align(*_build_data())
    cfg = sec.PortfolioConfig()
    detector = sec.MacroRegimeDetector(sec.MacroIndicatorConfig())
    regimes = detector.detectRegimeSeriesSmoothed(macro)
    backtester = sec.Backtester(
        prices=prices,
        regimeSeries=regimes,
        sectorMapper=sec.SectorMapper(),
        assetFilters=sec.AssetFilters(),
        portfolioConstructor=sec.PortfolioConstructor(cfg),
        portfolioConfig=cfg,
    )
    equity_curve, _ = backtester.run(initialCapital=1_000_000.0)

    eq = equity_curve["equity"].dropna()
    start_ts = pd.Timestamp(start_date)
    eq = eq.loc[eq.index >= start_ts]
    if eq.empty:
        return {"strategy": [], "spy": []}
    eq = eq * (initial_capital / eq.iloc[0])  # normalize to start capital

    last_reg = regimes.dropna()
    _cache["latest_regime"] = last_reg.iloc[-1].name if len(last_reg) else None

    try:
        hourly = _build_hourly_prices(hourly_window_days)
    except Exception:
        hourly = pd.DataFrame()

    rows_by_date: Dict[object, list] = {}
    if not hourly.empty:
        for ts in hourly.index:
            rows_by_date.setdefault(ts.date(), []).append(ts)

    strat_pts: List[tuple] = []
    ref: Dict[str, float] = {}     # each ticker's last hourly close (prev day)
    prev_d = None
    for d in list(eq.index):
        W = backtester.weightsTimeline.get(d) or {}
        L = backtester.levTimeline.get(d, 1.0)
        hrs = rows_by_date.get(d.date(), [])
        if not hrs or not W or prev_d is None:
            strat_pts.append((d.isoformat(), float(eq.loc[d])))
            prev_d = d
            if hrs:
                last = hrs[-1]
                ref = {t: float(hourly.at[last, t]) for t in hourly.columns
                       if pd.notna(hourly.at[last, t])}
            continue
        eq_prev = float(eq.loc[prev_d])
        first = hrs[0]
        for h in hrs:
            ret = 0.0
            for t, w in W.items():
                if t not in hourly.columns:
                    continue
                ph = hourly.at[h, t]
                base = ref.get(t)
                if base is None or base <= 0:
                    fb = hourly.at[first, t]
                    base = float(fb) if pd.notna(fb) and fb > 0 else None
                if base is None or pd.isna(ph) or ph <= 0:
                    continue
                ratio = float(ph) / base
                if 0.2 < ratio < 5.0:           # ignore split/bad-data spikes
                    ret += w * (ratio - 1.0)
            factor = max(1.0 + L * ret, 0.05)   # never let equity go to/below zero
            strat_pts.append((h.isoformat(), eq_prev * factor))
        last = hrs[-1]
        ref = {t: float(hourly.at[last, t]) for t in hourly.columns
               if pd.notna(hourly.at[last, t])}
        prev_d = d

    spy_pts: List[tuple] = []
    if "SPY" in prices.columns:
        spy_daily = prices["SPY"].reindex(eq.index).ffill().dropna()
        if not spy_daily.empty:
            spy_norm = spy_daily / float(spy_daily.iloc[0]) * initial_capital
            has_h = (not hourly.empty) and ("SPY" in hourly.columns)
            sref = None
            sprev = None
            for d in list(eq.index):
                if d not in spy_norm.index:
                    continue
                hrs = rows_by_date.get(d.date(), []) if has_h else []
                if not hrs or sprev is None:
                    spy_pts.append((d.isoformat(), float(spy_norm.loc[d])))
                    sprev = d
                    if hrs:
                        lp = hourly.at[hrs[-1], "SPY"]
                        sref = float(lp) if pd.notna(lp) else sref
                    continue
                eq_prev = float(spy_norm.loc[sprev])
                first = hrs[0]
                for h in hrs:
                    ph = hourly.at[h, "SPY"]
                    base = sref
                    if base is None or base <= 0:
                        fb = hourly.at[first, "SPY"]
                        base = float(fb) if pd.notna(fb) and fb > 0 else None
                    if base is None or pd.isna(ph) or ph <= 0:
                        continue
                    ratio = float(ph) / base
                    if 0.2 < ratio < 5.0:
                        spy_pts.append((h.isoformat(), eq_prev * ratio))
                lp = hourly.at[hrs[-1], "SPY"]
                sref = float(lp) if pd.notna(lp) else sref
                sprev = d

    allocations: List[dict] = []
    eq_series = eq
    dates_list = list(eq_series.index)
    for i, d in enumerate(dates_list):
        W = backtester.weightsTimeline.get(d) or {}
        L = backtester.levTimeline.get(d, 1.0)
        regime_at_d = regimes.loc[d] if d in regimes.index else None
        regime_name = ""
        if regime_at_d is not None and hasattr(regime_at_d, "name"):
            regime_name = regime_at_d.name
        elif regime_at_d is not None:
            regime_name = str(regime_at_d)

        sector_details = []
        prev_W = backtester.weightsTimeline.get(dates_list[i - 1]) if i > 0 else {}
        if not prev_W:
            prev_W = {}
        for t, w in W.items():
            if t in prices.columns and i > 0:
                prev_d = dates_list[i - 1]
                p_today = prices.at[d, t] if d in prices.index else None
                p_prev = prices.at[prev_d, t] if prev_d in prices.index else None
                day_ret = float(p_today / p_prev - 1.0) if (p_today and p_prev and p_prev > 0) else 0.0
            else:
                day_ret = 0.0
            prev_w = prev_W.get(t, 0.0)
            sector_details.append({
                "symbol": t,
                "weight": round(w, 4),
                "prev_weight": round(prev_w, 4),
                "day_return": round(day_ret, 4),
                "contribution": round(w * L * day_ret, 4),
            })

        equity_val = float(eq_series.loc[d])
        prev_eq = float(eq_series.loc[dates_list[i - 1]]) if i > 0 else equity_val
        portfolio_return = (equity_val / prev_eq - 1.0) if prev_eq > 0 and i > 0 else 0.0
        allocations.append({
            "date": d.strftime("%Y-%m-%d"),
            "leverage": round(L, 3),
            "regime": regime_name,
            "portfolio_return": round(portfolio_return, 4),
            "equity": round(equity_val, 2),
            "sectors": sector_details,
        })

    return {"strategy": strat_pts, "spy": spy_pts, "allocations": allocations}


def latest_regime() -> str:
    macro, _ = _align(*_build_data())
    detector = sec.MacroRegimeDetector(sec.MacroIndicatorConfig())
    regimes = detector.detectRegimeSeriesSmoothed(macro).dropna()
    if regimes.empty:
        return "UNKNOWN"
    r = regimes.iloc[-1]
    return r.name if hasattr(r, "name") else str(r)


def _target_leverage(prices: pd.DataFrame, weights: Dict[str, float], cfg) -> float:
    chosen = [t for t in weights if t in prices.columns]
    if not chosen:
        return 1.0
    lb = cfg.volLookbackDays
    sub = prices[chosen].iloc[-(lb + 1):]
    rets = sub.pct_change().dropna()
    if rets.empty:
        return 1.0
    w = pd.Series({t: weights[t] for t in chosen})
    port_ret = (rets[chosen] * w).sum(axis=1)
    realized_vol = float(port_ret.std() * np.sqrt(252))
    if realized_vol <= 0:
        return 1.0
    lev = cfg.targetVol / realized_vol
    return float(max(cfg.minLeverage, min(cfg.maxLeverage, lev)))


def compute_live_targets() -> Tuple[Dict[str, float], str, float]:
    macro, prices = _align(*_build_data())
    cfg = sec.PortfolioConfig()
    detector = sec.MacroRegimeDetector(sec.MacroIndicatorConfig())
    regimes = detector.detectRegimeSeriesSmoothed(macro).dropna()
    if regimes.empty:
        return {}, "UNKNOWN", 1.0
    regime = regimes.iloc[-1]
    label = regime.name if hasattr(regime, "name") else str(regime)

    mapper = sec.SectorMapper()
    candidates = [t for t in mapper.getSessionsForRegime(regime) if t in prices.columns]
    if not candidates:
        return {}, label, 1.0

    bench = prices["SPY"] if "SPY" in prices.columns else None
    window = prices[candidates].iloc[-260:]
    top_n = int(1.0 / cfg.maxWeightPerSector)
    filters = sec.AssetFilters()
    chosen = filters.filterAssets(window, benchmark=bench, topN=top_n)
    if not chosen:
        return {}, label, 1.0

    sub = window[chosen]
    momLb = min(filters.momLb, len(sub) - 1)
    rsLb = min(filters.rsLb, len(sub) - 1)
    if momLb > 0 and rsLb > 0:
        momMain = sub.pct_change(momLb).iloc[-1]
        momFast = sub.pct_change(rsLb).iloc[-1]
        scores = 0.6 * momMain + 0.4 * momFast
        weights = sec.PortfolioConstructor(cfg).buildPortfolio(chosen, scores=scores)
    else:
        weights = sec.PortfolioConstructor(cfg).buildPortfolio(chosen)

    leverage = _target_leverage(prices, weights, cfg)
    return weights, label, leverage
