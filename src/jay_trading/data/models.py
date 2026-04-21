"""SQLAlchemy 2.0 ORM models.

Schema covers:
- ``disclosed_trades``: raw STOCK Act + Form 4 rows ingested from FMP, with a
  uniqueness constraint that makes upserts idempotent.
- ``signals``: strategy output before any risk vetting.
- ``orders`` / ``fills``: our record of what we told Alpaca and what came back.
- ``positions``: mirror of Alpaca open positions + our metadata (strategy,
  entry signal).
- ``risk_events``: circuit-breaker trips, vetoes, and other anomalies.
- ``person_aliases``: name-canonicalizer helper (per Appendix C gotchas).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base for the project's ORM models."""


# --- Reference tables -------------------------------------------------------


class PersonAlias(Base):
    """Maps observed name variants to a canonical person.

    Example: "Pelosi, Nancy", "Nancy Pelosi", "Rep. Nancy Pelosi (D-CA)" all
    canonicalize to "Nancy Pelosi".
    """

    __tablename__ = "person_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    alias: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    canonical: Mapped[str] = mapped_column(String(256), index=True)
    source: Mapped[str] = mapped_column(String(32))  # "senate" | "house" | "insider"


# --- Disclosure ingest ------------------------------------------------------


class DisclosedTrade(Base):
    """Raw disclosed trade row: one politician/insider transaction as filed.

    Deduplication: SQL ``UniqueConstraint`` over columns that can be NULL
    (insider rows often have NULL amounts) does not deduplicate, because
    ``NULL != NULL``. And multi-line Form 4s share everything except an
    internal transaction index. So we compute an explicit ``dedup_key`` from
    the source-appropriate fields and unique-index that instead.
    """

    __tablename__ = "disclosed_trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16), index=True)  # senate | house | insider
    person_name: Mapped[str] = mapped_column(String(256), index=True)
    person_role: Mapped[str | None] = mapped_column(String(256), nullable=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    transaction_type: Mapped[str] = mapped_column(String(16))  # buy | sell | exchange
    transaction_date: Mapped[date] = mapped_column(Date, index=True)
    filing_date: Mapped[date] = mapped_column(Date, index=True)
    amount_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    amount_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    amount_exact: Mapped[float | None] = mapped_column(Float, nullable=True)
    dedup_key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


# --- Signals ---------------------------------------------------------------


class Signal(Base):
    """A strategy's observation that may or may not become a trade."""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_name: Mapped[str] = mapped_column(String(64), index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    direction: Mapped[str] = mapped_column(String(8))  # long | short | flat
    score: Mapped[float] = mapped_column(Float)
    rationale: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    acted_on: Mapped[bool] = mapped_column(Boolean, default=False)
    acted_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


# --- Orders & fills --------------------------------------------------------


class Order(Base):
    """Our record of every order submitted to Alpaca (shadow orders included)."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    strategy_name: Mapped[str] = mapped_column(String(64), index=True)
    signal_id: Mapped[int | None] = mapped_column(
        ForeignKey("signals.id"), nullable=True
    )
    client_order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    alpaca_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    ticker: Mapped[str] = mapped_column(String(16), index=True)
    side: Mapped[str] = mapped_column(String(8))  # buy | sell
    order_type: Mapped[str] = mapped_column(String(16))  # market | limit | stop
    qty: Mapped[float | None] = mapped_column(Float, nullable=True)
    notional: Mapped[float | None] = mapped_column(Float, nullable=True)
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_in_force: Mapped[str] = mapped_column(String(8), default="day")
    status: Mapped[str] = mapped_column(String(16), default="submitted")  # submitted/filled/cancelled/shadow
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    rationale_note_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    fills: Mapped[list["Fill"]] = relationship(back_populates="order")


class Fill(Base):
    """A fill reconciled from Alpaca back into our store."""

    __tablename__ = "fills"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    alpaca_fill_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    qty: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    order: Mapped[Order] = relationship(back_populates="fills")


# --- Positions & risk ------------------------------------------------------


class Position(Base):
    """Our view of an open position, joined with the strategy that opened it."""

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    strategy_name: Mapped[str] = mapped_column(String(64), index=True)
    entry_signal_id: Mapped[int | None] = mapped_column(
        ForeignKey("signals.id"), nullable=True
    )
    qty: Mapped[float] = mapped_column(Float)
    avg_entry_price: Mapped[float] = mapped_column(Float)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    hard_stop: Mapped[float | None] = mapped_column(Float, nullable=True)
    trail_peak: Mapped[float | None] = mapped_column(Float, nullable=True)
    trail_active: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(String(1024), nullable=True)


class RiskEvent(Base):
    """A circuit-breaker trip, a veto, a halt, anything the risk layer records."""

    __tablename__ = "risk_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # e.g. "veto", "breaker_trip"
    severity: Mapped[str] = mapped_column(String(16), default="info")  # info/warn/halt
    strategy_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ticker: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reason: Mapped[str] = mapped_column(String(1024))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


# --- Risk layer runtime state ---------------------------------------------


class EquitySnapshot(Base):
    """Daily snapshot of account equity used by the drawdown circuit breaker.

    One row per calendar day (the daily ``snapshot_equity_and_prune`` job
    writes it at 16:05 ET). ``high_water_mark`` is the max of all prior
    ``equity`` values, carried forward monotonically so the drawdown check
    has O(1) access.
    """

    __tablename__ = "equity_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    equity: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
    high_water_mark: Mapped[float] = mapped_column(Float)


class ApiCallLog(Base):
    """One row per outbound FMP / Alpaca call. Pruned to 7 days on the daily job.

    Used by the ``api_health`` pipeline gate to compute a rolling error rate
    without needing to hold state in the scheduler process (so a restart
    does not lose the window).
    """

    __tablename__ = "api_call_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    provider: Mapped[str] = mapped_column(String(16), index=True)  # "fmp" | "alpaca"
    endpoint: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(8), index=True)  # "ok" | "fail"
    latency_ms: Mapped[float] = mapped_column(Float)
    error_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)


class TickerProfile(Base):
    """Cached company metadata, primarily for the sector-correlation cap.

    Populated lazily by ``risk.guards.check_correlation_cap`` from FMP's
    ``/stable/profile?symbol=X`` response. Refreshed if ``last_refreshed``
    is older than 30 days.
    """

    __tablename__ = "ticker_profile"

    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    sector: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    industry: Mapped[str | None] = mapped_column(String(128), nullable=True)
    market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_refreshed: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class MacroRegimeSnapshot(Base):
    """One classification of the portfolio-wide macro regime (Strategy V).

    Written by the ``classify_macro_regime`` scheduled job (08:35 ET on
    weekdays) and read by the executor to apply a sizing multiplier to each
    strategy's intents. Component scores are kept so the dashboard and
    post-mortems can see *why* a given regime was picked without re-running
    the classifier.
    """

    __tablename__ = "macro_regime_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    regime: Mapped[str] = mapped_column(String(32), index=True)
    spy_score: Mapped[float] = mapped_column(Float)
    vix_score: Mapped[float] = mapped_column(Float)
    curve_score: Mapped[float] = mapped_column(Float)
    raw_inputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
