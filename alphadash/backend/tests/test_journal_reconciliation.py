"""S1.6 tests: append-only journal enforcement + fill-replay reconciliation."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from alphadash.db.models import (
    AssetClass,
    CashBalance,
    JournalEntry,
    JournalEntryType,
    OrderSide,
    OrderType,
    Position,
    RiskEvent,
    RiskEventType,
)
from alphadash.domain.risk import RiskLimitSet
from alphadash.services import journal
from alphadash.services.execution import place_order
from alphadash.services.reconciliation import reconcile_account
from tests.factories import funded_account, make_engine

D = Decimal
NOW = datetime(2026, 7, 8, 15, 0, tzinfo=UTC)


@pytest.fixture()
def session():
    with Session(make_engine()) as s:
        yield s


def trade(session, account, *, side=OrderSide.buy, qty="10", price="100", key="k"):
    return place_order(
        session,
        account=account,
        symbol="AAPL",
        asset_class=AssetClass.equity,
        side=side,
        order_type=OrderType.market,
        qty=D(qty),
        quote_price=D(price),
        limits=RiskLimitSet(),
        idempotency_key=key,
        now=NOW,
    )


# --- Append-only journal ---


def test_journal_update_blocked(session) -> None:
    account = funded_account(session)
    entry = journal.record(
        session,
        account_id=account.id,
        entry_type=JournalEntryType.note,
        ref_id="x",
        payload={"note": "original"},
    )
    session.commit()

    entry.ref_id = "tampered"
    with pytest.raises(journal.JournalTamperError, match="append-only"):
        session.flush()
    session.rollback()


def test_journal_delete_blocked(session) -> None:
    account = funded_account(session)
    entry = journal.record(
        session,
        account_id=account.id,
        entry_type=JournalEntryType.note,
        ref_id="x",
        payload={},
    )
    session.commit()

    session.delete(entry)
    with pytest.raises(journal.JournalTamperError, match="append-only"):
        session.flush()
    session.rollback()
    assert session.scalar(select(JournalEntry)) is not None


# --- Reconciliation ---


def test_clean_account_reconciles_with_no_discrepancies(session) -> None:
    account = funded_account(session)
    trade(session, account, key="b1")
    trade(session, account, side=OrderSide.sell, qty="4", price="110", key="s1")
    session.commit()

    assert reconcile_account(session, account) == []
    assert session.scalar(select(RiskEvent)) is None


def test_position_tamper_detected(session) -> None:
    account = funded_account(session)
    trade(session, account, key="b1")
    position = session.scalar(select(Position))
    position.quantity = D("999")  # tamper
    session.commit()

    discrepancies = reconcile_account(session, account)
    session.commit()
    assert [d.kind for d in discrepancies] == ["position_qty"]
    assert discrepancies[0].expected == D("10") and discrepancies[0].actual == D("999")
    event = session.scalar(select(RiskEvent))
    assert event.event_type is RiskEventType.reconcile_discrepancy
    journaled = session.scalars(
        select(JournalEntry).where(JournalEntry.entry_type == JournalEntryType.risk_event)
    ).all()
    assert any(e.payload.get("event") == "reconcile_discrepancy" for e in journaled)


def test_cash_tamper_detected(session) -> None:
    account = funded_account(session)
    trade(session, account, key="b1")
    cash = session.scalar(select(CashBalance))
    cash.amount += D("123.45")
    session.commit()

    discrepancies = reconcile_account(session, account)
    assert [d.kind for d in discrepancies] == ["cash"]


def test_phantom_position_detected(session) -> None:
    account = funded_account(session)
    session.add(
        Position(
            account_id=account.id,
            symbol="GHOST",
            asset_class=AssetClass.equity,
            quantity=D("1"),
            avg_cost=D("1"),
        )
    )
    session.commit()

    discrepancies = reconcile_account(session, account)
    assert [d.kind for d in discrepancies] == ["unknown_position"]
