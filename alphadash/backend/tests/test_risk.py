"""S1.3 tests: every limit type enforced, boundary behavior, structural invariants, properties."""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from alphadash.db.models import AssetClass, OrderSide, RiskLimitType
from alphadash.domain.risk import (
    AccountState,
    Decision,
    OrderIntent,
    PositionState,
    RiskLimitSet,
    validate_order,
)

D = Decimal


def account(
    *,
    equity: str = "10000",
    cash: str = "5000",
    positions: dict[str, PositionState] | None = None,
    trades_this_week: int = 0,
    drawdown_pct: str = "0",
    paused: bool = False,
) -> AccountState:
    return AccountState(
        equity=D(equity),
        cash=D(cash),
        positions=positions or {},
        trades_this_week=trades_this_week,
        drawdown_pct=D(drawdown_pct),
        paused=paused,
    )


def buy(symbol: str = "AAPL", qty: str = "10", price: str = "100", asset_class=AssetClass.equity):
    return OrderIntent(
        symbol=symbol, asset_class=asset_class, side=OrderSide.buy, qty=D(qty), price=D(price)
    )


def sell(symbol: str = "AAPL", qty: str = "10", price: str = "100", asset_class=AssetClass.equity):
    return OrderIntent(
        symbol=symbol, asset_class=asset_class, side=OrderSide.sell, qty=D(qty), price=D(price)
    )


def pos(symbol: str, qty: str, value: str, asset_class=AssetClass.equity) -> PositionState:
    return PositionState(
        symbol=symbol, asset_class=asset_class, quantity=D(qty), market_value=D(value)
    )


def limit_types(decision: Decision) -> set[RiskLimitType | None]:
    return {v.limit_type for v in decision.violations}


# --- No limits configured: only structural invariants apply ---


def test_no_limits_buy_within_cash_allowed() -> None:
    d = validate_order(buy(qty="10", price="100"), account(cash="1000"), RiskLimitSet())
    assert d.allow and d.reason is None


def test_buy_exceeding_cash_rejected() -> None:
    d = validate_order(buy(qty="11", price="100"), account(cash="1000"), RiskLimitSet())
    assert not d.allow
    assert "cash" in d.reason


def test_sell_more_than_held_rejected_no_shorting() -> None:
    state = account(positions={"AAPL": pos("AAPL", "5", "500")})
    d = validate_order(sell(qty="6"), state, RiskLimitSet())
    assert not d.allow
    assert "shorting" in d.reason
    assert validate_order(sell(qty="5"), state, RiskLimitSet()).allow


def test_nonpositive_qty_or_price_rejected() -> None:
    assert not validate_order(buy(qty="0"), account(), RiskLimitSet()).allow
    assert not validate_order(buy(price="0"), account(), RiskLimitSet()).allow
    assert not validate_order(sell(qty="-1"), account(), RiskLimitSet()).allow


# --- max_position_pct ---


def test_max_position_pct_boundary() -> None:
    limits = RiskLimitSet(max_position_pct=D("10"))
    # 10 sh × 100 = 1000 = exactly 10% of 10000 → allowed (≤)
    assert validate_order(buy(qty="10", price="100"), account(), limits).allow
    d = validate_order(buy(qty="10.01", price="100"), account(), limits)
    assert not d.allow and RiskLimitType.max_position_pct in limit_types(d)


def test_max_position_pct_counts_existing_position() -> None:
    state = account(positions={"AAPL": pos("AAPL", "5", "600")})
    limits = RiskLimitSet(max_position_pct=D("10"))
    d = validate_order(buy(qty="5", price="100"), state, limits)  # 600 + 500 = 11%
    assert not d.allow and RiskLimitType.max_position_pct in limit_types(d)


# --- max_asset_class_pct ---


def test_asset_class_cap_per_class() -> None:
    limits = RiskLimitSet(max_asset_class_pct={"crypto": D("25"), "equity": D("80")})
    state = account(positions={"BTCUSD": pos("BTCUSD", "0.03", "2000", AssetClass.crypto)})
    # crypto 2000 + 600 = 26% > 25
    d = validate_order(
        buy("ETHUSD", qty="1", price="600", asset_class=AssetClass.crypto), state, limits
    )
    assert not d.allow and RiskLimitType.max_asset_class_pct in limit_types(d)
    # equity buy unaffected by crypto cap
    assert validate_order(buy(qty="5", price="100"), state, limits).allow


# --- max_trades_per_week ---


def test_trades_per_week_applies_to_sells_too() -> None:
    limits = RiskLimitSet(max_trades_per_week=3)
    state = account(trades_this_week=3, positions={"AAPL": pos("AAPL", "10", "1000")})
    d = validate_order(sell(qty="1"), state, limits)
    assert not d.allow and RiskLimitType.max_trades_per_week in limit_types(d)
    assert validate_order(
        sell(qty="1"),
        account(trades_this_week=2, positions={"AAPL": pos("AAPL", "10", "1000")}),
        limits,
    ).allow


# --- cash_floor_pct ---


def test_cash_floor_boundary() -> None:
    limits = RiskLimitSet(cash_floor_pct=D("20"))
    # cash 5000, buy 3000 → 2000 = exactly 20% of 10000 → allowed (≥)
    assert validate_order(buy(qty="30", price="100"), account(), limits).allow
    d = validate_order(buy(qty="30.01", price="100"), account(), limits)
    assert not d.allow and RiskLimitType.cash_floor_pct in limit_types(d)


# --- per_suggestion_max_pct ---


def test_per_suggestion_cap() -> None:
    limits = RiskLimitSet(per_suggestion_max_pct=D("5"))
    assert validate_order(buy(qty="5", price="100"), account(), limits).allow  # 5%
    d = validate_order(buy(qty="6", price="100"), account(), limits)
    assert not d.allow and RiskLimitType.per_suggestion_max_pct in limit_types(d)


# --- drawdown_pause_pct + paused flag ---


def test_drawdown_pause_blocks_buys_not_sells() -> None:
    limits = RiskLimitSet(drawdown_pause_pct=D("15"))
    state = account(drawdown_pct="15", positions={"AAPL": pos("AAPL", "10", "1000")})
    d = validate_order(buy(qty="1"), state, limits)
    assert not d.allow and RiskLimitType.drawdown_pause_pct in limit_types(d)
    assert validate_order(sell(qty="5"), state, limits).allow  # de-risking never trapped


def test_paused_account_blocks_buys_not_sells() -> None:
    state = account(paused=True, positions={"AAPL": pos("AAPL", "10", "1000")})
    assert not validate_order(buy(qty="1"), state, RiskLimitSet()).allow
    assert validate_order(sell(qty="5"), state, RiskLimitSet()).allow


# --- All violations reported (teaching, not just first-failure) ---


def test_all_violations_reported() -> None:
    limits = RiskLimitSet(
        max_position_pct=D("5"), per_suggestion_max_pct=D("5"), cash_floor_pct=D("45")
    )
    d = validate_order(buy(qty="10", price="100"), account(), limits)  # 10% breaches all three
    assert not d.allow
    assert limit_types(d) == {
        RiskLimitType.max_position_pct,
        RiskLimitType.per_suggestion_max_pct,
        RiskLimitType.cash_floor_pct,
    }
    assert d.reason.count(";") == 2


# --- Properties ---

money = st.decimals(min_value="0.01", max_value="1000000", places=2)
qty_st = st.decimals(min_value="0.00000001", max_value="100000", places=8)


@settings(max_examples=200, deadline=None)
@given(qty=qty_st, price=money, cash=money)
def test_property_allowed_buy_never_exceeds_cash(qty, price, cash) -> None:
    state = account(equity=str(cash), cash=str(cash))
    d = validate_order(buy(qty=str(qty), price=str(price)), state, RiskLimitSet())
    if d.allow:
        assert qty * price <= cash


@settings(max_examples=200, deadline=None)
@given(
    qty=qty_st,
    price=money,
    cap=st.decimals(min_value="1", max_value="100", places=2),
)
def test_property_allowed_buy_respects_per_suggestion_cap(qty, price, cap) -> None:
    equity = D("100000")
    state = account(equity=str(equity), cash=str(equity))
    limits = RiskLimitSet(per_suggestion_max_pct=cap)
    d = validate_order(buy(qty=str(qty), price=str(price)), state, limits)
    if d.allow:
        assert (qty * price) / equity * 100 <= cap


@settings(max_examples=200, deadline=None)
@given(held=qty_st, ask=qty_st)
def test_property_never_short(held, ask) -> None:
    state = account(positions={"AAPL": pos("AAPL", str(held), "1000")})
    d = validate_order(sell(qty=str(ask), price="1"), state, RiskLimitSet())
    if d.allow:
        assert ask <= held
