"""Decision journal + behavioral feedback endpoints (S3.4).

The journal is the S1.6 append-only audit trail, surfaced to its owner: every suggestion,
decision, order, fill and risk event. Nudges are computed fresh on every read — they describe
current behavior, so caching them would make them stale lies.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from alphadash.api.deps import get_current_user, get_tenant_db, now_utc
from alphadash.api.portfolio import get_account
from alphadash.api.schemas import JournalEntryOut, JournalOut, NudgeOut
from alphadash.db.models import Account, JournalEntry, User
from alphadash.services import behavior as behavior_service
from alphadash.services import limits as limits_service

router = APIRouter(tags=["journal"])


@router.get("/journal", response_model=JournalOut)
def read_journal(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_tenant_db),
    account: Account = Depends(get_account),
    user: User = Depends(get_current_user),
) -> JournalOut:
    entries = db.scalars(
        select(JournalEntry)
        .where(JournalEntry.account_id == account.id)
        .order_by(JournalEntry.created_at.desc(), JournalEntry.id.desc())
        .limit(limit)
    ).all()
    nudges = behavior_service.analyze(
        db,
        account=account,
        limits=limits_service.effective_limits(db, user.id),
        now=now_utc(),
    )
    return JournalOut(
        entries=[
            JournalEntryOut(
                id=e.id,
                entry_type=e.entry_type.value,
                ref_id=e.ref_id,
                payload=e.payload,
                created_at=e.created_at.isoformat(),
            )
            for e in entries
        ],
        nudges=[NudgeOut(kind=n.kind, severity=n.severity, message=n.message) for n in nudges],
    )
