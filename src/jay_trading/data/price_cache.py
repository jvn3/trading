"""Lightweight cache for FMP historical close prices.

The politician scorer needs one close price per (ticker, date); without caching
we'd re-hit FMP for every politician's every past trade on every run.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Column, Date, Float, String, UniqueConstraint
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from jay_trading.data.db import get_engine
from jay_trading.data.models import Base

log = logging.getLogger(__name__)


# Defined inline to avoid churning the main models module. Registered against
# the same Base so alembic picks it up on the next autogen.
class PriceBar(Base):  # type: ignore[misc]
    """Daily close cache for historical price lookups."""

    __tablename__ = "price_bars"
    ticker = Column(String(16), primary_key=True)
    bar_date = Column(Date, primary_key=True)
    close = Column(Float, nullable=False)
    adj_close = Column(Float, nullable=True)
    __table_args__ = (UniqueConstraint("ticker", "bar_date"),)


def _ensure_table() -> None:
    Base.metadata.create_all(get_engine(), tables=[PriceBar.__table__])


def upsert_bars(ticker: str, rows: list[dict[str, Any]]) -> int:
    """Insert ``rows`` (each {'date', 'close', 'adjClose'}) for ``ticker``.

    Idempotent.
    """
    _ensure_table()
    tickeru = ticker.upper()
    inserted = 0
    from jay_trading.data.db import session_scope

    with session_scope() as s:
        for r in rows:
            d = r.get("date")
            if isinstance(d, str):
                d = date.fromisoformat(d[:10])
            close = r.get("close")
            if d is None or close is None:
                continue
            stmt = sqlite_insert(PriceBar).values(
                ticker=tickeru,
                bar_date=d,
                close=float(close),
                adj_close=float(r["adjClose"]) if r.get("adjClose") is not None else None,
            )
            stmt = stmt.on_conflict_do_nothing(index_elements=["ticker", "bar_date"])
            result = s.execute(stmt)
            if (result.rowcount or 0) > 0:
                inserted += 1
    return inserted


def get_close_on_or_before(ticker: str, on: date) -> float | None:
    """Return the close for ``ticker`` on ``on``, or the nearest earlier trading day."""
    from sqlalchemy import select

    from jay_trading.data.db import session_scope

    _ensure_table()
    with session_scope() as s:
        stmt = (
            select(PriceBar.close)
            .where(PriceBar.ticker == ticker.upper())
            .where(PriceBar.bar_date <= on)
            .order_by(PriceBar.bar_date.desc())
            .limit(1)
        )
        row = s.execute(stmt).first()
        return float(row[0]) if row else None


def ensure_history(
    fmp: Any, ticker: str, start: date, end: date | None = None
) -> None:
    """Fetch and cache historical closes for ``ticker`` over [start, end]."""
    end = end or date.today()
    try:
        rows = fmp.historical_prices(ticker, from_=start - timedelta(days=5), to=end)
    except Exception as e:  # noqa: BLE001
        log.warning("historical prices failed for %s: %s", ticker, e)
        return
    upsert_bars(ticker, rows)
