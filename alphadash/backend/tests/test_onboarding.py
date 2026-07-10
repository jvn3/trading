"""S3.1 onboarding tests: deterministic answer→profile mapping, provisioning, API flow."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from alphadash.config import Settings
from alphadash.db.base import Base
from alphadash.db.models import JournalEntry, RiskProfile, RiskProfileName, User
from alphadash.main import create_app
from alphadash.services import auth as auth_service
from alphadash.services.onboarding import (
    PROFILE_PRESETS,
    OnboardingError,
    apply_onboarding,
    recommend_profile,
)
from tests.factories import make_engine

NOW = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)


# --- mapping (pure) ---


@pytest.mark.parametrize(
    ("experience", "drop_reaction", "goal", "expected"),
    [
        # score 0 and 1 → conservative
        ("new", "sell", "preserve", RiskProfileName.conservative),
        ("new", "sell", "learn", RiskProfileName.conservative),
        ("some", "sell", "preserve", RiskProfileName.conservative),
        # scores 2–4 → balanced
        ("new", "wait", "learn", RiskProfileName.balanced),
        ("some", "wait", "learn", RiskProfileName.balanced),
        ("confident", "wait", "learn", RiskProfileName.balanced),
        ("new", "buy_more", "grow", RiskProfileName.balanced),
        # scores 5–6 → curious
        ("confident", "buy_more", "learn", RiskProfileName.curious),
        ("confident", "buy_more", "grow", RiskProfileName.curious),
    ],
)
def test_recommend_profile_bands(experience, drop_reaction, goal, expected) -> None:
    assert recommend_profile(experience, drop_reaction, goal) is expected


def test_recommend_profile_rejects_unknown_answers() -> None:
    with pytest.raises(OnboardingError, match="experience"):
        recommend_profile("expert", "wait", "learn")
    with pytest.raises(OnboardingError, match="drop_reaction"):
        recommend_profile("new", "panic", "learn")
    with pytest.raises(OnboardingError, match="goal"):
        recommend_profile("new", "wait", "moon")


def test_conservative_preset_is_strictly_tighter_than_curious() -> None:
    cons = PROFILE_PRESETS[RiskProfileName.conservative]
    cur = PROFILE_PRESETS[RiskProfileName.curious]
    assert cons["max_position_pct"] < cur["max_position_pct"]
    assert cons["max_trades_per_week"] < cur["max_trades_per_week"]
    assert cons["cash_floor_pct"] > cur["cash_floor_pct"]
    assert cons["per_suggestion_max_pct"] < cur["per_suggestion_max_pct"]
    assert cons["drawdown_pause_pct"] < cur["drawdown_pause_pct"]


# --- service (DB) ---


def test_apply_onboarding_rewrites_profile_and_marks_user() -> None:
    engine = make_engine()
    with Session(engine) as db:
        registered = auth_service.register_user(
            db, email="ob@example.com", password="long-enough-pass", display_name="OB"
        )
        user, account = registered.user, registered.account
        assert user.onboarded_at is None
        assert registered.profile.name is RiskProfileName.balanced

        result = apply_onboarding(
            db,
            user=user,
            account=account,
            experience="new",
            drop_reaction="sell",
            goal="preserve",
            now=NOW,
        )
        assert result.profile_name is RiskProfileName.conservative
        assert user.onboarded_at == NOW

        profile = db.scalar(select(RiskProfile).where(RiskProfile.user_id == user.id))
        assert profile.name is RiskProfileName.conservative
        assert profile.max_position_pct == Decimal("5")
        assert profile.max_asset_class_pct["crypto"] == 0

        notes = db.scalars(select(JournalEntry).where(JournalEntry.account_id == account.id)).all()
        payloads = [n.payload for n in notes if n.payload.get("event") == "onboarding"]
        assert payloads and payloads[0]["profile"] == "conservative"


def test_apply_onboarding_can_be_re_run() -> None:
    engine = make_engine()
    with Session(engine) as db:
        registered = auth_service.register_user(
            db, email="ob2@example.com", password="long-enough-pass", display_name="OB"
        )
        apply_onboarding(
            db,
            user=registered.user,
            account=registered.account,
            experience="new",
            drop_reaction="sell",
            goal="preserve",
            now=NOW,
        )
        result = apply_onboarding(
            db,
            user=registered.user,
            account=registered.account,
            experience="confident",
            drop_reaction="buy_more",
            goal="grow",
            now=NOW,
        )
        assert result.profile_name is RiskProfileName.curious
        # Still exactly one profile row — rewritten in place, not accumulated.
        profiles = db.scalars(
            select(RiskProfile).where(RiskProfile.user_id == registered.user.id)
        ).all()
        assert len(profiles) == 1


# --- API ---

CREDS = {"email": "wiz@example.com", "password": "correct-horse-battery", "display_name": "W"}


@pytest.fixture()
def client(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/ob.db", providers="stub", llm_provider="fake"
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as c:
        c.post("/auth/register", json=CREDS)
        yield c


def test_onboarding_api_flow(client) -> None:
    # Fresh registration: not onboarded, presets exposed for the wizard's teaching copy
    status = client.get("/onboarding").json()
    assert status["onboarded"] is False
    assert set(status["profiles"]) == {"conservative", "balanced", "curious"}
    assert status["profiles"]["conservative"]["max_position_pct"] == "5"

    me = client.get("/auth/me").json()
    assert me["onboarded"] is False

    r = client.post(
        "/onboarding",
        json={"experience": "new", "drop_reaction": "sell", "goal": "preserve"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["profile"] == "conservative"
    assert body["onboarded"] is True

    assert client.get("/auth/me").json()["onboarded"] is True
    assert client.get("/onboarding").json()["onboarded"] is True

    # The applied limits are now the account's effective limits
    limits = client.get("/account/limits").json()
    assert Decimal(limits["max_position_pct"]) == Decimal("5")
    assert limits["max_trades_per_week"] == 2


def test_onboarding_api_rejects_bad_answers(client) -> None:
    r = client.post(
        "/onboarding", json={"experience": "guru", "drop_reaction": "sell", "goal": "learn"}
    )
    assert r.status_code == 422


def test_onboarding_requires_auth(tmp_path) -> None:
    settings = Settings(database_url=f"sqlite:///{tmp_path}/na.db", llm_provider="fake")
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as c:
        assert c.get("/onboarding").status_code == 401
        assert (
            c.post(
                "/onboarding",
                json={"experience": "new", "drop_reaction": "sell", "goal": "learn"},
            ).status_code
            == 401
        )


def test_user_model_onboarded_at_column_exists() -> None:
    assert hasattr(User, "onboarded_at")
