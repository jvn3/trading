"""S1.4 tests: exact sizing, cap selection, and the sized-order-always-validates property."""

from __future__ import annotations

from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from alphadash.db.models import AssetClass, OrderSide
from alphadash.domain.risk import (
    AccountState,
    OrderIntent,
    PositionState,
    RiskLimitSet,
    validate_order,
)
from alphadash.domain.sizing import size_buy, size_sell

D = Decimal


def account(**kw) -> AccountState:
    defaults = dict(
        equity=D("10000"),
        cash=D("5000"),
        positions={},
        trades_this_week=0,
        drawdown_pct=D("0"),
        paused=False,
    )
    defaults.update(kw)
    return AccountState(**defaults)


def pos(symbol: str, qty: str, value: str, asset_class=AssetClass.equity) -> PositionState:
    return PositionState(
        symbol=symbol, asset_class=asset_class, quantity=D(qty), market_value=D(value)
    )


# --- Exact-value cases ---


def test_target_pct_sizing_exact() -> None:
    r = size_buy(account(), RiskLimitSet(), "AAPL", AssetClass.equity, D("100"), target_pct=D("5"))
    assert r.qty == D("5")  # 5% of 10000 = 500 → 5 shares
    assert r.notional == D("500")
    assert r.binding_constraint == "target"
    assert not r.capped


def test_per_trade_cap_binds_before_target() -> None:
    limits = RiskLimitSet(per_suggestion_max_pct=D("3"))
    r = size_buy(account(), limits, "AAPL", AssetClass.equity, D("100"), target_pct=D("5"))
    assert r.notional == D("300")
    assert r.binding_constraint == "per-trade cap"
    assert r.capped


def test_position_cap_subtracts_existing_holding() -> None:
    state = account(positions={"AAPL": pos("AAPL", "6", "600")})
    limits = RiskLimitSet(max_position_pct=D("10"))
    r = size_buy(state, limits, "AAPL", AssetClass.equity, D("100"))
    assert r.notional == D("400")  # 1000 cap - 600 held
    assert r.binding_constraint == "position cap"


def test_cash_floor_limits_notional() -> None:
    limits = RiskLimitSet(cash_floor_pct=D("40"))  # floor = 4000, cash 5000 → max spend 1000
    r = size_buy(account(), limits, "AAPL", AssetClass.equity, D("100"))
    assert r.notional == D("1000")
    assert r.binding_constraint == "cash floor"


def test_asset_class_headroom() -> None:
    state = account(positions={"BTCUSD": pos("BTCUSD", "0.03", "2000", AssetClass.crypto)})
    limits = RiskLimitSet(max_asset_class_pct={"crypto": D("25")})
    r = size_buy(state, limits, "ETHUSD", AssetClass.crypto, D("100"))
    assert r.notional == D("500")  # 2500 cap - 2000 held
    assert r.binding_constraint == "asset-class cap"


def test_zero_when_paused_drawdown_or_weekly_cap() -> None:
    assert size_buy(account(paused=True), RiskLimitSet(), "A", AssetClass.equity, D("1")).qty == 0
    assert (
        size_buy(
            account(drawdown_pct=D("20")),
            RiskLimitSet(drawdown_pause_pct=D("15")),
            "A",
            AssetClass.equity,
            D("1"),
        ).qty
        == 0
    )
    assert (
        size_buy(
            account(trades_this_week=3),
            RiskLimitSet(max_trades_per_week=3),
            "A",
            AssetClass.equity,
            D("1"),
        ).qty
        == 0
    )


def test_fractional_quantization_rounds_down() -> None:
    r = size_buy(account(), RiskLimitSet(), "AAPL", AssetClass.equity, D("333"), target_pct=D("1"))
    # 100 / 333 = 0.3003003... → floored at 8dp
    assert r.qty == D("0.30030030")
    assert r.qty * D("333") <= D("100")


def test_size_sell_caps_at_held() -> None:
    state = account(positions={"AAPL": pos("AAPL", "5", "500")})
    r = size_sell(state, "AAPL", D("8"))
    assert r.qty == D("5") and r.capped and r.binding_constraint == "held quantity"
    assert size_sell(state, "MSFT", D("1")).qty == 0


# --- THE property: sized buys always pass the risk gate ---

pct = st.decimals(min_value="0.1", max_value="100", places=2)
opt_pct = st.none() | pct


@settings(max_examples=300, deadline=None)
@given(
    equity=st.decimals(min_value="100", max_value="1000000", places=2),
    cash_frac=st.decimals(min_value="0", max_value="1", places=4),
    price=st.decimals(min_value="0.01", max_value="100000", places=2),
    held_value=st.decimals(min_value="0", max_value="50000", places=2),
    max_position_pct=opt_pct,
    max_class_pct=opt_pct,
    cash_floor_pct=opt_pct,
    per_trade_pct=opt_pct,
    target_pct=opt_pct,
)
def test_property_sized_buy_always_validates(
    equity,
    cash_frac,
    price,
    held_value,
    max_position_pct,
    max_class_pct,
    cash_floor_pct,
    per_trade_pct,
    target_pct,
) -> None:
    cash = (equity * cash_frac).quantize(D("0.01"))
    positions = {}
    if held_value > 0:
        positions["AAPL"] = pos("AAPL", "1", str(held_value))
    state = account(equity=equity, cash=cash, positions=positions)
    limits = RiskLimitSet(
        max_position_pct=max_position_pct,
        max_asset_class_pct={"equity": max_class_pct} if max_class_pct is not None else {},
        cash_floor_pct=cash_floor_pct,
        per_suggestion_max_pct=per_trade_pct,
    )
    r = size_buy(state, limits, "AAPL", AssetClass.equity, price, target_pct=target_pct)
    if r.qty == 0:
        return
    intent = OrderIntent(
        symbol="AAPL", asset_class=AssetClass.equity, side=OrderSide.buy, qty=r.qty, price=price
    )
    decision = validate_order(intent, state, limits)
    assert decision.allow, f"sized order rejected: {decision.reason} (result={r})"
