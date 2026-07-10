"""S3.5 honest review + S3.6 editable limits tests (service boundaries + API)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from alphadash.config import Settings
from alphadash.db.base import Base
from alphadash.db.models import (
    AssetClass,
    Fill,
    JournalEntry,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    RiskProfileName,
)
from alphadash.main import create_app
from alphadash.services import auth as auth_service
from alphadash.services.limits import LimitsError, LimitsUpdate, update_limits
from alphadash.services.review import closed_trade_stats
from tests.factories import funded_account, make_engine

NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)


def _fill(db, account, *, symbol, side, qty, price, at) -> None:
    order = Order(
        account_id=account.id,
        symbol=symbol,
        asset_class=AssetClass.equity,
        side=side,
        order_type=OrderType.market,
        qty=Decimal(qty),
        status=OrderStatus.filled,
        idempotency_key=f"r-{symbol}-{side.value}-{at.isoformat()}",
    )
    db.add(order)
    db.flush()
    db.add(Fill(order_id=order.id, qty=Decimal(qty), price=Decimal(price), filled_at=at))
    db.flush()


# --- S3.5 closed-trade stats (hand-computed fixtures) ---


def test_closed_trade_stats_hand_computed() -> None:
    engine = make_engine()
    with Session(engine) as db:
        account = funded_account(db)
        t0 = NOW - timedelta(days=10)
        # Buy 10 @ 100, sell 5 @ 120 (win), sell 5 @ 90 (loss)
        _fill(db, account, symbol="AAPL", side=OrderSide.buy, qty="10", price="100", at=t0)
        _fill(
            db,
            account,
            symbol="AAPL",
            side=OrderSide.sell,
            qty="5",
            price="120",
            at=t0 + timedelta(days=1),
        )
        _fill(
            db,
            account,
            symbol="AAPL",
            side=OrderSide.sell,
            qty="5",
            price="90",
            at=t0 + timedelta(days=2),
        )
        stats = closed_trade_stats(db, account)
        assert (stats.closed_trades, stats.wins, stats.losses) == (2, 1, 1)
        assert stats.win_rate_pct == Decimal("50.00")
        assert stats.small_sample is True


def test_closed_trade_stats_empty_account() -> None:
    engine = make_engine()
    with Session(engine) as db:
        account = funded_account(db)
        stats = closed_trade_stats(db, account)
        assert stats.closed_trades == 0
        assert stats.win_rate_pct is None
        assert stats.small_sample is True


def test_break_even_sell_counts_as_loss() -> None:
    engine = make_engine()
    with Session(engine) as db:
        account = funded_account(db)
        t0 = NOW - timedelta(days=3)
        _fill(db, account, symbol="AAPL", side=OrderSide.buy, qty="1", price="100", at=t0)
        _fill(
            db,
            account,
            symbol="AAPL",
            side=OrderSide.sell,
            qty="1",
            price="100",
            at=t0 + timedelta(days=1),
        )
        stats = closed_trade_stats(db, account)
        assert (stats.wins, stats.losses) == (0, 1)


# --- S3.6 limits update (service) ---


def _update(**overrides) -> LimitsUpdate:
    base = dict(
        max_position_pct=Decimal("10"),
        max_asset_class_pct={"equity": Decimal("80"), "crypto": Decimal("10")},
        max_trades_per_week=5,
        cash_floor_pct=Decimal("10"),
        per_suggestion_max_pct=Decimal("5"),
        drawdown_pause_pct=Decimal("15"),
    )
    base.update(overrides)
    return LimitsUpdate(**base)


@pytest.fixture()
def db_registered():
    engine = make_engine()
    with Session(engine) as db:
        registered = auth_service.register_user(
            db, email="lim@example.com", password="long-enough-pass", display_name="L"
        )
        yield db, registered


def test_update_limits_sets_custom_and_journals(db_registered) -> None:
    db, registered = db_registered
    profile, loosened = update_limits(
        db,
        user_id=registered.user.id,
        account=registered.account,
        update=_update(max_position_pct=Decimal("8")),
        now=NOW,
    )
    assert profile.name is RiskProfileName.custom
    assert profile.max_position_pct == Decimal("8")
    assert loosened == []  # tightening only
    notes = [
        e.payload
        for e in db.scalars(
            select(JournalEntry).where(JournalEntry.account_id == registered.account.id)
        )
        if e.payload.get("event") == "limits_updated"
    ]
    assert notes and notes[0]["limits"]["max_position_pct"] == "8"


def test_update_limits_flags_every_loosened_field(db_registered) -> None:
    db, registered = db_registered
    _, loosened = update_limits(
        db,
        user_id=registered.user.id,
        account=registered.account,
        update=_update(
            max_position_pct=Decimal("20"),  # up from 10
            max_asset_class_pct={"equity": Decimal("90"), "crypto": Decimal("10")},  # equity up
            max_trades_per_week=8,  # up from 5
            cash_floor_pct=Decimal("5"),  # DOWN from 10 = looser
            drawdown_pause_pct=Decimal("25"),  # up from 15 = pauses later = looser
        ),
        now=NOW,
    )
    assert set(loosened) == {
        "max_position_pct",
        "max_asset_class_pct.equity",
        "max_trades_per_week",
        "cash_floor_pct",
        "drawdown_pause_pct",
    }


@pytest.mark.parametrize(
    "bad",
    [
        {"max_position_pct": Decimal("101")},
        {"max_position_pct": Decimal("-1")},
        {"cash_floor_pct": Decimal("120")},
        {"max_trades_per_week": 101},
        {"max_asset_class_pct": {"equity": Decimal("80")}},  # missing crypto key
        {"max_asset_class_pct": {"equity": Decimal("80"), "gold": Decimal("5")}},
    ],
)
def test_update_limits_validation(db_registered, bad) -> None:
    db, registered = db_registered
    with pytest.raises(LimitsError):
        update_limits(
            db,
            user_id=registered.user.id,
            account=registered.account,
            update=_update(**bad),
            now=NOW,
        )


# --- API ---

CREDS = {"email": "rv@example.com", "password": "correct-horse-battery", "display_name": "R"}


@pytest.fixture()
def client(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/rl.db", providers="stub", llm_provider="fake"
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as c:
        c.post("/auth/register", json=CREDS)
        yield c


VALID_LIMITS = {
    "max_position_pct": "12",
    "max_asset_class_pct": {"equity": "85", "crypto": "10"},
    "max_trades_per_week": 6,
    "cash_floor_pct": "10",
    "per_suggestion_max_pct": "5",
    "drawdown_pause_pct": "15",
}


def test_put_limits_persists_and_reports_loosened(client) -> None:
    r = client.put("/account/limits", json=VALID_LIMITS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["profile"] == "custom"
    assert set(body["loosened"]) == {
        "max_position_pct",
        "max_asset_class_pct.equity",
        "max_trades_per_week",
    }
    # Persisted: a fresh GET shows the new values
    limits = client.get("/account/limits").json()
    assert Decimal(limits["max_position_pct"]) == Decimal("12")
    assert limits["max_trades_per_week"] == 6


def test_put_limits_rejects_garbage(client) -> None:
    assert (
        client.put("/account/limits", json={**VALID_LIMITS, "max_position_pct": "wat"}).status_code
        == 422
    )
    assert (
        client.put("/account/limits", json={**VALID_LIMITS, "cash_floor_pct": "150"}).status_code
        == 422
    )


def test_pause_halts_automation_and_buys(client) -> None:
    """S3.6 acceptance: one-tap pause verifiably halts automation."""
    client.post("/account/pause")
    # Agent runs, but generates no buy suggestions while paused (S2.1 suppression)
    run = client.post("/agent/run").json()
    assert all(s["proposedOrder"]["side"] != "buy" for s in run["suggestions"])
    # And a manual buy is vetoed by the risk gate
    r = client.post(
        "/orders",
        json={
            "symbol": "AAPL",
            "asset_class": "equity",
            "side": "buy",
            "order_type": "market",
            "qty": "1",
        },
        headers={"Idempotency-Key": "paused-buy-1"},
    )
    body = r.json()
    assert body["order"]["status"] == "rejected"
    assert any("paused" in v["message"] for v in body["violations"])
    # Resume restores buying
    client.post("/account/resume")
    r2 = client.post(
        "/orders",
        json={
            "symbol": "AAPL",
            "asset_class": "equity",
            "side": "buy",
            "order_type": "market",
            "qty": "1",
        },
        headers={"Idempotency-Key": "resumed-buy-1"},
    )
    assert r2.json()["order"]["status"] == "filled"


def test_review_api_never_serves_naked_returns(client) -> None:
    run = client.post("/agent/run").json()
    target = next(s for s in run["suggestions"] if s["status"] == "proposed")
    client.post(f"/suggestions/{target['id']}/approve", json={})

    r = client.get("/portfolio/review")
    assert r.status_code == 200, r.text
    body = r.json()
    # Benchmark + drawdown ALWAYS ride along with the return
    perf = body["performance"]
    assert {
        "return_pct",
        "benchmark_return_pct",
        "max_drawdown_pct",
        "current_drawdown_pct",
    } <= set(perf)
    assert perf["benchmark_symbol"] == "SPY"
    assert body["verdict"]
    assert len(body["disclaimers"]) >= 3
    assert any("not investment advice" in d.lower() for d in body["disclaimers"])
    assert body["trades"]["small_sample"] is True


def test_review_requires_auth(tmp_path) -> None:
    settings = Settings(database_url=f"sqlite:///{tmp_path}/na.db", llm_provider="fake")
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as c:
        assert c.get("/portfolio/review").status_code == 401
        assert c.put("/account/limits", json=VALID_LIMITS).status_code == 401
