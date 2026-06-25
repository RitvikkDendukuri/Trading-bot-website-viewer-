# Trading Bot Viewer

Live paper-trading dashboard that hosts algorithmic trading bots, marks them to market every minute using Yahoo Finance data, and benchmarks everything against SPY.

First bot: **[Macro-Economic Sector Rotation](https://github.com/RitvikkDendukuri/Macro-Economic-Sector-Rotation-Trading-Bot)** — rotates sector ETFs by macro regime with daily rebalancing and volatility-targeted leverage.

## What it does

- **Live paper trading** — pulls 1-minute Yahoo prices every 60s compares it with alpaca data for the bot varifies they are the same, marks portfolios to market, no broker needed
- **Backtest seed** — chart starts at $100k on Jan 1 2026, live line continues seamlessly from there
- **SPY benchmark overlay** — equity chart with strategy vs SPY, dashed line for live portion
- **Click-to-inspect trades** — click any point on the chart to see what sectors were bought/sold that day and how each contributed
- **Risk metrics** — Sharpe, Sortino, Beta, Alpha, Calmar, Max Drawdown with SPY comparison and info tooltips
- **Self-healing** — if the server goes down mid-day, Yahoo serves full-day 1-min bars so missing minutes backfill automatically on restart
- **Minute today, hourly history** — current session at minute resolution, older days compressed to hourly
- **Regime detection** — automatically detects macro regime (Recovery, Crisis, Stagflation, etc.) and rotates accordingly


## Tech Stack

- **Backend:** FastAPI + SQLite (WAL mode) + background scheduler threads
- **Strategy:** Python port of the sector rotation model with daily regime detection
- **Data:** Yahoo Finance (daily for backtest, 1-min for live, 1-hour for history reconstruction)
- **Frontend:** Vanilla JS + Chart.js with zoom/pan, neo-brutalist UI
- **Deploy:** Docker, configured for Render (always-on instance + persistent disk)

## Run locally

```bash
cd platform
pip install -r requirements.txt
uvicorn app.main:app --port 8000
```

The backtest seeds automatically on first startup. Live trading starts on the next market session.


## Adding a bot

1. Create `app/bots/<name>/strategy.py` with `METADATA`, `run_backtest()`, `compute_live_targets()`, `latest_regime()`
2. Add the module path to `_BOT_MODULES` in `app/core/registry.py`

## Config

| Var | Default | What it does |
| --- | --- | --- |
| `POLL_SECONDS` | 60 | how often to pull prices |
| `SEED_START_DATE` | 2026-01-01 | backtest start |
| `SEED_INITIAL_CAPITAL` | 100000 | starting equity |
| `ALPACA_API_KEY` / `ALPACA_API_SECRET` | — | optional paper trading creds |

## Disclaimer

Educational/research project. Not financial advice. The strategy uses leverage up to 2x.
