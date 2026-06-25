# SQLite storage — single file DB with WAL mode
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "bots.db"

_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


@contextmanager
def get_conn():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _lock, get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS equity_points (
                bot_id  TEXT NOT NULL,
                ts      TEXT NOT NULL,          -- ISO timestamp
                series  TEXT NOT NULL,          -- 'strategy' | 'spy'
                source  TEXT NOT NULL,          -- 'backtest' | 'live'
                value   REAL NOT NULL,
                PRIMARY KEY (bot_id, ts, series)
            );
            CREATE INDEX IF NOT EXISTS idx_eq_bot_ts ON equity_points (bot_id, ts);

            CREATE TABLE IF NOT EXISTS regimes (
                bot_id  TEXT NOT NULL,
                date    TEXT NOT NULL,
                regime  TEXT NOT NULL,
                PRIMARY KEY (bot_id, date)
            );

            CREATE TABLE IF NOT EXISTS positions (
                bot_id        TEXT NOT NULL,
                symbol        TEXT NOT NULL,
                qty           REAL NOT NULL,
                market_value  REAL NOT NULL,
                weight        REAL NOT NULL,
                change_pct    REAL NOT NULL DEFAULT 0,
                change_amt    REAL NOT NULL DEFAULT 0,
                updated_at    TEXT NOT NULL,
                PRIMARY KEY (bot_id, symbol)
            );

            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS daily_allocations (
                bot_id  TEXT NOT NULL,
                date    TEXT NOT NULL,
                data    TEXT NOT NULL,       -- JSON blob
                PRIMARY KEY (bot_id, date)
            );
            """
        )
        # migrate existing positions tables that predate the change columns
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(positions)")}
        if "change_pct" not in cols:
            conn.execute("ALTER TABLE positions ADD COLUMN change_pct REAL NOT NULL DEFAULT 0")
        if "change_amt" not in cols:
            conn.execute("ALTER TABLE positions ADD COLUMN change_amt REAL NOT NULL DEFAULT 0")
        # migrate: add daily_allocations table if missing
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "daily_allocations" not in tables:
            conn.execute("""
                CREATE TABLE daily_allocations (
                    bot_id  TEXT NOT NULL,
                    date    TEXT NOT NULL,
                    data    TEXT NOT NULL,
                    PRIMARY KEY (bot_id, date)
                )
            """)



def replace_backtest_series(bot_id: str, points: Dict[str, List[tuple]]) -> None:
    with _lock, get_conn() as conn:
        conn.execute(
            "DELETE FROM equity_points WHERE bot_id=? AND source='backtest'", (bot_id,)
        )
        rows = []
        for series, pts in points.items():
            for ts, value in pts:
                rows.append((bot_id, ts, series, "backtest", float(value)))
        conn.executemany(
            "INSERT OR REPLACE INTO equity_points (bot_id, ts, series, source, value)"
            " VALUES (?,?,?,?,?)",
            rows,
        )


def refresh_backtest_window(bot_id: str, cutoff_date: str, points: Dict[str, List[tuple]]) -> int:
    # replace backtest points on/after cutoff, keep earlier history
    with _lock, get_conn() as conn:
        conn.execute(
            "DELETE FROM equity_points WHERE bot_id=? AND source='backtest'"
            " AND substr(ts,1,10) >= ?",
            (bot_id, cutoff_date),
        )
        rows = []
        for series, pts in points.items():
            for ts, value in pts:
                rows.append((bot_id, ts, series, "backtest", float(value)))
        conn.executemany(
            "INSERT OR REPLACE INTO equity_points (bot_id, ts, series, source, value)"
            " VALUES (?,?,?,?,?)",
            rows,
        )
        return len(rows)


def add_live_point(bot_id: str, ts: str, series: str, value: float) -> None:
    with _lock, get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO equity_points (bot_id, ts, series, source, value)"
            " VALUES (?,?,?,'live',?)",
            (bot_id, ts, series, float(value)),
        )


def get_equity_series(bot_id: str) -> Dict[str, List[dict]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT ts, series, source, value FROM equity_points"
            " WHERE bot_id=? ORDER BY ts ASC",
            (bot_id,),
        ).fetchall()
    out: Dict[str, List[dict]] = {"strategy": [], "spy": []}
    for r in rows:
        if r["series"] in out:
            out[r["series"]].append(
                {"ts": r["ts"], "value": r["value"], "source": r["source"]}
            )
    return out


def compact_live_to_hourly(today: str) -> int:
    # collapse past days' minute data to hourly, keep today's minutes
    with _lock, get_conn() as conn:
        cur = conn.execute(
            """
            DELETE FROM equity_points
            WHERE source='live'
              AND substr(ts, 1, 10) < ?
              AND ts NOT IN (
                  SELECT MAX(e2.ts) FROM equity_points e2
                  WHERE e2.source='live'
                    AND e2.bot_id = equity_points.bot_id
                    AND e2.series = equity_points.series
                    AND substr(e2.ts, 1, 13) = substr(equity_points.ts, 1, 13)
              )
            """,
            (today,),
        )
        return cur.rowcount


def last_live_ts(bot_id: str) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT MAX(ts) AS m FROM equity_points WHERE bot_id=? AND source='live'",
            (bot_id,),
        ).fetchone()
    return row["m"] if row and row["m"] else None


def has_backtest(bot_id: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM equity_points WHERE bot_id=? AND source='backtest' LIMIT 1",
            (bot_id,),
        ).fetchone()
    return row is not None


def last_value(bot_id: str, series: str) -> Optional[float]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM equity_points WHERE bot_id=? AND series=? AND value > 0"
            " ORDER BY ts DESC LIMIT 1",
            (bot_id, series),
        ).fetchone()
    return row["value"] if row else None


def last_value_before(bot_id: str, series: str, date_str: str) -> Optional[float]:
    # strictly before date_str — anchors live sessions to prior day's close
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM equity_points WHERE bot_id=? AND series=? AND value > 0"
            " AND substr(ts,1,10) < ? ORDER BY ts DESC LIMIT 1",
            (bot_id, series, date_str),
        ).fetchone()
    return row["value"] if row else None



def set_regime(bot_id: str, date: str, regime: str) -> None:
    with _lock, get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO regimes (bot_id, date, regime) VALUES (?,?,?)",
            (bot_id, date, regime),
        )


def latest_regime(bot_id: str) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT regime FROM regimes WHERE bot_id=? ORDER BY date DESC LIMIT 1",
            (bot_id,),
        ).fetchone()
    return row["regime"] if row else None



def replace_positions(bot_id: str, positions: List[dict]) -> None:
    now = datetime.utcnow().isoformat()
    with _lock, get_conn() as conn:
        conn.execute("DELETE FROM positions WHERE bot_id=?", (bot_id,))
        conn.executemany(
            "INSERT OR REPLACE INTO positions"
            " (bot_id, symbol, qty, market_value, weight, change_pct, change_amt, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    bot_id,
                    p["symbol"],
                    float(p["qty"]),
                    float(p["market_value"]),
                    float(p["weight"]),
                    float(p.get("change_pct", 0.0)),
                    float(p.get("change_amt", 0.0)),
                    now,
                )
                for p in positions
            ],
        )


def get_positions(bot_id: str) -> List[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT symbol, qty, market_value, weight, change_pct, change_amt, updated_at"
            " FROM positions WHERE bot_id=? ORDER BY market_value DESC",
            (bot_id,),
        ).fetchall()
    return [dict(r) for r in rows]



def save_daily_allocations(bot_id: str, rows: List[dict]) -> None:
    with _lock, get_conn() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO daily_allocations (bot_id, date, data) VALUES (?,?,?)",
            [(bot_id, r["date"], r["data"]) for r in rows],
        )


def save_daily_allocation(bot_id: str, date: str, data: str) -> None:
    with _lock, get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO daily_allocations (bot_id, date, data) VALUES (?,?,?)",
            (bot_id, date, data),
        )


def get_daily_allocation(bot_id: str, date: str) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT data FROM daily_allocations WHERE bot_id=? AND date=?",
            (bot_id, date),
        ).fetchone()
    return row["data"] if row else None



def set_meta(key: str, value: str) -> None:
    with _lock, get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (key, value)
        )


def get_meta(key: str) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None
