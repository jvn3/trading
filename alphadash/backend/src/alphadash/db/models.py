"""All §9.4 entities as SQLAlchemy 2.0 typed models (S0.2 frozen contract).

16 tables. Money/quantities are ``Numeric(24, 8)`` (``MONEY``), timestamps tz-aware UTC, PKs are
uuid4 hex strings, enums are ``sa.Enum`` (non-native → CHECK constraints) with the exact members
from the frozen contract. Every user-owned row is reachable via ``user_id`` directly or through
its ``account``; physical RLS enforcement lands in S1.8.
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from alphadash.db.base import MONEY, Base, CreatedAtMixin, PkMixin, UpdatedAtMixin

# ---------------------------------------------------------------------------
# Enums (exact members from the frozen contract)
# ---------------------------------------------------------------------------


class RiskProfileName(enum.StrEnum):
    conservative = "conservative"
    balanced = "balanced"
    curious = "curious"
    custom = "custom"


class AccountMode(enum.StrEnum):
    paper = "paper"
    real = "real"


class AssetClass(enum.StrEnum):
    equity = "equity"
    crypto = "crypto"


class OrderSide(enum.StrEnum):
    buy = "buy"
    sell = "sell"


class OrderType(enum.StrEnum):
    market = "market"
    limit = "limit"


class OrderStatus(enum.StrEnum):
    pending = "pending"
    validated = "validated"
    rejected = "rejected"
    submitted = "submitted"
    filled = "filled"
    cancelled = "cancelled"


class SuggestionStatus(enum.StrEnum):
    proposed = "proposed"
    approved = "approved"
    modified = "modified"
    dismissed = "dismissed"
    expired = "expired"
    blocked = "blocked"


class DecisionAction(enum.StrEnum):
    approve = "approve"
    modify = "modify"
    dismiss = "dismiss"


class DecidedBy(enum.StrEnum):
    user = "user"
    auto = "auto"


class RiskLimitType(enum.StrEnum):
    max_position_pct = "max_position_pct"
    max_asset_class_pct = "max_asset_class_pct"
    max_trades_per_week = "max_trades_per_week"
    cash_floor_pct = "cash_floor_pct"
    per_suggestion_max_pct = "per_suggestion_max_pct"
    drawdown_pause_pct = "drawdown_pause_pct"


class RiskEventType(enum.StrEnum):
    breach = "breach"
    veto = "veto"
    auto_pause = "auto_pause"
    reconcile_discrepancy = "reconcile_discrepancy"


class JournalEntryType(enum.StrEnum):
    suggestion = "suggestion"
    decision = "decision"
    order = "order"
    fill = "fill"
    risk_event = "risk_event"
    note = "note"


class AgentRunTrigger(enum.StrEnum):
    scheduled = "scheduled"
    event = "event"
    on_demand = "on_demand"


class AgentRunStatus(enum.StrEnum):
    running = "running"
    completed = "completed"
    failed = "failed"


def _enum(enum_cls: type[enum.StrEnum], name: str) -> Enum:
    """Non-native enum → portable VARCHAR + CHECK constraint with stored *values*."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        validate_strings=True,
        values_callable=lambda e: [m.value for m in e],
    )


# ---------------------------------------------------------------------------
# Identity & configuration
# ---------------------------------------------------------------------------


class User(PkMixin, CreatedAtMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    # S1.8: argon2 hash. Nullable so pre-auth rows (tests/fixtures) stay valid; login requires it.
    password_hash: Mapped[str | None] = mapped_column(String(200), nullable=True)


class AuthSession(PkMixin, CreatedAtMixin, Base):
    """Server-side login session (S1.8). Stores only the token's SHA-256 — never the token."""

    __tablename__ = "auth_sessions"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RiskProfile(PkMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "risk_profiles"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[RiskProfileName] = mapped_column(
        _enum(RiskProfileName, "risk_profile_name"), nullable=False
    )
    max_position_pct: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    max_asset_class_pct: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    max_trades_per_week: Mapped[int] = mapped_column(Integer, nullable=False)
    cash_floor_pct: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    per_suggestion_max_pct: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    drawdown_pause_pct: Mapped[Decimal] = mapped_column(MONEY, nullable=False)


class Account(PkMixin, CreatedAtMixin, Base):
    __tablename__ = "accounts"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    mode: Mapped[AccountMode] = mapped_column(
        _enum(AccountMode, "account_mode"), nullable=False, default=AccountMode.paper
    )
    base_currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    starting_equity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)


# ---------------------------------------------------------------------------
# Portfolio state
# ---------------------------------------------------------------------------


class CashBalance(PkMixin, Base):
    __tablename__ = "cash_balances"
    __table_args__ = (UniqueConstraint("account_id", "currency"),)

    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)


class Position(PkMixin, UpdatedAtMixin, Base):
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("account_id", "symbol"),)

    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    asset_class: Mapped[AssetClass] = mapped_column(
        _enum(AssetClass, "asset_class"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    avg_cost: Mapped[Decimal] = mapped_column(MONEY, nullable=False)


# ---------------------------------------------------------------------------
# Order lifecycle
# ---------------------------------------------------------------------------


class Order(PkMixin, CreatedAtMixin, UpdatedAtMixin, Base):
    __tablename__ = "orders"

    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    asset_class: Mapped[AssetClass] = mapped_column(
        _enum(AssetClass, "asset_class"), nullable=False
    )
    side: Mapped[OrderSide] = mapped_column(_enum(OrderSide, "order_side"), nullable=False)
    order_type: Mapped[OrderType] = mapped_column(_enum(OrderType, "order_type"), nullable=False)
    qty: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    limit_price: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    status: Mapped[OrderStatus] = mapped_column(
        _enum(OrderStatus, "order_status"), nullable=False, default=OrderStatus.pending
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    rejected_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    suggestion_id: Mapped[str | None] = mapped_column(
        ForeignKey("suggestions.id", ondelete="SET NULL"), nullable=True
    )


class Fill(PkMixin, Base):
    __tablename__ = "fills"

    order_id: Mapped[str] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    qty: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    fee: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=Decimal("0"))
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# Agent output & human decisions
# ---------------------------------------------------------------------------


class Suggestion(PkMixin, CreatedAtMixin, Base):
    __tablename__ = "suggestions"

    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    headline: Mapped[str] = mapped_column(String(300), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    confidence_basis: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[SuggestionStatus] = mapped_column(
        _enum(SuggestionStatus, "suggestion_status"),
        nullable=False,
        default=SuggestionStatus.proposed,
    )
    falsifier: Mapped[str] = mapped_column(Text, nullable=False)
    reversibility: Mapped[str] = mapped_column(Text, nullable=False)
    sizing: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    worst_case: Mapped[str] = mapped_column(Text, nullable=False)
    blocked_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Decision(PkMixin, CreatedAtMixin, Base):
    __tablename__ = "decisions"

    suggestion_id: Mapped[str] = mapped_column(
        ForeignKey("suggestions.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[DecisionAction] = mapped_column(
        _enum(DecisionAction, "decision_action"), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    modified_sizing: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    decided_by: Mapped[DecidedBy] = mapped_column(_enum(DecidedBy, "decided_by"), nullable=False)


# ---------------------------------------------------------------------------
# Risk & audit
# ---------------------------------------------------------------------------


class RiskLimit(PkMixin, CreatedAtMixin, Base):
    __tablename__ = "risk_limits"

    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    limit_type: Mapped[RiskLimitType] = mapped_column(
        _enum(RiskLimitType, "risk_limit_type"), nullable=False
    )
    value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)


class RiskEvent(PkMixin, CreatedAtMixin, Base):
    __tablename__ = "risk_events"

    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[RiskEventType] = mapped_column(
        _enum(RiskEventType, "risk_event_type"), nullable=False
    )
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    order_id: Mapped[str | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )
    suggestion_id: Mapped[str | None] = mapped_column(
        ForeignKey("suggestions.id", ondelete="SET NULL"), nullable=True
    )


class JournalEntry(PkMixin, CreatedAtMixin, Base):
    """Append-only audit log. No update/delete code path may ever be written for this table."""

    __tablename__ = "journal_entries"

    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    entry_type: Mapped[JournalEntryType] = mapped_column(
        _enum(JournalEntryType, "journal_entry_type"), nullable=False
    )
    ref_id: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


# ---------------------------------------------------------------------------
# Watchlists
# ---------------------------------------------------------------------------


class Watchlist(PkMixin, CreatedAtMixin, Base):
    __tablename__ = "watchlists"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)


class WatchlistItem(PkMixin, Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (UniqueConstraint("watchlist_id", "symbol"),)

    watchlist_id: Mapped[str] = mapped_column(
        ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    asset_class: Mapped[AssetClass] = mapped_column(
        _enum(AssetClass, "asset_class"), nullable=False
    )


# ---------------------------------------------------------------------------
# Agent runs & data snapshots (mutually referencing; snapshot FK uses use_alter)
# ---------------------------------------------------------------------------


class AgentRun(PkMixin, Base):
    __tablename__ = "agent_runs"

    account_id: Mapped[str] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    trigger: Mapped[AgentRunTrigger] = mapped_column(
        _enum(AgentRunTrigger, "agent_run_trigger"), nullable=False
    )
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[AgentRunStatus] = mapped_column(
        _enum(AgentRunStatus, "agent_run_status"), nullable=False, default=AgentRunStatus.running
    )
    cost_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("data_snapshots.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DataSnapshot(PkMixin, CreatedAtMixin, Base):
    """Point-in-time agent inputs — the no-lookahead guarantee hangs off this table."""

    __tablename__ = "data_snapshots"

    agent_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
