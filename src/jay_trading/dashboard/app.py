"""FastAPI app. Localhost only, read-only.

Run with::

    uv run uvicorn jay_trading.dashboard.app:app --host 127.0.0.1 --port 8787
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from jay_trading.dashboard import data

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(
    title="Jay Trading Dashboard",
    description="Read-only operator view of the paper trading system.",
    version="0.1.0",
)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/snapshot")
def api_snapshot() -> dict:
    return data.snapshot()


@app.get("/api/account")
def api_account() -> dict:
    return data.account()


@app.get("/api/positions")
def api_positions() -> list[dict]:
    return data.positions()


@app.get("/api/orders")
def api_orders(days: int = 7) -> list[dict]:
    return data.orders(days=days)


@app.get("/api/signals")
def api_signals(limit: int = 40) -> list[dict]:
    return data.signals(limit=limit)


@app.get("/api/disclosures/counts")
def api_disclosure_counts() -> dict:
    return data.disclosures_counts()


@app.get("/api/disclosures/top")
def api_disclosure_top() -> list[dict]:
    return data.disclosures_top_tickers()


@app.get("/api/disclosures/recent")
def api_disclosure_recent(limit: int = 50) -> list[dict]:
    return data.recent_disclosures(limit=limit)


@app.get("/api/scheduler")
def api_scheduler() -> dict:
    return data.scheduler_health()


@app.get("/api/briefings")
def api_briefings() -> list[dict]:
    return data.briefings()


@app.get("/api/briefings/today", response_class=PlainTextResponse)
def api_today_briefing() -> str:
    md = data.today_briefing_markdown()
    return md or "_(no briefing yet today)_"


# Static assets (none at time of writing, but reserved for future CSS/JS splits)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
