"""Data access layer.

Business code should not touch ``sqlalchemy`` directly — go through these
functions. Idempotent upserts live here so callers can re-run an ingestion
pass without worrying about duplicates.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from jay_trading.data import models
from jay_trading.data.db import session_scope

log = logging.getLogger(__name__)


@dataclass
class UpsertReport:
    inserted: int = 0
    updated: int = 0
    skipped: int = 0

    @property
    def total_seen(self) -> int:
        return self.inserted + self.updated + self.skipped


def upsert_disclosed_trades(rows: Iterable[dict[str, Any]]) -> UpsertReport:
    """Idempotently insert ``DisclosedTrade`` rows.

    Dedup is enforced by the unique index on ``dedup_key``; duplicates are
    counted as ``skipped`` rather than raising.
    """
    report = UpsertReport()
    with session_scope() as s:
        for row in rows:
            if not row.get("source") or not row.get("ticker") or not row.get("dedup_key"):
                report.skipped += 1
                continue
            stmt = sqlite_insert(models.DisclosedTrade).values(**row)
            stmt = stmt.on_conflict_do_nothing(index_elements=["dedup_key"])
            result = s.execute(stmt)
            if (result.rowcount or 0) > 0:
                report.inserted += 1
            else:
                report.skipped += 1
    return report


def recent_disclosed_trades(
    source: str | None = None,
    since: date | None = None,
    limit: int | None = None,
) -> list[models.DisclosedTrade]:
    with session_scope() as s:
        stmt = select(models.DisclosedTrade)
        if source:
            stmt = stmt.where(models.DisclosedTrade.source == source)
        if since:
            stmt = stmt.where(models.DisclosedTrade.filing_date >= since)
        stmt = stmt.order_by(models.DisclosedTrade.filing_date.desc())
        if limit:
            stmt = stmt.limit(limit)
        rows = list(s.scalars(stmt))
        # Detach so callers can use them outside the session
        for r in rows:
            s.expunge(r)
        return rows


def unique_tickers_traded_by(
    person_name: str, since_days: int = 180
) -> list[str]:
    since = date.today() - timedelta(days=since_days)
    with session_scope() as s:
        stmt = (
            select(models.DisclosedTrade.ticker)
            .where(models.DisclosedTrade.person_name == person_name)
            .where(models.DisclosedTrade.filing_date >= since)
            .distinct()
        )
        return list(s.scalars(stmt))


def count_by_source(since: date | None = None) -> dict[str, int]:
    """Return {source: row_count} optionally filtered by filing_date >= since."""
    from sqlalchemy import func

    with session_scope() as s:
        stmt = select(
            models.DisclosedTrade.source,
            func.count(models.DisclosedTrade.id),
        ).group_by(models.DisclosedTrade.source)
        if since:
            stmt = stmt.where(models.DisclosedTrade.filing_date >= since)
        return {src: int(n) for src, n in s.execute(stmt).all()}


def top_tickers(
    since: date | None = None, source: str | None = None, limit: int = 10
) -> list[tuple[str, int]]:
    from sqlalchemy import func

    with session_scope() as s:
        stmt = select(
            models.DisclosedTrade.ticker,
            func.count(models.DisclosedTrade.id).label("n"),
        ).group_by(models.DisclosedTrade.ticker)
        if since:
            stmt = stmt.where(models.DisclosedTrade.filing_date >= since)
        if source:
            stmt = stmt.where(models.DisclosedTrade.source == source)
        stmt = stmt.order_by(__import__("sqlalchemy").desc("n")).limit(limit)
        return [(t, int(n)) for t, n in s.execute(stmt).all()]


# -- Signal / order / risk helpers (minimal; expanded in later phases) -----


def record_signal(
    strategy_name: str,
    ticker: str,
    direction: str,
    score: float,
    rationale: dict[str, Any],
    session: Session | None = None,
) -> int:
    """Insert a Signal row, return its id."""
    def _do(s: Session) -> int:
        sig = models.Signal(
            strategy_name=strategy_name,
            ticker=ticker.upper(),
            direction=direction,
            score=float(score),
            rationale=rationale,
        )
        s.add(sig)
        s.flush()
        return int(sig.id)

    if session is not None:
        return _do(session)
    with session_scope() as s:
        return _do(s)


def record_risk_event(
    kind: str,
    reason: str,
    severity: str = "info",
    strategy_name: str | None = None,
    ticker: str | None = None,
    payload: dict[str, Any] | None = None,
) -> int:
    with session_scope() as s:
        ev = models.RiskEvent(
            kind=kind,
            reason=reason,
            severity=severity,
            strategy_name=strategy_name,
            ticker=ticker,
            payload=payload or {},
        )
        s.add(ev)
        s.flush()
        return int(ev.id)
