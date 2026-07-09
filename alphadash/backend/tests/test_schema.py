"""S0.2 schema tests: table set, column typing rules, unique + FK constraints."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import DateTime, Float, Numeric, create_engine, event, insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alphadash.db import models
from alphadash.db.base import Base, new_id

EXPECTED_TABLES = {
    "auth_sessions",  # S1.8 schema extension
    "evidence_docs",  # S2.2 schema extension
    "users",
    "risk_profiles",
    "accounts",
    "cash_balances",
    "positions",
    "orders",
    "fills",
    "suggestions",
    "decisions",
    "risk_limits",
    "risk_events",
    "journal_entries",
    "watchlists",
    "watchlist_items",
    "agent_runs",
    "data_snapshots",
}

# Every column that holds money or a quantity — all must be Numeric(24, 8).
MONEY_COLUMNS = {
    ("risk_profiles", "max_position_pct"),
    ("risk_profiles", "cash_floor_pct"),
    ("risk_profiles", "per_suggestion_max_pct"),
    ("risk_profiles", "drawdown_pause_pct"),
    ("accounts", "starting_equity"),
    ("cash_balances", "amount"),
    ("positions", "quantity"),
    ("positions", "avg_cost"),
    ("orders", "qty"),
    ("orders", "limit_price"),
    ("fills", "qty"),
    ("fills", "price"),
    ("fills", "fee"),
    ("suggestions", "confidence"),
    ("risk_limits", "value"),
}


@pytest.fixture()
def engine():
    eng = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def session(engine):
    with Session(engine) as s:
        yield s


def _user(s: Session) -> models.User:
    u = models.User(email=f"{new_id()}@example.com", display_name="Test User")
    s.add(u)
    s.flush()
    return u


def _account(s: Session, user: models.User) -> models.Account:
    a = models.Account(user_id=user.id, starting_equity=Decimal("10000"))
    s.add(a)
    s.flush()
    return a


def test_metadata_yields_exact_table_set() -> None:
    assert set(Base.metadata.tables.keys()) == EXPECTED_TABLES


def test_no_float_columns_and_money_is_numeric_24_8() -> None:
    for table in Base.metadata.tables.values():
        for col in table.columns:
            assert not isinstance(col.type, Float), f"{table.name}.{col.name} is Float"
    for table_name, col_name in MONEY_COLUMNS:
        col = Base.metadata.tables[table_name].columns[col_name]
        assert isinstance(col.type, Numeric), f"{table_name}.{col_name} not Numeric"
        assert (col.type.precision, col.type.scale) == (24, 8)


def test_timestamps_tz_aware_and_pk_is_uuid_hex(session: Session) -> None:
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, DateTime):
                assert col.type.timezone, f"{table.name}.{col.name} not tz-aware"
        assert list(table.primary_key.columns)[0].name == "id"

    user = _user(session)
    assert len(user.id) == 32
    int(user.id, 16)  # hex-parseable


def test_created_at_defaults_and_account_defaults(session: Session) -> None:
    user = _user(session)
    account = _account(session, user)
    session.commit()
    assert user.created_at is not None
    assert account.mode == models.AccountMode.paper
    assert account.base_currency == "USD"


def test_unique_email(session: Session) -> None:
    session.add(models.User(email="dup@example.com", display_name="A"))
    session.flush()
    session.add(models.User(email="dup@example.com", display_name="B"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_unique_position_per_account_symbol(session: Session) -> None:
    account = _account(session, _user(session))
    for _ in range(2):
        session.add(
            models.Position(
                account_id=account.id,
                symbol="AAPL",
                asset_class=models.AssetClass.equity,
                quantity=Decimal("1"),
                avg_cost=Decimal("100"),
            )
        )
    with pytest.raises(IntegrityError):
        session.flush()


def test_unique_cash_balance_per_account_currency(session: Session) -> None:
    account = _account(session, _user(session))
    for _ in range(2):
        session.add(models.CashBalance(account_id=account.id, currency="USD", amount=Decimal("1")))
    with pytest.raises(IntegrityError):
        session.flush()


def test_unique_watchlist_item(session: Session) -> None:
    user = _user(session)
    wl = models.Watchlist(user_id=user.id, name="Main")
    session.add(wl)
    session.flush()
    for _ in range(2):
        session.add(
            models.WatchlistItem(
                watchlist_id=wl.id, symbol="BTCUSD", asset_class=models.AssetClass.crypto
            )
        )
    with pytest.raises(IntegrityError):
        session.flush()


def _order_kwargs(account_id: str, key: str) -> dict:
    return dict(
        account_id=account_id,
        symbol="AAPL",
        asset_class=models.AssetClass.equity,
        side=models.OrderSide.buy,
        order_type=models.OrderType.market,
        qty=Decimal("1"),
        idempotency_key=key,
    )


def test_unique_idempotency_key(session: Session) -> None:
    account = _account(session, _user(session))
    session.add(models.Order(**_order_kwargs(account.id, "k1")))
    session.flush()
    session.add(models.Order(**_order_kwargs(account.id, "k1")))
    with pytest.raises(IntegrityError):
        session.flush()


def test_fk_rejects_orphan_rows(session: Session) -> None:
    session.add(
        models.CashBalance(account_id="no-such-account", currency="USD", amount=Decimal("1"))
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_fk_rejects_orphan_fill(session: Session) -> None:
    session.add(
        models.Fill(
            order_id="no-such-order",
            qty=Decimal("1"),
            price=Decimal("100"),
            fee=Decimal("0"),
            filled_at=datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_enum_rejects_invalid_member(engine) -> None:
    with Session(engine) as s:
        account = _account(s, _user(s))
        s.commit()
        with pytest.raises(Exception) as exc_info, s.begin_nested():
            s.execute(
                insert(models.RiskLimit.__table__).values(
                    id=new_id(),
                    account_id=account.id,
                    limit_type="not_a_limit",
                    value=Decimal("1"),
                )
            )
        assert "not_a_limit" in str(exc_info.value) or isinstance(exc_info.value, IntegrityError)


def test_agent_run_snapshot_cycle_insertable(session: Session) -> None:
    account = _account(session, _user(session))
    run = models.AgentRun(
        account_id=account.id,
        trigger=models.AgentRunTrigger.on_demand,
        prompt_version="p1",
        model_version="m1",
        started_at=datetime.now(UTC),
    )
    session.add(run)
    session.flush()
    snap = models.DataSnapshot(agent_run_id=run.id, payload={"quotes": []})
    session.add(snap)
    session.flush()
    run.input_snapshot_id = snap.id
    session.commit()
    assert run.input_snapshot_id == snap.id
