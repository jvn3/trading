"""S4.2 backtest tests: no-lookahead, hand-computed fills, walk-forward windows, honesty."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from alphadash.domain.strategy_backtest import (
    SLIPPAGE,
    STARTING_EQUITY,
    BacktestError,
    run_backtest,
)
from alphadash.domain.strategy_rules import StrategyParams

D = Decimal


def params(**overrides) -> StrategyParams:
    base = {
        "symbol": "AAPL",
        "asset_class": "equity",
        "entry": {"kind": "price_above_sma", "window": 3},
        "stop_loss_pct": "50",
        "take_profit_pct": "400",
        "size_pct": "10",
    }
    base.update(overrides)
    return StrategyParams.model_validate(base)


def series(closes: list[Decimal]):
    start = date(2026, 1, 1)
    return [start + timedelta(days=i) for i in range(len(closes))], closes


def test_requires_minimum_history() -> None:
    days, closes = series([D(100)] * 10)
    with pytest.raises(BacktestError, match="not enough price history"):
        run_backtest(days=days, closes=closes, benchmark_closes=closes, params=params())


def test_requires_aligned_series() -> None:
    days, closes = series([D(100)] * 40)
    with pytest.raises(BacktestError, match="benchmark"):
        run_backtest(days=days, closes=closes, benchmark_closes=closes[:-1], params=params())


def test_no_lookahead_next_close_fill() -> None:
    """The first possible fill is the close AFTER the first signal close — never the same day."""
    # Flat at 100 for 4 days (sma == price → no entry), then a jump that triggers entry.
    closes = [D(100)] * 4 + [D(110)] + [D(120)] * 30
    days, closes = series(closes)
    result = run_backtest(days=days, closes=closes, benchmark_closes=closes, params=params())
    # Signal fires on the 110 close (index 4); the fill must be at index 5's close (120),
    # not at 110. With 10% sizing: entry uses 120*(1+5bps).
    fill_price = D(120) * (1 + SLIPPAGE)
    invested = STARTING_EQUITY * D("0.10")
    qty = invested / fill_price
    # No exit ever fires (flat at 120, generous bands) → final equity = cash + qty*120
    expected_final = (STARTING_EQUITY - qty * fill_price) + qty * D(120)
    assert result.closed_trades == ()
    # final equity implied by total_return_pct
    final = STARTING_EQUITY * (1 + result.total_return_pct / 100)
    assert abs(final - expected_final) < D("1")  # within rounding of the 2dp return


def test_round_trip_stop_loss_hand_computed() -> None:
    # Enter after rise, then crash 60% → stop loss (50%) exits.
    closes = (
        [D(100)] * 4  # warmup, no signal
        + [D(110), D(120)]  # signal on 110, fill at 120
        + [D(40)] * 2  # crash: stop fires on first 40 close, fills at second 40 close
        + [D(40)] * 25
    )
    days, closes = series(closes)
    result = run_backtest(days=days, closes=closes, benchmark_closes=closes, params=params())
    assert len(result.closed_trades) == 1
    trade = result.closed_trades[0]
    entry = D(120) * (1 + SLIPPAGE)
    exit_ = D(40) * (1 - SLIPPAGE)
    assert trade.entry_price == entry
    assert trade.exit_price == exit_
    assert trade.return_pct < D("-66")  # ~ -66.7%
    assert result.win_rate_pct == D("0.00")
    assert result.small_sample is True


def test_windows_cover_full_span_and_count_trades() -> None:
    closes = [D(100) + D(i) for i in range(60)]  # steady rise → one entry, no exit
    days, closes = series(closes)
    result = run_backtest(
        days=days, closes=closes, benchmark_closes=closes, params=params(), n_windows=4
    )
    assert len(result.windows) == 4
    assert result.windows[0].start == days[0]
    assert result.windows[-1].end == days[-1]
    # windows are contiguous
    for prev, nxt in zip(result.windows, result.windows[1:], strict=False):
        assert (nxt.start - prev.end).days == 1
    # every window carries its own buy-and-hold comparison (no naked returns)
    assert all(w.buy_hold_return_pct is not None for w in result.windows)


def test_caveats_always_present_and_small_sample_flagged() -> None:
    closes = [D(100) + D(i) for i in range(40)]
    days, closes = series(closes)
    result = run_backtest(days=days, closes=closes, benchmark_closes=closes, params=params())
    assert any("does not predict" in c for c in result.caveats)
    assert any("Walk-forward" in c or "walk-forward" in c.lower() for c in result.caveats)
    assert result.small_sample is True
    assert any("too few" in c for c in result.caveats)


def test_benchmark_return_reported_from_own_series() -> None:
    closes = [D(100)] * 40
    bench = [D(100) + D(i) for i in range(40)]  # benchmark rallies while symbol flat
    days, closes = series(closes)
    result = run_backtest(days=days, closes=closes, benchmark_closes=bench, params=params())
    assert result.total_return_pct == D("0.00")
    assert result.benchmark_return_pct == D("39.00")
