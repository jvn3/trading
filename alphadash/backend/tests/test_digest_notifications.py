"""S3.2 tests: digest generation (idempotent per day), notifications feed, mark-read."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from alphadash.config import Settings
from alphadash.db.base import Base
from alphadash.db.models import EvidenceDoc, NotificationKind
from alphadash.main import create_app
from alphadash.services import auth as auth_service
from alphadash.services import notify as notify_service
from alphadash.services.digest import run_digest
from tests.factories import make_engine

NOW = datetime(2026, 7, 9, 13, 0, tzinfo=UTC)


class RecordingNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, *, user, title: str, body: str) -> None:
        self.sent.append((title, body))


@pytest.fixture()
def db_user_account():
    engine = make_engine()
    with Session(engine) as db:
        registered = auth_service.register_user(
            db, email="dg@example.com", password="long-enough-pass", display_name="D"
        )
        yield db, registered.user, registered.account


def test_digest_payload_sections_and_delivery(db_user_account) -> None:
    db, user, account = db_user_account
    db.add(
        EvidenceDoc(
            external_id="doc-1",
            doc_type="news",
            source="stub-news",
            symbols=["AAPL"],
            title="Apple services revenue climbs",
            body="Services grew again.",
            url=None,
            published_at=NOW - timedelta(hours=2),
        )
    )
    db.flush()

    notifier = RecordingNotifier()
    result = run_digest(db, user=user, account=account, prices={}, now=NOW, notifier=notifier)
    assert result.created is True
    payload = result.notification.payload
    assert payload["date"] == "2026-07-09"
    assert payload["read"][0]["title"] == "Apple services revenue climbs"
    assert payload["read"][0]["source"] == "stub-news"  # provenance survives
    assert Decimal(payload["what_changed"]["equity"]) == Decimal("10000")
    assert payload["suggestions"] == []
    assert "not investment advice" in payload["disclaimer"]
    assert result.notification.kind is NotificationKind.digest
    assert len(notifier.sent) == 1  # delivery stub invoked exactly once


def test_digest_idempotent_per_day_but_new_next_day(db_user_account) -> None:
    db, user, account = db_user_account
    first = run_digest(db, user=user, account=account, prices={}, now=NOW)
    again = run_digest(db, user=user, account=account, prices={}, now=NOW + timedelta(hours=5))
    assert again.created is False
    assert again.notification.id == first.notification.id

    tomorrow = run_digest(db, user=user, account=account, prices={}, now=NOW + timedelta(days=1))
    assert tomorrow.created is True
    assert tomorrow.notification.id != first.notification.id


def test_notifications_list_unread_and_mark_read(db_user_account) -> None:
    db, user, account = db_user_account
    n = run_digest(db, user=user, account=account, prices={}, now=NOW).notification
    assert [x.id for x in notify_service.list_notifications(db, user=user)] == [n.id]
    assert [x.id for x in notify_service.list_notifications(db, user=user, unread_only=True)] == [
        n.id
    ]

    notify_service.mark_read(db, user=user, notification_id=n.id, now=NOW)
    assert notify_service.list_notifications(db, user=user, unread_only=True) == []
    # Mark-read is idempotent and preserves the original timestamp
    first_read_at = n.read_at
    notify_service.mark_read(db, user=user, notification_id=n.id, now=NOW + timedelta(hours=1))
    assert n.read_at == first_read_at

    with pytest.raises(LookupError):
        notify_service.mark_read(db, user=user, notification_id="nope", now=NOW)


# --- API ---

CREDS = {"email": "feed@example.com", "password": "correct-horse-battery", "display_name": "F"}


@pytest.fixture()
def client(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/digest.db", providers="stub", llm_provider="fake"
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as c:
        c.post("/auth/register", json=CREDS)
        yield c


def test_digest_api_includes_open_suggestions_and_fills(client) -> None:
    # Agent run seeds evidence docs + suggestions; approving creates a fill.
    run = client.post("/agent/run").json()
    proposed = [s for s in run["suggestions"] if s["status"] == "proposed"]
    client.post(f"/suggestions/{proposed[0]['id']}/approve", json={})

    r = client.post("/digest/run")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] is True
    payload = body["notification"]["payload"]
    assert payload["read"], "agent-run ingestion should surface a today's read"
    assert payload["what_changed"]["fills_24h"], "approved trade must appear in what changed"
    remaining = {s["id"] for s in payload["suggestions"]}
    assert remaining == {s["id"] for s in proposed[1:]}

    # Same-day rerun replays the same digest
    again = client.post("/digest/run").json()
    assert again["created"] is False
    assert again["notification"]["id"] == body["notification"]["id"]

    # Feed + unread + mark read round trip
    feed = client.get("/notifications").json()
    assert [n["id"] for n in feed] == [body["notification"]["id"]]
    read = client.post(f"/notifications/{feed[0]['id']}/read").json()
    assert read["read_at"] is not None
    assert client.get("/notifications?unread_only=true").json() == []
    assert client.post("/notifications/zzz/read").status_code == 404


def test_notifications_require_auth(tmp_path) -> None:
    settings = Settings(database_url=f"sqlite:///{tmp_path}/na.db", llm_provider="fake")
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as c:
        assert c.post("/digest/run").status_code == 401
        assert c.get("/notifications").status_code == 401


def test_digest_equity_uses_prices(db_user_account) -> None:
    db, user, account = db_user_account
    payload = run_digest(
        db, user=user, account=account, prices={"AAPL": Decimal("200")}, now=NOW
    ).notification.payload
    # No positions yet — equity is all cash regardless of quotes
    assert Decimal(payload["what_changed"]["cash"]) == Decimal("10000")
