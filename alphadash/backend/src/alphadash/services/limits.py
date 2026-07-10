"""Effective risk limits + pause state (S1.9 plumbing).

Limits come from the user's ``risk_profiles`` row. The kill switch (S1.10 shell / S3.6 settings)
is modeled with ``risk_events`` of type ``auto_pause`` carrying ``detail.action`` = "pause" |
"resume" — the frozen schema has no paused column, and an auditable event trail is better anyway.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from alphadash.db.models import (
    Account,
    JournalEntryType,
    RiskEvent,
    RiskEventType,
    RiskProfile,
    RiskProfileName,
)
from alphadash.domain.risk import RiskLimitSet
from alphadash.services import journal


def effective_limits(session: Session, user_id: str) -> RiskLimitSet:
    profile = session.scalar(
        select(RiskProfile)
        .where(RiskProfile.user_id == user_id)
        .order_by(RiskProfile.created_at.desc())
    )
    if profile is None:
        return RiskLimitSet()
    return RiskLimitSet(
        max_position_pct=profile.max_position_pct,
        max_asset_class_pct={
            k: Decimal(str(v)) for k, v in (profile.max_asset_class_pct or {}).items()
        },
        max_trades_per_week=profile.max_trades_per_week,
        cash_floor_pct=profile.cash_floor_pct,
        per_suggestion_max_pct=profile.per_suggestion_max_pct,
        drawdown_pause_pct=profile.drawdown_pause_pct,
    )


class LimitsError(ValueError):
    """Invalid limit values. Message is safe to show the user."""


@dataclass(frozen=True)
class LimitsUpdate:
    """Full replacement set for the six S1.3 limits (S3.6 settings)."""

    max_position_pct: Decimal
    max_asset_class_pct: dict[str, Decimal]  # keys: equity, crypto
    max_trades_per_week: int
    cash_floor_pct: Decimal
    per_suggestion_max_pct: Decimal
    drawdown_pause_pct: Decimal


_PCT_FIELDS = (
    "max_position_pct",
    "cash_floor_pct",
    "per_suggestion_max_pct",
    "drawdown_pause_pct",
)


def _validate(update: LimitsUpdate) -> None:
    for name in _PCT_FIELDS:
        value = getattr(update, name)
        if not (Decimal("0") <= value <= Decimal("100")):
            raise LimitsError(f"{name} must be between 0 and 100")
    if set(update.max_asset_class_pct) != {"equity", "crypto"}:
        raise LimitsError("max_asset_class_pct must have exactly the keys: equity, crypto")
    for cls, value in update.max_asset_class_pct.items():
        if not (Decimal("0") <= value <= Decimal("100")):
            raise LimitsError(f"max_asset_class_pct.{cls} must be between 0 and 100")
    if not (0 <= update.max_trades_per_week <= 100):
        raise LimitsError("max_trades_per_week must be between 0 and 100")


def _loosened_fields(profile: RiskProfile, update: LimitsUpdate) -> list[str]:
    """Which edits give the account MORE room? (higher caps, lower floors, later pause)."""
    loosened: list[str] = []
    if update.max_position_pct > profile.max_position_pct:
        loosened.append("max_position_pct")
    old_classes = {k: Decimal(str(v)) for k, v in (profile.max_asset_class_pct or {}).items()}
    for cls, value in update.max_asset_class_pct.items():
        if value > old_classes.get(cls, Decimal("0")):
            loosened.append(f"max_asset_class_pct.{cls}")
    if update.max_trades_per_week > profile.max_trades_per_week:
        loosened.append("max_trades_per_week")
    if update.cash_floor_pct < profile.cash_floor_pct:
        loosened.append("cash_floor_pct")
    if update.per_suggestion_max_pct > profile.per_suggestion_max_pct:
        loosened.append("per_suggestion_max_pct")
    if update.drawdown_pause_pct > profile.drawdown_pause_pct:
        loosened.append("drawdown_pause_pct")
    return loosened


def update_limits(
    session: Session,
    *,
    user_id: str,
    account: Account,
    update: LimitsUpdate,
    now: datetime | None = None,
) -> tuple[RiskProfile, list[str]]:
    """Apply edited limits to the user's profile (name → custom). Returns loosened field names.

    Loosening is allowed — this is the user's own paper account — but it is surfaced so the
    UI can teach about it, and it is journaled so the audit trail shows every safety change.
    """
    _validate(update)
    profile = session.scalar(
        select(RiskProfile)
        .where(RiskProfile.user_id == user_id)
        .order_by(RiskProfile.created_at.desc())
    )
    if profile is None:
        raise LimitsError("no risk profile provisioned for this user")

    loosened = _loosened_fields(profile, update)
    profile.name = RiskProfileName.custom
    profile.max_position_pct = update.max_position_pct
    profile.max_asset_class_pct = {k: str(v) for k, v in update.max_asset_class_pct.items()}
    profile.max_trades_per_week = update.max_trades_per_week
    profile.cash_floor_pct = update.cash_floor_pct
    profile.per_suggestion_max_pct = update.per_suggestion_max_pct
    profile.drawdown_pause_pct = update.drawdown_pause_pct
    session.flush()

    journal.record(
        session,
        account_id=account.id,
        entry_type=JournalEntryType.note,
        ref_id=profile.id,
        payload={
            "event": "limits_updated",
            "by": user_id,
            "at": (now or datetime.now(UTC)).isoformat(),
            "loosened": loosened,
            "limits": {
                "max_position_pct": str(update.max_position_pct),
                "max_asset_class_pct": {k: str(v) for k, v in update.max_asset_class_pct.items()},
                "max_trades_per_week": update.max_trades_per_week,
                "cash_floor_pct": str(update.cash_floor_pct),
                "per_suggestion_max_pct": str(update.per_suggestion_max_pct),
                "drawdown_pause_pct": str(update.drawdown_pause_pct),
            },
        },
    )
    return profile, loosened


def is_paused(session: Session, account: Account) -> bool:
    events = session.scalars(
        select(RiskEvent).where(
            RiskEvent.account_id == account.id,
            RiskEvent.event_type == RiskEventType.auto_pause,
        )
    ).all()
    if not events:
        return False
    # Order by the microsecond timestamp stamped into detail — created_at is second-precision
    # on sqlite, so rapid pause→resume pairs would otherwise tie and sort arbitrarily.
    latest = max(events, key=lambda e: e.detail.get("at") or e.created_at.isoformat())
    return latest.detail.get("action") == "pause"


def set_paused(
    session: Session, account: Account, *, paused: bool, by: str, now: datetime | None = None
) -> RiskEvent:
    stamp = (now or datetime.now(UTC)).isoformat()
    event = RiskEvent(
        account_id=account.id,
        event_type=RiskEventType.auto_pause,
        detail={"action": "pause" if paused else "resume", "by": by, "at": stamp},
    )
    session.add(event)
    session.flush()
    journal.record(
        session,
        account_id=account.id,
        entry_type=JournalEntryType.risk_event,
        ref_id=event.id,
        payload={"event": "pause" if paused else "resume", "by": by},
    )
    return event
