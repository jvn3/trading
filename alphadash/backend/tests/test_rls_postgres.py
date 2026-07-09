"""S1.8 RLS tests against real Postgres (docker compose service).

Marked ``integration``: needs the alphadash-postgres container up and migrated. This is the test
that makes "tenant isolation" a physical fact rather than a code-review promise.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from alphadash.db.models import (
    Account,
    AssetClass,
    JournalEntry,
    Order,
    OrderSide,
    OrderType,
    Position,
)
from alphadash.domain.risk import RiskLimitSet
from alphadash.services import auth as auth_service
from alphadash.services.execution import place_order

PG_URL = "postgresql+psycopg://alphadash_app:alphadash_app_dev@localhost:5433/alphadash"

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def engine():
    eng = create_engine(PG_URL)
    try:
        with eng.connect() as conn:
            assert conn.scalar(text("SELECT 1")) == 1
    except Exception:
        pytest.skip("alphadash-postgres not reachable on :5433")
    yield eng
    eng.dispose()


@pytest.fixture()
def two_tenants(engine):
    """Two registered users, each with one filled trade. Cleaned up afterwards."""
    created = {}
    with Session(engine) as db:
        for who in ("alice", "bob"):
            reg = auth_service.register_user(
                db,
                email=f"{who}-rls@test.example",
                password="a-long-enough-pw",
                display_name=who,
            )
            db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": reg.user.id})
            place_order(
                db,
                account=reg.account,
                symbol="AAPL",
                asset_class=AssetClass.equity,
                side=OrderSide.buy,
                order_type=OrderType.market,
                qty=Decimal("1"),
                quote_price=Decimal("100"),
                limits=RiskLimitSet(),
                idempotency_key=f"rls-{who}",
                now=datetime.now(UTC),
            )
            created[who] = {"user_id": reg.user.id, "account_id": reg.account.id}
        db.commit()
    yield created
    with Session(engine) as db:  # cleanup (no app.user_id → need per-user context to delete)
        for who, ids in created.items():
            db.execute(
                text("SELECT set_config('app.user_id', :uid, true)"), {"uid": ids["user_id"]}
            )
            for table in (
                "journal_entries",
                "risk_events",
                "fills",
                "orders",
                "positions",
                "cash_balances",
                "risk_limits",
                "accounts",
                "risk_profiles",
            ):
                if table == "fills":
                    db.execute(text("DELETE FROM fills WHERE order_id IN (SELECT id FROM orders)"))
                elif table in ("accounts", "risk_profiles"):
                    db.execute(
                        text(f"DELETE FROM {table} WHERE user_id = :uid"), {"uid": ids["user_id"]}
                    )
                elif table == "journal_entries":
                    # journal is append-only at ORM level; raw SQL cleanup is test-fixture only
                    db.execute(
                        text("DELETE FROM journal_entries WHERE account_id = :aid"),
                        {"aid": ids["account_id"]},
                    )
                else:
                    db.execute(
                        text(f"DELETE FROM {table} WHERE account_id = :aid"),
                        {"aid": ids["account_id"]},
                    )
            db.commit()
        db.execute(text("DELETE FROM auth_sessions"))
        db.execute(text("DELETE FROM users WHERE email LIKE '%-rls@test.example'"))
        db.commit()


def _as(db: Session, user_id: str) -> None:
    db.execute(text("SELECT set_config('app.user_id', :uid, true)"), {"uid": user_id})


def test_cross_tenant_read_blocked(engine, two_tenants) -> None:
    alice, bob = two_tenants["alice"], two_tenants["bob"]
    with Session(engine) as db:
        _as(db, alice["user_id"])
        accounts = db.scalars(select(Account)).all()
        assert [a.id for a in accounts] == [alice["account_id"]]  # bob invisible

        positions = db.scalars(select(Position)).all()
        assert {p.account_id for p in positions} == {alice["account_id"]}

        orders = db.scalars(select(Order)).all()
        assert {o.account_id for o in orders} == {alice["account_id"]}

        journal = db.scalars(select(JournalEntry)).all()
        assert journal and {j.account_id for j in journal} == {alice["account_id"]}


def test_no_context_means_zero_rows(engine, two_tenants) -> None:
    with Session(engine) as db:  # app.user_id never set in this transaction
        assert db.scalars(select(Account)).all() == []
        assert db.scalars(select(Position)).all() == []
        assert db.scalars(select(JournalEntry)).all() == []


def test_cross_tenant_write_blocked_by_with_check(engine, two_tenants) -> None:
    alice, bob = two_tenants["alice"], two_tenants["bob"]
    with Session(engine) as db:
        _as(db, alice["user_id"])
        db.add(
            Position(
                account_id=bob["account_id"],  # forging a row into bob's account
                symbol="EVIL",
                asset_class=AssetClass.equity,
                quantity=Decimal("1"),
                avg_cost=Decimal("1"),
            )
        )
        with pytest.raises(ProgrammingError, match="row-level security"):
            db.flush()
        db.rollback()
