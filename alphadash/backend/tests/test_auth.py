"""S1.8 tests: auth flow, session lifecycle, and paper-account provisioning (sqlite)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from alphadash.config import Settings
from alphadash.db.base import Base
from alphadash.db.models import Account, CashBalance, RiskProfile, RiskProfileName
from alphadash.main import create_app
from alphadash.services import auth as auth_service

CREDS = {"email": "jay@example.com", "password": "correct-horse-battery", "display_name": "Jay"}


@pytest.fixture()
def client(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path}/auth.db", providers="stub")
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as c:
        yield c


def test_register_provisions_full_beginner_setup(client) -> None:
    r = client.post("/auth/register", json=CREDS)
    assert r.status_code == 201, r.text
    assert r.json()["email"] == "jay@example.com"
    assert "alphadash_session" in r.cookies

    with Session(client.app.state.engine) as db:
        account = db.scalar(select(Account))
        assert account.mode.value == "paper"
        assert account.starting_equity == Decimal("10000")
        cash = db.scalar(select(CashBalance))
        assert cash.amount == Decimal("10000") and cash.currency == "USD"
        profile = db.scalar(select(RiskProfile))
        assert profile.name is RiskProfileName.balanced
        assert profile.per_suggestion_max_pct == Decimal("5")

    me = client.get("/auth/me")
    assert me.status_code == 200 and me.json()["display_name"] == "Jay"


def test_duplicate_email_and_short_password_rejected(client) -> None:
    assert client.post("/auth/register", json=CREDS).status_code == 201
    assert client.post("/auth/register", json=CREDS).status_code == 400
    weak = {**CREDS, "email": "b@example.com", "password": "short"}
    assert client.post("/auth/register", json=weak).status_code == 422  # pydantic min_length


def test_login_wrong_password_401_generic_message(client) -> None:
    client.post("/auth/register", json=CREDS)
    r = client.post("/auth/login", json={"email": CREDS["email"], "password": "wrong-password-x"})
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid email or password"
    r2 = client.post("/auth/login", json={"email": "ghost@example.com", "password": "whatever-pw"})
    assert r2.json()["detail"] == "invalid email or password"  # no user-enumeration


def test_logout_revokes_session(client) -> None:
    client.post("/auth/register", json=CREDS)
    assert client.get("/auth/me").status_code == 200
    assert client.post("/auth/logout").status_code == 204
    assert client.get("/auth/me").status_code == 401


def test_me_without_cookie_401(client) -> None:
    assert client.get("/auth/me").status_code == 401


def test_expired_session_rejected(tmp_path) -> None:
    settings = Settings(database_url=f"sqlite:///{tmp_path}/exp.db")
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with Session(app.state.engine) as db:
        auth_service.register_user(db, **CREDS)
        _, token = auth_service.login(
            db, email=CREDS["email"], password=CREDS["password"], now=datetime.now(UTC)
        )
        db.commit()
        with pytest.raises(auth_service.AuthError, match="expired"):
            auth_service.resolve_session(
                db,
                token=token,
                now=datetime.now(UTC) + auth_service.SESSION_TTL + timedelta(seconds=1),
            )


def test_password_stored_hashed_never_plaintext(client) -> None:
    client.post("/auth/register", json=CREDS)
    with Session(client.app.state.engine) as db:
        from alphadash.db.models import User

        user = db.scalar(select(User))
        assert user.password_hash.startswith("$argon2id$")
        assert CREDS["password"] not in user.password_hash
