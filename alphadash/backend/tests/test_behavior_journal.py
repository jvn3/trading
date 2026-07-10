"""S3.4 tests: behavioral nudge rules (boundaries) + journal API with nudges."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from alphadash.config import Settings
from alphadash.db.base import Base
from alphadash.db.models import AssetClass, Fill, Order, OrderSide, OrderStatus, OrderType
from alphadash.domain.risk import RiskLimitSet
from alphadash.main import create_app
from alphadash.services.behavior import analyze
from tests.factories import funded_account, make_engine

# A Wednesday noon: week_start (Monday) is 2 days back, so same-week fills are unambiguous.
NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)
LIMITS = RiskLimitSet(max_trades_per_week=5)


def _fill(
    db: Session,
    account,
    *,
    symbol: str,
    side: OrderSide,
    qty: str,
    price: str,
    at: datetime,
) -> None:
    order = Order(
        account_id=account.id,
        symbol=symbol,
        asset_class=AssetClass.equity,
        side=side,
        order_type=OrderType.market,
        qty=Decimal(qty),
        status=OrderStatus.filled,
        idempotency_key=f"t-{symbol}-{side.value}-{at.isoformat()}",
    )
    db.add(order)
    db.flush()
    db.add(Fill(order_id=order.id, qty=Decimal(qty), price=Decimal(price), filled_at=at))
    db.flush()


@pytest.fixture()
def db_account():
    engine = make_engine()
    with Session(engine) as db:
        account = funded_account(db)
        yield db, account


def test_no_nudges_on_quiet_account(db_account) -> None:
    db, account = db_account
    assert analyze(db, account=account, limits=LIMITS, now=NOW) == []


def test_overtrading_info_at_80_pct_and_warn_at_limit(db_account) -> None:
    db, account = db_account
    for i in range(3):
        _fill(
            db,
            account,
            symbol="AAPL",
            side=OrderSide.buy,
            qty="1",
            price="10",
            at=NOW - timedelta(hours=10 - i),
        )
    # 3 of 5 = 60% — silent
    assert analyze(db, account=account, limits=LIMITS, now=NOW) == []

    _fill(db, account, symbol="AAPL", side=OrderSide.buy, qty="1", price="10", at=NOW)
    # 4 of 5 = 80% — info nudge
    nudges = analyze(db, account=account, limits=LIMITS, now=NOW)
    assert [(n.kind, n.severity) for n in nudges] == [("overtrading", "info")]

    _fill(
        db,
        account,
        symbol="AAPL",
        side=OrderSide.buy,
        qty="1",
        price="10",
        at=NOW + timedelta(minutes=1),
    )
    # 5 of 5 — warn
    nudges = analyze(db, account=account, limits=LIMITS, now=NOW)
    assert [(n.kind, n.severity) for n in nudges] == [("overtrading", "warn")]
    assert "5 of your 5" in nudges[0].message


def test_overtrading_ignores_last_weeks_fills(db_account) -> None:
    db, account = db_account
    for i in range(5):
        _fill(
            db,
            account,
            symbol="AAPL",
            side=OrderSide.buy,
            qty="1",
            price="10",
            at=NOW - timedelta(days=7, hours=i + 1),
        )
    assert analyze(db, account=account, limits=LIMITS, now=NOW) == []


def test_loss_chasing_buy_within_48h_of_loss_sell(db_account) -> None:
    db, account = db_account
    limits = RiskLimitSet()  # no trade cap — isolate the loss-chasing rule
    _fill(
        db,
        account,
        symbol="AAPL",
        side=OrderSide.buy,
        qty="10",
        price="100",
        at=NOW - timedelta(days=3),
    )
    _fill(
        db,
        account,
        symbol="AAPL",
        side=OrderSide.sell,
        qty="10",
        price="80",  # realized loss vs avg cost 100
        at=NOW - timedelta(hours=30),
    )
    _fill(
        db,
        account,
        symbol="MSFT",
        side=OrderSide.buy,
        qty="1",
        price="50",
        at=NOW - timedelta(hours=2),  # 28h after the loss sell — inside the window
    )
    nudges = analyze(db, account=account, limits=limits, now=NOW)
    assert [n.kind for n in nudges] == ["loss_chasing"]
    assert nudges[0].severity == "warn"


def test_no_loss_chasing_when_sell_was_profitable_or_buy_is_late(db_account) -> None:
    db, account = db_account
    limits = RiskLimitSet()
    _fill(
        db,
        account,
        symbol="AAPL",
        side=OrderSide.buy,
        qty="10",
        price="100",
        at=NOW - timedelta(days=10),
    )
    # Profitable sell → following buy is fine
    _fill(
        db,
        account,
        symbol="AAPL",
        side=OrderSide.sell,
        qty="5",
        price="120",
        at=NOW - timedelta(days=9),
    )
    _fill(
        db,
        account,
        symbol="MSFT",
        side=OrderSide.buy,
        qty="1",
        price="50",
        at=NOW - timedelta(days=9, hours=-1),
    )
    assert analyze(db, account=account, limits=limits, now=NOW) == []

    # Loss sell, but the next buy comes 3 days later — outside the 48h window
    _fill(
        db,
        account,
        symbol="AAPL",
        side=OrderSide.sell,
        qty="5",
        price="80",
        at=NOW - timedelta(days=5),
    )
    _fill(
        db,
        account,
        symbol="MSFT",
        side=OrderSide.buy,
        qty="1",
        price="50",
        at=NOW - timedelta(days=1),
    )
    assert analyze(db, account=account, limits=limits, now=NOW) == []


def test_stale_loss_chase_is_not_renagged(db_account) -> None:
    db, account = db_account
    limits = RiskLimitSet()
    long_ago = NOW - timedelta(days=30)
    _fill(db, account, symbol="AAPL", side=OrderSide.buy, qty="10", price="100", at=long_ago)
    _fill(
        db,
        account,
        symbol="AAPL",
        side=OrderSide.sell,
        qty="10",
        price="80",
        at=long_ago + timedelta(hours=1),
    )
    _fill(
        db,
        account,
        symbol="MSFT",
        side=OrderSide.buy,
        qty="1",
        price="50",
        at=long_ago + timedelta(hours=2),
    )
    assert analyze(db, account=account, limits=limits, now=NOW) == []


# --- API ---

CREDS = {"email": "jr@example.com", "password": "correct-horse-battery", "display_name": "J"}


@pytest.fixture()
def client(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/journal.db", providers="stub", llm_provider="fake"
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as c:
        c.post("/auth/register", json=CREDS)
        yield c


def test_journal_api_shows_decisions_and_orders(client) -> None:
    run = client.post("/agent/run").json()
    target = next(s for s in run["suggestions"] if s["status"] == "proposed")
    client.post(f"/suggestions/{target['id']}/dismiss", json={"reason": "not today"})

    body = client.get("/journal").json()
    types = {e["entry_type"] for e in body["entries"]}
    assert "suggestion" in types
    assert "decision" in types
    decision = next(e for e in body["entries"] if e["entry_type"] == "decision")
    assert decision["payload"]["action"] == "dismiss"
    assert decision["payload"]["reason"] == "not today"
    assert isinstance(body["nudges"], list)
    # Entries are newest-first
    stamps = [e["created_at"] for e in body["entries"]]
    assert stamps == sorted(stamps, reverse=True)


def test_journal_requires_auth(tmp_path) -> None:
    settings = Settings(database_url=f"sqlite:///{tmp_path}/na.db", llm_provider="fake")
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as c:
        assert c.get("/journal").status_code == 401
