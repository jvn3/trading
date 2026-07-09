"""S2.1 tests: deterministic candidates, numeric features, LLM-free rules."""

from __future__ import annotations

from decimal import Decimal

from alphadash.db.models import AssetClass, OrderSide
from alphadash.domain.risk import AccountState, PositionState, RiskLimitSet
from alphadash.domain.signals import (
    CandidateAction,
    SignalInputs,
    WatchItem,
    generate_candidates,
)

D = Decimal


def pos(symbol, qty, value, asset_class=AssetClass.equity):
    return PositionState(
        symbol=symbol, asset_class=asset_class, quantity=D(qty), market_value=D(value)
    )


def state(**kw) -> AccountState:
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


def rising_closes(start: str, n: int = 25, step: str = "2") -> list[Decimal]:
    return [D(start) + D(step) * i for i in range(n)]


def test_rebalance_candidate_when_class_over_cap() -> None:
    s = state(
        positions={
            "BTCUSD": pos("BTCUSD", "0.05", "3000", AssetClass.crypto),
            "ETHUSD": pos("ETHUSD", "1", "500", AssetClass.crypto),
        }
    )
    limits = RiskLimitSet(max_asset_class_pct={"crypto": D("10")})
    out = generate_candidates(SignalInputs(state=s, limits=limits))
    assert len(out) == 1
    c = out[0]
    assert c.kind == "rebalance" and c.side is OrderSide.sell
    assert c.symbol == "BTCUSD"  # largest position trimmed
    assert c.features["class_allocation_pct"] == D("35.00")
    assert c.features["class_cap_pct"] == D("10")
    assert c.features["excess_pct"] == D("25.00")


def test_no_rebalance_within_tolerance() -> None:
    s = state(positions={"BTCUSD": pos("BTCUSD", "0.01", "1050", AssetClass.crypto)})
    limits = RiskLimitSet(max_asset_class_pct={"crypto": D("10")})  # 10.5% < 10+1 tolerance
    assert generate_candidates(SignalInputs(state=s, limits=limits)) == []


def test_take_profit_candidate() -> None:
    s = state(positions={"NVDA": pos("NVDA", "10", "1500")})  # price 150
    inputs = SignalInputs(state=s, limits=RiskLimitSet(), avg_costs={"NVDA": D("100")})
    out = generate_candidates(inputs)
    assert [c.kind for c in out] == ["take_profit"]
    assert out[0].features["unrealized_gain_pct"] == D("50.00")
    assert out[0].side is OrderSide.sell


def test_momentum_candidate_from_watchlist() -> None:
    closes = rising_closes("100")  # 20-bar return = 40/148 well above 5%
    inputs = SignalInputs(
        state=state(),
        limits=RiskLimitSet(),
        closes={"AAPL": closes},
        watchlist=(WatchItem("AAPL", AssetClass.equity),),
    )
    out = generate_candidates(inputs)
    assert [c.kind for c in out] == ["momentum"]
    c = out[0]
    assert c.side is OrderSide.buy
    assert c.features["return_20d_pct"] > D("5")
    assert c.features["last_close"] == closes[-1]


def test_momentum_suppressed_when_paused_or_drawdown() -> None:
    closes = rising_closes("100")
    base = dict(
        limits=RiskLimitSet(drawdown_pause_pct=D("15")),
        closes={"AAPL": closes},
        watchlist=(WatchItem("AAPL", AssetClass.equity),),
    )
    assert generate_candidates(SignalInputs(state=state(paused=True), **base)) == []
    assert generate_candidates(SignalInputs(state=state(drawdown_pct=D("20")), **base)) == []
    # But sells (take_profit/rebalance) still allowed while paused
    s = state(paused=True, positions={"NVDA": pos("NVDA", "10", "1500")})
    out = generate_candidates(
        SignalInputs(state=s, limits=RiskLimitSet(), avg_costs={"NVDA": D("100")})
    )
    assert [c.kind for c in out] == ["take_profit"]


def test_weak_momentum_and_short_history_ignored() -> None:
    flat = [D("100")] * 25
    short = rising_closes("100", n=10)
    inputs = SignalInputs(
        state=state(),
        limits=RiskLimitSet(),
        closes={"FLAT": flat, "SHORT": short},
        watchlist=(WatchItem("FLAT", AssetClass.equity), WatchItem("SHORT", AssetClass.equity)),
    )
    assert generate_candidates(inputs) == []


def test_deterministic_ordering_and_cap() -> None:
    s = state(
        positions={
            "BTCUSD": pos("BTCUSD", "0.05", "3000", AssetClass.crypto),
            "NVDA": pos("NVDA", "10", "1500"),
        }
    )
    inputs = SignalInputs(
        state=s,
        limits=RiskLimitSet(max_asset_class_pct={"crypto": D("10")}),
        avg_costs={"NVDA": D("100")},
        closes={"AAPL": rising_closes("100"), "MSFT": rising_closes("200")},
        watchlist=(WatchItem("MSFT", AssetClass.equity), WatchItem("AAPL", AssetClass.equity)),
    )
    first = generate_candidates(inputs)
    second = generate_candidates(inputs)
    assert first == second  # deterministic
    assert [c.ref for c in first] == [
        "rebalance:crypto:BTCUSD",
        "take_profit:NVDA",
        "momentum:AAPL",  # sorted watchlist: AAPL before MSFT
        "momentum:MSFT",
    ]
    assert len(first) <= 5


def test_candidate_serializes_decimals_as_strings() -> None:
    c = CandidateAction(
        kind="momentum",
        symbol="AAPL",
        asset_class=AssetClass.equity,
        side=OrderSide.buy,
        features={"return_20d_pct": D("7.25")},
        ref="momentum:AAPL",
    )
    assert c.as_json()["features"]["return_20d_pct"] == "7.25"
