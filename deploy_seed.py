# One-command refresh + deploy of the committed seed(s).
#
# On Render's Free plan the SQLite DB is ephemeral (no persistent disk, and the
# service spins down when idle), so the deployed dashboard can only show what the
# committed seed contains. This script regenerates each bot's seed straight from
# the strategy backtest through *today* — a complete, gap-free curve — then commits
# and pushes so Render redeploys with fresh data.
#
#   python deploy_seed.py            # refresh + commit + push
#   python deploy_seed.py --no-push  # refresh + commit only
#   python deploy_seed.py --dry-run  # just rewrite the seed files, no git
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from app.core import registry
from app.core.scheduler import INITIAL_CAPITAL, START_DATE

HERE = Path(__file__).resolve().parent
SEED_DIR = HERE / "seeds"


def _regime_of(pts: dict, strat) -> str:
    try:
        return strat.latest_regime() or ""
    except Exception:
        # backtest caches the last regime it computed; fall back to that
        for a in reversed(pts.get("allocations", [])):
            if a.get("regime"):
                return a["regime"]
    return ""


def refresh_bot(bot_id: str) -> bool:
    strat = registry.get_strategy(bot_id)
    print(f"  {bot_id}: running backtest (downloads prices, ~30-90s)...")
    pts = strat.run_backtest(START_DATE, INITIAL_CAPITAL)
    s = pts.get("strategy", [])
    if len(s) < 10 or any(v <= 0 for _, v in s):
        print(f"  {bot_id}: backtest returned invalid data — keeping existing seed.")
        return False

    payload = {
        "equity": {
            "strategy": [[ts, v] for ts, v in s],
            "spy": [[ts, v] for ts, v in pts.get("spy", [])],
        },
        "allocations": pts.get("allocations", []),
        "regime": _regime_of(pts, strat),
    }
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    (SEED_DIR / f"seed_{bot_id}.json").write_text(json.dumps(payload))
    print(
        f"  {bot_id}: wrote seed ({len(s)} pts, {s[0][0][:10]} -> {s[-1][0][:10]}, "
        f"regime={payload['regime']})"
    )
    return True


def _git(*args: str) -> None:
    subprocess.run(["git", *args], cwd=HERE, check=True)


def main() -> None:
    flags = set(sys.argv[1:])
    print("Refreshing seeds from backtest through today...")
    changed = [b for b in registry.bot_ids() if refresh_bot(b)]
    if not changed:
        print("No seeds updated.")
        return
    if "--dry-run" in flags:
        print("Dry run — seed files rewritten, no git actions.")
        return
    _git("add", "seeds/")
    msg = f"Refresh seed data ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
    _git("commit", "-m", msg)
    if "--no-push" in flags:
        print("Committed. Skipping push (--no-push). Run 'git push' when ready.")
        return
    _git("push", "origin", "main")
    print("Pushed to main — Render will redeploy with the fresh, gap-free seed.")


if __name__ == "__main__":
    main()
