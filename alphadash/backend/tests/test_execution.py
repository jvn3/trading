"""S1.5 tests: fills with slippage, idempotency, risk veto, position/cash accounting."""

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
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    RiskEvent,
    RiskEventType,
)
from alphadash.domain.risk import RiskLimitSet
from alphadash.services.execution import SLIPPAGE_BPS, place_order
from tests.factories import funded_account, make_engine

D = Decimal
NOW = datetime(2026, 7, 8, 15, 0, tzinfo=UTC)


@pytest.fixture()
def session():
    with Session(make_engine()) as s:
        yield s


def market_buy(session, account, *, qty="10", price="100", key="k1", limits=None):
    return place_order(
        session,
        account=account,
        symbol="AAPL",
        asset_class=AssetClass.equity,
        side=OrderSide.buy,
        order_type=OrderType.market,
        qty=D(qty),
        quote_price=D(price),
        limits=limits or RiskLimitSet(),
        idempotency_key=key,
        now=NOW,
    )


def test_market_buy_fills_with_adverse_slippage(session) -> None:
    account = funded_account(session)
    result = market_buy(session, account)
    session.commit()

    assert result.order.status is OrderStatus.filled
    expected_price = (D("100") * (1 + SLIPPAGE_BPS / D("10000"))).quantize(D("0.01"))
    assert result.fill.price == expected_price == D("100.05")

    position = session.scalar(select(Position))
    assert position.quantity == D("10") and position.avg_cost == D("100.05")
    cash = session.scalar(select(CashBalance))
    assert cash.amount == D("10000") - D("10") * D("100.05")


def test_idempotency_key_dedupes(session) -> None:
    account = funded_account(session)
    first = market_buy(session, account, key="same")
    second = market_buy(session, account, key="same")
    session.commit()

    assert second.replayed and second.order.id == first.order.id
    assert session.scalar(select(Position)).quantity == D("10")  # applied once


def test_risk_veto_rejects_and_raises_risk_event(session) -> None:
    account = funded_account(session)
    limits = RiskLimitSet(per_suggestion_max_pct=D("5"))
    result = market_buy(session, account, qty="10", price="100", limits=limits)  # 10% > 5%
    session.commit()

    assert result.order.status is OrderStatus.rejected
    assert "per trade" in result.order.rejected_reason
    assert result.fill is None
    event = session.scalar(select(RiskEvent))
    assert event.event_type is RiskEventType.veto and event.order_id == result.order.id
    assert session.scalar(select(Position)) is None  # nothing applied


def test_marketable_limit_fills_never_above_limit(session) -> None:
    account = funded_account(session)
    result = place_order(
        session,
        account=account,
        symbol="AAPL",
        asset_class=AssetClass.equity,
        side=OrderSide.buy,
        order_type=OrderType.limit,
        qty=D("10"),
        quote_price=D("100"),
        limit_price=D("100.02"),  # marketable, but below slipped 100.05
        limits=RiskLimitSet(),
        idempotency_key="lim1",
        now=NOW,
    )
    assert result.order.status is OrderStatus.filled
    assert result.fill.price == D("100.02")  # clamped to limit


def test_non_marketable_limit_rejected_with_teaching_reason(session) -> None:
    account = funded_account(session)
    result = place_order(
        session,
        account=account,
        symbol="AAPL",
        asset_class=AssetClass.equity,
        side=OrderSide.buy,
        order_type=OrderType.limit,
        qty=D("10"),
        quote_price=D("100"),
        limit_price=D("95"),
        limits=RiskLimitSet(),
        idempotency_key="lim2",
        now=NOW,
    )
    assert result.order.status is OrderStatus.rejected
    assert "not marketable" in result.order.rejected_reason
    assert result.fill is None


def test_sell_roundtrip_updates_cash_and_closes_position(session) -> None:
    account = funded_account(session)
    market_buy(session, account, key="b1")
    result = place_order(
        session,
        account=account,
        symbol="AAPL",
        asset_class=AssetClass.equity,
        side=OrderSide.sell,
        order_type=OrderType.market,
        qty=D("10"),
        quote_price=D("110"),
        limits=RiskLimitSet(),
        idempotency_key="s1",
        now=NOW,
    )
    session.commit()

    sell_price = (D("110") * (1 - SLIPPAGE_BPS / D("10000"))).quantize(D("0.01"))
    assert result.fill.price == sell_price
    assert session.scalar(select(Position)) is None  # fully closed
    cash = session.scalar(select(CashBalance))
    assert cash.amount == D("10000") - D("10") * D("100.05") + D("10") * sell_price


def test_every_lifecycle_event_journaled(session) -> None:
    account = funded_account(session)
    market_buy(session, account, key="j1")
    market_buy(session, account, qty="10000", key="j2")  # veto: exceeds cash
    session.commit()

    entries = session.scalars(select(JournalEntry).order_by(JournalEntry.created_at)).all()
    kinds = [(e.entry_type.value, e.payload.get("event")) for e in entries]
    assert ("order", "submitted") in kinds
    assert ("fill", None) in kinds or any(k[0] == "fill" for k in kinds)
    assert ("risk_event", "veto") in kinds


def test_weekly_trade_cap_counts_fills(session) -> None:
    account = funded_account(session)
    limits = RiskLimitSet(max_trades_per_week=2)
    assert (
        market_buy(session, account, qty="1", key="w1", limits=limits).order.status
        is OrderStatus.filled
    )
    assert (
        market_buy(session, account, qty="1", key="w2", limits=limits).order.status
        is OrderStatus.filled
    )
    third = market_buy(session, account, qty="1", key="w3", limits=limits)
    assert third.order.status is OrderStatus.rejected
    assert "week" in third.order.rejected_reason
