"""Effective risk limits + pause state (S1.9 plumbing).

Limits come from the user's ``risk_profiles`` row. The kill switch (S1.10 shell / S3.6 settings)
is modeled with ``risk_events`` of type ``auto_pause`` carrying ``detail.action`` = "pause" |
"resume" — the frozen schema has no paused column, and an auditable event trail is better anyway.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from alphadash.db.models import (
    Account,
    JournalEntryType,
    RiskEvent,
    RiskEventType,
    RiskProfile,
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


def is_paused(session: Session, account: Account) -> bool:
    latest = session.scalar(
        select(RiskEvent)
        .where(
            RiskEvent.account_id == account.id,
            RiskEvent.event_type == RiskEventType.auto_pause,
        )
        .order_by(RiskEvent.created_at.desc(), RiskEvent.id.desc())
    )
    return bool(latest and latest.detail.get("action") == "pause")


def set_paused(session: Session, account: Account, *, paused: bool, by: str) -> RiskEvent:
    event = RiskEvent(
        account_id=account.id,
        event_type=RiskEventType.auto_pause,
        detail={"action": "pause" if paused else "resume", "by": by},
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
