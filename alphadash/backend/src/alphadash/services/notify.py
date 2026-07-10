"""Notification delivery (S3.2).

The in-app feed is the ``notifications`` table (source of truth). Push/email delivery goes
through the ``Notifier`` protocol; the only implementation today is ``LogNotifier`` — a stub
that logs instead of sending (no SMTP/push credentials exist in this phase). Swapping in a real
adapter later changes delivery, not the data model.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.orm import Session

from alphadash.db.models import Notification, NotificationKind, User

log = logging.getLogger(__name__)


@runtime_checkable
class Notifier(Protocol):
    def send(self, *, user: User, title: str, body: str) -> None: ...


class LogNotifier:
    """Delivery stub: records the send in the app log. Honest placeholder, not a fake success."""

    def send(self, *, user: User, title: str, body: str) -> None:
        log.info("notify user=%s title=%r body=%r (log-only delivery)", user.id, title, body)


def create_notification(
    session: Session,
    *,
    user: User,
    kind: NotificationKind,
    title: str,
    body: str,
    payload: dict[str, Any],
    notifier: Notifier | None = None,
) -> Notification:
    notification = Notification(user_id=user.id, kind=kind, title=title, body=body, payload=payload)
    session.add(notification)
    session.flush()
    (notifier or LogNotifier()).send(user=user, title=title, body=body)
    return notification


def list_notifications(
    session: Session, *, user: User, unread_only: bool = False, limit: int = 50
) -> list[Notification]:
    stmt = (
        select(Notification)
        .where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    return list(session.scalars(stmt))


def mark_read(session: Session, *, user: User, notification_id: str, now: datetime) -> Notification:
    notification = session.scalar(
        select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user.id
        )
    )
    if notification is None:
        raise LookupError("notification not found")
    if notification.read_at is None:
        notification.read_at = now
        session.flush()
    return notification
