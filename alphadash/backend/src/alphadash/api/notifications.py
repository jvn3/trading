"""Digest + notifications endpoints (S3.2).

``POST /digest/run`` is the single generation entry point — a scheduler and the UI's refresh
button both call it; it is idempotent per user per UTC day. ``GET /notifications`` is the
in-app feed.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from alphadash.api.deps import get_current_user, get_tenant_db, now_utc
from alphadash.api.portfolio import _current_prices, get_account
from alphadash.api.schemas import DigestOut, NotificationOut
from alphadash.db.models import Account, Notification, User
from alphadash.services import digest as digest_service
from alphadash.services import notify as notify_service

router = APIRouter(tags=["notifications"])


def _notification_out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        kind=n.kind.value,
        title=n.title,
        body=n.body,
        payload=n.payload,
        created_at=n.created_at.isoformat(),
        read_at=n.read_at.isoformat() if n.read_at else None,
    )


@router.post("/digest/run", response_model=DigestOut)
def run_digest(
    request: Request,
    db: Session = Depends(get_tenant_db),
    account: Account = Depends(get_account),
    user: User = Depends(get_current_user),
) -> DigestOut:
    result = digest_service.run_digest(
        db,
        user=user,
        account=account,
        prices=_current_prices(request, db, account),
        now=now_utc(),
    )
    return DigestOut(notification=_notification_out(result.notification), created=result.created)


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
) -> list[NotificationOut]:
    rows = notify_service.list_notifications(db, user=user, unread_only=unread_only, limit=limit)
    return [_notification_out(n) for n in rows]


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def mark_read(
    notification_id: str,
    db: Session = Depends(get_tenant_db),
    user: User = Depends(get_current_user),
) -> NotificationOut:
    try:
        n = notify_service.mark_read(db, user=user, notification_id=notification_id, now=now_utc())
    except LookupError:
        raise HTTPException(status_code=404, detail="notification not found") from None
    return _notification_out(n)
