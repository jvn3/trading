"""Daily digest (S3.2): today's read + what changed + open suggestions. Deterministic, no LLM.

One digest per user per calendar day (UTC), stored as a ``digest`` notification whose payload
is the structured document the frontend renders. Re-running on the same day returns the
existing digest untouched (idempotent), so a scheduler and the on-demand button can share the
same entry point.

Every fact in the digest is derived from persisted data (evidence docs, fills, risk events,
suggestions) with provenance — the digest teaches, it never speculates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from alphadash.db.models import (
    Account,
    EvidenceDoc,
    Fill,
    Notification,
    NotificationKind,
    Order,
    RiskEvent,
    Suggestion,
    SuggestionStatus,
    User,
)
from alphadash.services import notify
from alphadash.services import portfolio as portfolio_service

MAX_READ_ITEMS = 3
MAX_SUGGESTIONS = 3
CHANGE_WINDOW = timedelta(hours=24)


@dataclass(frozen=True)
class DigestResult:
    notification: Notification
    created: bool  # False when today's digest already existed


def _todays_digest(session: Session, user: User, day_iso: str) -> Notification | None:
    rows = session.scalars(
        select(Notification).where(
            Notification.user_id == user.id, Notification.kind == NotificationKind.digest
        )
    )
    for n in rows:
        if n.payload.get("date") == day_iso:
            return n
    return None


def _as_utc(dt: datetime, now: datetime) -> datetime:
    # sqlite round-trips tz-aware datetimes as naive; stored values are UTC by contract.
    return dt if dt.tzinfo else dt.replace(tzinfo=now.tzinfo)


def build_digest_payload(
    session: Session,
    *,
    account: Account,
    prices: dict[str, Decimal],
    now: datetime,
) -> dict[str, Any]:
    day_iso = now.date().isoformat()
    since = now - CHANGE_WINDOW

    # --- Today's read: freshest evidence docs, with provenance (source + published_at) ---
    docs = session.scalars(
        select(EvidenceDoc).order_by(EvidenceDoc.published_at.desc()).limit(MAX_READ_ITEMS)
    ).all()
    read = [
        {
            "title": d.title,
            "source": d.source,
            "published_at": _as_utc(d.published_at, now).isoformat(),
            "symbols": d.symbols,
            "url": d.url,
        }
        for d in docs
    ]

    # --- What changed in the last 24h: fills + risk events, plus current equity ---
    fills = session.execute(
        select(Fill, Order)
        .join(Order, Fill.order_id == Order.id)
        .where(Order.account_id == account.id)
        .order_by(Fill.filled_at.desc())
    ).all()
    recent_fills = [
        {
            "symbol": order.symbol,
            "side": order.side.value,
            "qty": str(fill.qty),
            "price": str(fill.price),
            "filled_at": _as_utc(fill.filled_at, now).isoformat(),
        }
        for fill, order in fills
        if _as_utc(fill.filled_at, now) >= since
    ]
    recent_events = [
        {"event_type": e.event_type.value, "detail": e.detail}
        for e in session.scalars(
            select(RiskEvent)
            .where(RiskEvent.account_id == account.id)
            .order_by(RiskEvent.created_at.desc())
        )
        if _as_utc(e.created_at, now) >= since
    ]
    snapshot = portfolio_service.portfolio_snapshot(session, account, prices=prices)

    # --- Open suggestions (0–3), headline only — details live on the Agent screen ---
    open_suggestions = session.scalars(
        select(Suggestion)
        .where(
            Suggestion.account_id == account.id,
            Suggestion.status == SuggestionStatus.proposed,
        )
        .order_by(Suggestion.created_at.desc())
        .limit(MAX_SUGGESTIONS)
    ).all()

    return {
        "date": day_iso,
        "read": read,
        "what_changed": {
            "equity": str(snapshot.equity),
            "cash": str(snapshot.cash),
            "fills_24h": recent_fills,
            "risk_events_24h": recent_events,
        },
        "suggestions": [
            {"id": s.id, "headline": s.headline, "confidence": str(s.confidence)}
            for s in open_suggestions
        ],
        "disclaimer": "Simulated paper account. Educational, not investment advice.",
    }


def run_digest(
    session: Session,
    *,
    user: User,
    account: Account,
    prices: dict[str, Decimal],
    now: datetime,
    notifier: notify.Notifier | None = None,
) -> DigestResult:
    day_iso = now.date().isoformat()
    existing = _todays_digest(session, user, day_iso)
    if existing is not None:
        return DigestResult(notification=existing, created=False)

    payload = build_digest_payload(session, account=account, prices=prices, now=now)
    n_suggestions = len(payload["suggestions"])
    n_fills = len(payload["what_changed"]["fills_24h"])
    equity = Decimal(payload["what_changed"]["equity"]).quantize(Decimal("0.01"))
    body = (
        f"Portfolio value ${equity} · "
        f"{n_fills} trade(s) in the last 24h · "
        f"{n_suggestions} open suggestion(s)."
    )
    notification = notify.create_notification(
        session,
        user=user,
        kind=NotificationKind.digest,
        title=f"Your {day_iso} digest",
        body=body,
        payload=payload,
        notifier=notifier,
    )
    return DigestResult(notification=notification, created=True)
