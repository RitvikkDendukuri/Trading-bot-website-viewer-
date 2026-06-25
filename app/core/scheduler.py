# background worker — seeds backtest on startup, ticks paper engine every 60s, compacts old data
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone

from app.core import db, paper, registry

log = logging.getLogger("scheduler")

START_DATE = os.environ.get("SEED_START_DATE", "2026-01-01")
INITIAL_CAPITAL = float(os.environ.get("SEED_INITIAL_CAPITAL", "100000"))
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "60"))
REFRESH_WINDOW_DAYS = int(os.environ.get("REFRESH_WINDOW_DAYS", "35"))

_stop = threading.Event()


# ---------------- seeding ----------------

def seed_bot(bot_id: str) -> None:
    strat = registry.get_strategy(bot_id)
    try:
        # full hourly history (seed runs once, so this is safe and stays stable)
        points = strat.run_backtest(START_DATE, INITIAL_CAPITAL)
    except Exception as e:  # network / data failure shouldn't crash startup
        log.warning("Seed failed for %s: %s", bot_id, e)
        return

    strat_pts = points.get("strategy", [])
    if len(strat_pts) < 10 or any(v <= 0 for _, v in strat_pts):
        log.warning("Seed for %s produced invalid data; keeping existing.", bot_id)
        return

    go_live = db.get_meta(f"{bot_id}:go_live")
    if go_live:
        points = {
            series: [(ts, v) for (ts, v) in pts if ts[:10] < go_live]
            for series, pts in points.items()
        }

    # Save daily allocation snapshots for the trade-detail panel
    allocations = points.pop("allocations", [])
    if allocations:
        alloc_rows = [
            {"date": a["date"], "data": json.dumps(a)}
            for a in allocations
        ]
        db.save_daily_allocations(bot_id, alloc_rows)
        log.info("Saved %d daily allocation snapshots for %s.", len(alloc_rows), bot_id)

    if db.has_backtest(bot_id):
        cutoff = (datetime.utcnow().date() - timedelta(days=REFRESH_WINDOW_DAYS)).isoformat()
        window = {
            series: [(ts, v) for (ts, v) in pts if ts[:10] >= cutoff]
            for series, pts in points.items()
        }
        n = db.refresh_backtest_window(bot_id, cutoff, window)
        log.info("Refreshed last %dd of %s (%d pts).", REFRESH_WINDOW_DAYS, bot_id, n)
    else:
        db.replace_backtest_series(bot_id, points)
        log.info("Full seed %s (%d strategy pts).", bot_id, len(strat_pts))

    try:
        regime = strat.latest_regime()
        db.set_regime(bot_id, datetime.utcnow().date().isoformat(), regime)
    except Exception as e:
        log.warning("Regime fetch failed for %s: %s", bot_id, e)


def seed_all() -> None:
    for bot_id in registry.bot_ids():
        seed_bot(bot_id)
    db.set_meta("last_seed", datetime.utcnow().isoformat())


def seed_missing() -> None:
    for bot_id in registry.bot_ids():
        if not db.has_backtest(bot_id):
            seed_bot(bot_id)


# ---------------- live engine ----------------

def tick_all() -> None:
    for bot_id in registry.bot_ids():
        try:
            paper.tick(bot_id)
        except Exception as e:
            log.warning("Paper tick failed for %s: %s", bot_id, e)


def maybe_compact() -> None:
    today = datetime.now(timezone.utc).date().isoformat()
    if db.get_meta("last_compact") == today:
        return
    try:
        deleted = db.compact_live_to_hourly(today)
        db.set_meta("last_compact", today)
        log.info("Compacted %d intraday rows to hourly.", deleted)
    except Exception as e:
        log.warning("Compaction failed: %s", e)


# ---------------- loops ----------------

def _poll_loop() -> None:
    while not _stop.is_set():
        try:
            tick_all()
            maybe_compact()
        except Exception as e:
            log.exception("poll loop error: %s", e)
        _stop.wait(POLL_SECONDS)


def _seed_loop() -> None:
    while not _stop.wait(24 * 3600):
        try:
            seed_all()
        except Exception as e:
            log.exception("seed loop error: %s", e)


def start() -> None:
    db.init_db()
    # seed once — re-running is non-deterministic because regime model is data-sensitive
    threading.Thread(target=seed_missing, daemon=True).start()
    threading.Thread(target=_poll_loop, daemon=True).start()
    log.info("Scheduler started (poll=%ss, start_date=%s)", POLL_SECONDS, START_DATE)


def stop() -> None:
    _stop.set()
