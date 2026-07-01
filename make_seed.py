# Export the current SQLite DB into committed seed_<bot_id>.json files.
#
# Render only ships the committed seed files (data/*.db is gitignored), so the
# deployed site can never show data newer than whatever these seeds contain.
# Run this before deploying to bake the latest equity curve + allocations into
# the seed, then commit the refreshed data/seed_*.json.
#
#   python make_seed.py                 # export every bot with data
#   python make_seed.py sector_rotation # export a single bot
from __future__ import annotations

import json
import sys
from pathlib import Path

from app.core import db, registry

# Seeds live outside data/ so the Render persistent-disk mount can't shadow them.
SEED_DIR = Path(__file__).resolve().parent / "seeds"


def export_bot(bot_id: str) -> bool:
    # merge backtest + live points exactly as the dashboard renders them
    series = db.get_equity_series(bot_id)
    strat = [[p["ts"], p["value"]] for p in series["strategy"]]
    spy = [[p["ts"], p["value"]] for p in series["spy"]]
    if len(strat) < 10:
        print(f"  {bot_id}: only {len(strat)} points, skipping.")
        return False

    # pull every daily allocation snapshot
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT data FROM daily_allocations WHERE bot_id=? ORDER BY date ASC",
            (bot_id,),
        ).fetchall()
    allocations = [json.loads(r["data"]) for r in rows]

    payload = {
        "equity": {"strategy": strat, "spy": spy},
        "allocations": allocations,
        "regime": db.latest_regime(bot_id) or "",
    }

    SEED_DIR.mkdir(parents=True, exist_ok=True)
    path = SEED_DIR / f"seed_{bot_id}.json"
    path.write_text(json.dumps(payload))
    print(
        f"  {bot_id}: wrote {path.name} "
        f"({len(strat)} strategy pts, {len(allocations)} allocations, "
        f"{strat[0][0][:10]} -> {strat[-1][0][:10]})"
    )
    return True


def main() -> None:
    db.init_db()
    targets = sys.argv[1:] or registry.bot_ids()
    print(f"Exporting seeds for: {', '.join(targets)}")
    for bot_id in targets:
        export_bot(bot_id)


if __name__ == "__main__":
    main()
