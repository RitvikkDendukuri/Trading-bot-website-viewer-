# manual seed script — scheduler does this automatically, but handy for debugging
from __future__ import annotations

import logging

from app.core import db, registry, stats
from app.core.scheduler import seed_all

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")


def _fmt(x, pct=False):
    if x is None:
        return "n/a"
    return f"{x*100:.2f}%" if pct else f"{x:,.2f}"


def main() -> None:
    db.init_db()
    seed_all()
    for bot_id in registry.bot_ids():
        series = db.get_equity_series(bot_id)
        s = stats.summary(series["strategy"], series["spy"])
        st, spy = s["strategy"], s["spy"]
        print(f"\n=== {bot_id} ===")
        print(f"  points: strategy={len(series['strategy'])}, spy={len(series['spy'])}")
        print(f"  current equity : ${_fmt(st['current_equity'])}")
        print(f"  total return   : {_fmt(st['total_return'], True)}   (SPY {_fmt(spy['total_return'], True)})")
        print(f"  excess vs SPY  : {_fmt(s['excess_return_vs_spy'], True)}")
        print(f"  Sharpe         : {_fmt(st['sharpe'])}   (SPY {_fmt(spy['sharpe'])})")
        print(f"  Sortino        : {_fmt(st['sortino'])}   (SPY {_fmt(spy['sortino'])})")
        print(f"  max drawdown   : {_fmt(st['max_drawdown'], True)}   (SPY {_fmt(spy['max_drawdown'], True)})")


if __name__ == "__main__":
    main()
