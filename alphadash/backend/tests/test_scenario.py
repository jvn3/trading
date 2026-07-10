"""S4.3 scenario tests: shock math hand-computed, drawdown-pause trip, trade-preview parity."""

from __future__ import annotations

from decimal import Decimal

import pytest

from alphadash.db.models import AssetClass, OrderSide
from alphadash.domain.risk import (
    AccountState,
    OrderIntent,
    PositionState,
    RiskLimitSet,
    validate_order,
)
from alphadash.domain.scenario import (
    ScenarioError,
    ShockScenario,
    apply_shock,
    preview_trade,
)

D = Decimal


def state(**overrides) -> AccountState:
    base = dict(
        equity=D("10000"),
        cash=D("4000"),
        positions={
            "AAPL": PositionState(
                symbol="AAPL",
                asset_class=AssetClass.equity,
                quantity=D("20"),
                market_value=D("4000"),
            ),
            "BTCUSD": PositionState(
                symbol="BTCUSD",
                asset_class=AssetClass.crypto,
                quantity=D("0.02"),
                market_value=D("2000"),
            ),
        },
        trades_this_week=0,
        drawdown_pct=D("0"),
        paused=False,
    )
    base.update(overrides)
    return AccountState(**base)


LIMITS = RiskLimitSet(drawdown_pause_pct=D("15"), per_suggestion_max_pct=D("5"))


def test_shock_hand_computed() -> None:
    impact = apply_shock(state(), ShockScenario(equity_pct=D("-20"), crypto_pct=D("-50")), LIMITS)
    # AAPL 4000 → 3200; BTC 2000 → 1000; cash 4000 untouched
    assert impact.equity_before == D("10000")
    assert impact.equity_after == D("8200.00")
    assert impact.equity_change_pct == D("-18.00")
    assert impact.cash == D("4000")
    by_symbol = {p.symbol: p for p in impact.positions}
    assert by_symbol["AAPL"].value_after == D("3200.00")
    assert by_symbol["BTCUSD"].value_after == D("1000.00")
    # allocation after: 3200/8200, 1000/8200, cash 4000/8200
    assert impact.allocation_after_pct["equity"] == D("39.02")
    assert impact.allocation_after_pct["crypto"] == D("12.20")
    assert impact.allocation_after_pct["cash"] == D("48.78")
    # -18% ≥ 15% pause threshold → would trip
    assert impact.would_trip_drawdown_pause is True


def test_symbol_override_beats_class_shock() -> None:
    impact = apply_shock(
        state(),
        ShockScenario(equity_pct=D("-20"), symbol_overrides={"aapl": D("-50")}),
        LIMITS,
    )
    by_symbol = {p.symbol: p for p in impact.positions}
    assert by_symbol["AAPL"].value_after == D("2000.00")  # override -50, not -20
    assert by_symbol["AAPL"].applied_pct == D("-50")
    assert by_symbol["BTCUSD"].value_after == D("2000.00")  # crypto default 0


def test_small_shock_does_not_trip_pause() -> None:
    impact = apply_shock(state(), ShockScenario(equity_pct=D("-10")), LIMITS)
    assert impact.equity_change_pct == D("-4.00")  # only 40% of the book is equity
    assert impact.would_trip_drawdown_pause is False


def test_positive_shock_and_bounds() -> None:
    impact = apply_shock(state(), ShockScenario(equity_pct=D("25")), LIMITS)
    assert impact.equity_after == D("11000.00")
    with pytest.raises(ScenarioError):
        apply_shock(state(), ShockScenario(equity_pct=D("-96")), LIMITS)
    with pytest.raises(ScenarioError):
        apply_shock(state(), ShockScenario(symbol_overrides={"AAPL": D("101")}), LIMITS)


def test_trade_preview_verdict_matches_validate_order_exactly() -> None:
    """Parity by construction: the preview must agree with the real gate on the same inputs."""
    s = state()
    for side, qty, price in (
        (OrderSide.buy, D("10"), D("100")),  # 1000 = 10% of equity > 5% cap → veto
        (OrderSide.buy, D("2"), D("100")),  # 200 = 2% → allowed
        (OrderSide.sell, D("50"), D("100")),  # more than held → veto (no shorting)
    ):
        preview = preview_trade(
            s,
            LIMITS,
            symbol="AAPL",
            asset_class=AssetClass.equity,
            side=side,
            qty=qty,
            price=price,
        )
        direct = validate_order(
            OrderIntent(
                symbol="AAPL", asset_class=AssetClass.equity, side=side, qty=qty, price=price
            ),
            s,
            LIMITS,
        )
        assert preview.decision.allow == direct.allow
        assert [v.message for v in preview.decision.violations] == [
            v.message for v in direct.violations
        ]


def test_trade_preview_post_trade_shape() -> None:
    preview = preview_trade(
        state(),
        LIMITS,
        symbol="AAPL",
        asset_class=AssetClass.equity,
        side=OrderSide.buy,
        qty=D("2"),
        price=D("100"),
    )
    assert preview.cash_after == D("3800.00")
    assert preview.position_value_after == D("4200.00")
    assert preview.position_allocation_after_pct == D("42.00")
    assert preview.cash_allocation_after_pct == D("38.00")
