"""S4.2 rule DSL tests: schema bounds, condition evaluation, decision precedence, describe."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from alphadash.domain.strategy_rules import (
    Condition,
    ConditionKind,
    StrategyParams,
    condition_met,
    describe,
    evaluate,
    sma,
)


def params(**overrides) -> StrategyParams:
    base = {
        "symbol": "AAPL",
        "asset_class": "equity",
        "entry": {"kind": "price_above_sma", "window": 3},
        "stop_loss_pct": "10",
        "take_profit_pct": "20",
        "size_pct": "5",
    }
    base.update(overrides)
    return StrategyParams.model_validate(base)


# --- schema bounds ---


def test_symbol_normalized_to_upper() -> None:
    assert params(symbol=" aapl ").symbol == "AAPL"


@pytest.mark.parametrize(
    "bad",
    [
        {"entry": {"kind": "price_above_sma", "window": 1}},  # window too small
        {"entry": {"kind": "price_above_sma", "window": 201}},
        {"entry": {"kind": "return_exceeds", "window": 10}},  # missing threshold
        {"entry": {"kind": "price_above_sma", "window": 10, "threshold_pct": "5"}},  # extra
        {"entry": {"kind": "return_exceeds", "window": 10, "threshold_pct": "0.1"}},  # < 0.5
        {"size_pct": "25"},  # above hard cap
        {"size_pct": "0.1"},
        {"stop_loss_pct": "96"},
        {"take_profit_pct": "501"},
    ],
)
def test_schema_rejects_out_of_bounds(bad) -> None:
    with pytest.raises(ValidationError):
        params(**bad)


def test_schema_requires_at_least_one_exit() -> None:
    with pytest.raises(ValidationError, match="at least one exit"):
        params(stop_loss_pct=None, take_profit_pct=None, exit_condition=None)


# --- evaluation ---

D = Decimal


def test_sma_needs_full_window() -> None:
    assert sma([D(1), D(2)], 3) is None
    assert sma([D(1), D(2), D(3)], 3) == D(2)


def test_price_above_and_below_sma() -> None:
    above = Condition(kind=ConditionKind.price_above_sma, window=3)
    below = Condition(kind=ConditionKind.price_below_sma, window=3)
    rising = [D(1), D(2), D(6)]  # sma=3, last=6
    assert condition_met(rising, above) is True
    assert condition_met(rising, below) is False
    assert condition_met([D(1), D(2)], above) is None  # insufficient history → never guess


def test_return_conditions_boundaries() -> None:
    up = Condition(kind=ConditionKind.return_exceeds, window=2, threshold_pct=D(10))
    down = Condition(kind=ConditionKind.return_below, window=2, threshold_pct=D(10))
    closes = [D(100), D(105), D(110)]  # 2-day return exactly +10%
    assert condition_met(closes, up) is True  # >= is inclusive
    assert condition_met(closes, down) is False
    falling = [D(100), D(95), D(90)]  # exactly -10%
    assert condition_met(falling, down) is True
    assert condition_met([D(100), D(105)], up) is None  # needs window+1 closes


def test_evaluate_entry_and_wait() -> None:
    p = params()  # enter when close > 3-day sma
    assert evaluate([D(1), D(2), D(6)], p, entry_price=None) == "enter"
    assert evaluate([D(6), D(2), D(1)], p, entry_price=None) == "wait"
    assert evaluate([], p, entry_price=None) == "wait"


def test_evaluate_exit_precedence_stop_loss_first() -> None:
    # Price down 15% from entry: stop (10%) fires even though take profit can't
    p = params()
    assert evaluate([D(100), D(90), D(85)], p, entry_price=D(100)) == "exit"
    # Price up 25%: take profit fires
    assert evaluate([D(100), D(110), D(125)], p, entry_price=D(100)) == "exit"
    # Price wobbling inside the band: hold
    assert evaluate([D(100), D(101), D(102)], p, entry_price=D(100)) == "hold"


def test_evaluate_exit_condition_used_when_bands_quiet() -> None:
    p = params(
        stop_loss_pct=None,
        take_profit_pct=None,
        exit_condition={"kind": "price_below_sma", "window": 3},
    )
    # last below sma → exit
    assert evaluate([D(6), D(5), D(1)], p, entry_price=D(4)) == "exit"
    assert evaluate([D(1), D(2), D(6)], p, entry_price=D(4)) == "hold"


# --- describe (faithfulness) ---


def test_describe_is_plain_language_and_complete() -> None:
    text = describe(params())
    assert "Buy AAPL with 5% of the portfolio" in text
    assert "3-day average" in text
    assert "down 10% (stop loss)" in text
    assert "up 20% (take profit)" in text
    assert "safety limits" in text
    assert "10.0000" not in text  # no Decimal noise
