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


# -- Risk layer accessors (phase 3) ----------------------------------------


def record_equity_snapshot(equity: float, cash: float) -> int:
    """Append a daily equity snapshot, carrying the high-water-mark forward.

    On first insert, ``high_water_mark = equity``. On subsequent inserts,
    ``high_water_mark = max(prior_hwm, equity)``.
    """
    from sqlalchemy import func

    with session_scope() as s:
        prior_hwm = s.scalar(
            select(func.max(models.EquitySnapshot.high_water_mark))
        )
        hwm = max(float(equity), float(prior_hwm)) if prior_hwm is not None else float(equity)
        snap = models.EquitySnapshot(
            equity=float(equity), cash=float(cash), high_water_mark=hwm,
        )
        s.add(snap)
        s.flush()
        return int(snap.id)


def latest_equity_snapshot() -> models.EquitySnapshot | None:
    with session_scope() as s:
        row = s.scalar(
            select(models.EquitySnapshot).order_by(models.EquitySnapshot.ts.desc()).limit(1)
        )
        if row is not None:
            s.expunge(row)
        return row


def record_macro_regime_snapshot(
    *,
    regime: str,
    spy_score: float,
    vix_score: float,
    curve_score: float,
    raw_inputs: dict[str, Any] | None = None,
) -> int:
    """Append a :class:`MacroRegimeSnapshot` row.

    Called by the ``classify_macro_regime`` job once per morning. No
    deduplication — multiple snapshots per day are allowed (and useful if we
    ever add intraday re-classification).
    """
    with session_scope() as s:
        snap = models.MacroRegimeSnapshot(
            regime=regime,
            spy_score=float(spy_score),
            vix_score=float(vix_score),
            curve_score=float(curve_score),
            raw_inputs=raw_inputs or {},
        )
        s.add(snap)
        s.flush()
        return int(snap.id)


def latest_macro_regime() -> models.MacroRegimeSnapshot | None:
    """Most recent snapshot, or ``None`` if the classifier hasn't run yet."""
    with session_scope() as s:
        row = s.scalar(
            select(models.MacroRegimeSnapshot)
            .order_by(models.MacroRegimeSnapshot.ts.desc())
            .limit(1)
        )
        if row is not None:
            s.expunge(row)
        return row


def count_distinct_insider_buys(ticker: str, *, days: int = 30) -> int:
    """Count distinct insiders with at least one ``buy`` on ``ticker``
    in the last ``days``.

    Used by the cluster_detector's "insider confluence" multiplier (knob 3,
    2026-04-22): a congressional cluster gets a small score bump if real
    insider buy interest is concurrent on the same ticker. Buys only —
    ``exchange`` (option grants/exercises) and ``sell`` rows are noise here.
    """
    from datetime import date, timedelta
    from sqlalchemy import func

    if not ticker:
        return 0
    since = date.today() - timedelta(days=days)
    with session_scope() as s:
        n = s.scalar(
            select(func.count(func.distinct(models.DisclosedTrade.person_name)))
            .where(models.DisclosedTrade.source == "insider")
            .where(models.DisclosedTrade.ticker == ticker.upper())
            .where(models.DisclosedTrade.transaction_type == "buy")
            .where(models.DisclosedTrade.filing_date >= since)
        )
    return int(n or 0)


def record_api_call(
    provider: str,
    endpoint: str,
    status: str,
    latency_ms: float,
    error_kind: str | None = None,
) -> None:
    """Log one outbound API call. Best-effort — swallows DB errors.

    Keeping this non-raising is intentional: a DB hiccup during logging
    must not cascade into failing the actual FMP/Alpaca call.
    """
    try:
        with session_scope() as s:
            row = models.ApiCallLog(
                provider=provider,
                endpoint=endpoint[:128],
                status=status,
                latency_ms=float(latency_ms),
                error_kind=error_kind,
            )
            s.add(row)
    except Exception as e:  # noqa: BLE001
        log.debug("api_call_log write failed: %s", e)


def api_error_rate(provider: str, window_minutes: int = 30) -> tuple[int, int]:
    """Return ``(fail_count, total_count)`` for ``provider`` over the window."""
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import func

    since = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    with session_scope() as s:
        total = s.scalar(
            select(func.count(models.ApiCallLog.id))
            .where(models.ApiCallLog.provider == provider)
            .where(models.ApiCallLog.ts >= since)
        ) or 0
        fails = s.scalar(
            select(func.count(models.ApiCallLog.id))
            .where(models.ApiCallLog.provider == provider)
            .where(models.ApiCallLog.status == "fail")
            .where(models.ApiCallLog.ts >= since)
        ) or 0
        return int(fails), int(total)


def prune_api_call_log(older_than_days: int = 7) -> int:
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import delete

    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    with session_scope() as s:
        result = s.execute(
            delete(models.ApiCallLog).where(models.ApiCallLog.ts < cutoff)
        )
        return int(result.rowcount or 0)


def upsert_ticker_profile(
    ticker: str,
    sector: str | None,
    industry: str | None = None,
    market_cap: float | None = None,
) -> None:
    from datetime import datetime, timezone

    with session_scope() as s:
        existing = s.get(models.TickerProfile, ticker.upper())
        if existing is None:
            s.add(models.TickerProfile(
                ticker=ticker.upper(),
                sector=sector,
                industry=industry,
                market_cap=market_cap,
                last_refreshed=datetime.now(timezone.utc),
            ))
        else:
            existing.sector = sector
            existing.industry = industry
            existing.market_cap = market_cap
            existing.last_refreshed = datetime.now(timezone.utc)


def get_ticker_profile(ticker: str) -> models.TickerProfile | None:
    with session_scope() as s:
        row = s.get(models.TickerProfile, ticker.upper())
        if row is not None:
            s.expunge(row)
        return row


def sector_position_count(sector: str) -> int:
    """How many open Position rows are in the given sector (across strategies)?"""
    from sqlalchemy import func

    if not sector:
        return 0
    with session_scope() as s:
        count = s.scalar(
            select(func.count(models.Position.id))
            .join(
                models.TickerProfile,
                models.TickerProfile.ticker == models.Position.ticker,
            )
            .where(models.TickerProfile.sector == sector)
        ) or 0
        return int(count)
