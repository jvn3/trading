"""Tests for :mod:`scripts.backtest.metrics` (pure, no network)."""
from __future__ import annotations

import math

import pandas as pd
import pytest

from scripts.backtest.metrics import (
    cagr,
    exposure,
    max_drawdown,
    sharpe,
    summary,
    turnover,
)


def _equity_from_returns(returns: list[float]) -> pd.Series:
    equity = [1.0]
    for r in returns:
        equity.append(equity[-1] * (1.0 + r))
    return pd.Series(equity)


def test_cagr_constant_daily_return_range_index() -> None:
    # 252 steps of +0.1%/day on a RangeIndex = exactly one year of bars.
    equity = pd.Series([1.001**k for k in range(253)])
    assert cagr(equity) == pytest.approx(1.001**252 - 1)


def test_cagr_uses_calendar_time_for_date_index() -> None:
    # Doubling over ~one calendar year -> ~100% CAGR.
    idx = pd.DatetimeIndex(["2020-01-01", "2021-01-01"])
    equity = pd.Series([1.0, 2.0], index=idx)
    assert cagr(equity) == pytest.approx(1.0, rel=0.01)


def test_cagr_flat_curve_is_zero() -> None:
    assert cagr(pd.Series([1.0] * 100)) == pytest.approx(0.0)


def test_sharpe_hand_computed() -> None:
    # Daily returns 1%, 2%, 3%: mean 2%, std (ddof=1) exactly 1%.
    equity = pd.Series([1.0, 1.01, 1.01 * 1.02, 1.01 * 1.02 * 1.03])
    assert sharpe(equity) == pytest.approx(2.0 * math.sqrt(252), rel=1e-9)


def test_sharpe_zero_mean_is_zero() -> None:
    # Symmetric +10%/-10% daily returns have mean exactly 0 -> Sharpe 0.
    equity = _equity_from_returns([0.1, -0.1, 0.1, -0.1])
    assert sharpe(equity) == pytest.approx(0.0)


def test_sharpe_zero_volatility_returns_zero() -> None:
    equity = pd.Series([1.001**k for k in range(10)])
    assert sharpe(equity) == 0.0


def test_max_drawdown_hand_computed() -> None:
    equity = pd.Series([1.0, 1.2, 0.6, 0.9])
    assert max_drawdown(equity) == pytest.approx(0.6 / 1.2 - 1.0)  # -50%


def test_max_drawdown_monotonic_rise_is_zero() -> None:
    equity = pd.Series([1.0, 1.1, 1.2, 1.3])
    assert max_drawdown(equity) == pytest.approx(0.0)


def test_exposure_counts_non_cash_days() -> None:
    weights = pd.DataFrame({"A": [0.0, 1.0, 1.0, 0.0]})
    assert exposure(weights) == pytest.approx(0.5)


def test_turnover_single_entry_over_one_year() -> None:
    # 253 rows on a RangeIndex = 252 daily steps = 1 year; one 0->1 entry.
    weights = pd.DataFrame({"A": [1.0] * 253})
    assert turnover(weights) == pytest.approx(1.0)


def test_turnover_counts_absolute_weight_changes() -> None:
    weights = pd.DataFrame({"A": [1.0, 0.0, 1.0, 0.0] + [0.0] * 249})
    # Entry 1.0 + three flips of 1.0 each = 4.0 total over one year.
    assert turnover(weights) == pytest.approx(4.0)


def test_summary_shape_and_defaults() -> None:
    equity = pd.Series([1.0, 1.01, 1.02])
    s = summary(equity, "bench")
    assert s["name"] == "bench"
    assert set(s) == {"name", "cagr", "sharpe", "max_drawdown", "exposure", "turnover"}
    assert s["exposure"] == 1.0  # no weights given -> assumed always invested
    assert s["turnover"] == 0.0


def test_summary_with_weights_uses_them() -> None:
    equity = pd.Series([1.0, 1.0, 1.0, 1.0])
    weights = pd.DataFrame({"A": [0.0, 0.0, 1.0, 1.0]})
    s = summary(equity, "strat", weights)
    assert s["exposure"] == pytest.approx(0.5)
    assert s["turnover"] > 0.0
