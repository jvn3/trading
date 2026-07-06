"""Tests for :mod:`scripts.backtest.engine` (pure, no network)."""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.backtest.engine import run_weights


def _prices(values: list[float], col: str = "A") -> pd.DataFrame:
    return pd.DataFrame({col: values})


def _weights(values: list[float], col: str = "A") -> pd.DataFrame:
    return pd.DataFrame({col: values})


def test_next_day_shift_blocks_lookahead() -> None:
    # Price doubles on day 2. A signal emitted ON day 2 (i.e. computed from
    # day 2's close) would double our money if the engine filled same-day.
    prices = _prices([100.0, 100.0, 200.0, 200.0, 200.0])
    cheating = _weights([0.0, 0.0, 1.0, 0.0, 0.0])
    equity = run_weights(prices, cheating, cost_bps=0.0)
    # With the next-day convention the position is held during day 3, which
    # is flat — the jump is never captured.
    assert equity.iloc[-1] == pytest.approx(1.0)
    assert (equity <= 1.0 + 1e-12).all()


def test_signal_on_prior_day_does_capture_move() -> None:
    prices = _prices([100.0, 100.0, 200.0, 200.0, 200.0])
    legit = _weights([0.0, 1.0, 0.0, 0.0, 0.0])  # decided at day 1 close
    equity = run_weights(prices, legit, cost_bps=0.0)
    assert equity.iloc[-1] == pytest.approx(2.0)


def test_full_weight_tracks_asset_with_one_day_lag() -> None:
    prices = _prices([100.0, 110.0, 121.0])
    equity = run_weights(prices, _weights([1.0, 1.0, 1.0]), cost_bps=0.0)
    assert list(equity) == pytest.approx([1.0, 1.1, 1.21])


def test_partial_weight_earns_partial_return_rest_cash() -> None:
    prices = _prices([100.0, 110.0])
    equity = run_weights(prices, _weights([0.5, 0.5]), cost_bps=0.0)
    assert equity.iloc[-1] == pytest.approx(1.05)


def test_entry_cost_reduces_equity_by_expected_bps() -> None:
    prices = _prices([100.0] * 5)
    equity = run_weights(prices, _weights([1.0] * 5), cost_bps=10.0)
    # One entry from cash -> one unit of turnover -> 10 bps once.
    assert equity.iloc[-1] == pytest.approx(1.0 - 10 / 10_000)


def test_round_trip_charges_costs_twice() -> None:
    prices = _prices([100.0] * 6)
    weights = _weights([1.0, 1.0, 0.0, 0.0, 0.0, 0.0])
    equity = run_weights(prices, weights, cost_bps=10.0)
    assert equity.iloc[-1] == pytest.approx((1.0 - 0.001) ** 2)


def test_rejects_weights_summing_above_one() -> None:
    prices = pd.DataFrame({"A": [100.0, 101.0], "B": [50.0, 51.0]})
    weights = pd.DataFrame({"A": [0.8, 0.8], "B": [0.5, 0.5]})
    with pytest.raises(ValueError, match="sum"):
        run_weights(prices, weights)


def test_rejects_negative_weights() -> None:
    prices = _prices([100.0, 101.0])
    with pytest.raises(ValueError, match="negative"):
        run_weights(prices, _weights([-0.5, 0.0]))


def test_missing_weight_columns_treated_as_zero() -> None:
    prices = pd.DataFrame({"A": [100.0, 110.0], "B": [100.0, 90.0]})
    weights = pd.DataFrame({"A": [1.0, 1.0]})  # no B column -> B weight 0
    equity = run_weights(prices, weights, cost_bps=0.0)
    assert equity.iloc[-1] == pytest.approx(1.1)
