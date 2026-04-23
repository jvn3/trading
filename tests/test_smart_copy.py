"""Tests for SmartCopyStrategy (pure logic, no network)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from jay_trading.data.db import create_all
from jay_trading.strategies.base import PortfolioSnapshot, PositionView, SignalView
from jay_trading.strategies.smart_copy import SmartCopyStrategy


@pytest.fixture(autouse=True)
def _schema() -> None:
    # manage_positions queries disclosed_trades for reversal detection.
    create_all()


def _sig(i: int = 1, ticker: str = "NVDA", score: float = 0.8,
         direction: str = "long") -> SignalView:
    return SignalView(
        id=i, strategy_name="smart_copy", ticker=ticker, direction=direction,
        score=score, rationale={"cluster": {"members": []}},
        generated_at=datetime.now(timezone.utc),
    )


def _pf(equity: float = 10_000, positions=None) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        equity=equity, cash=equity, buying_power=equity * 2,
        positions=positions or [],
        taken_at=datetime.now(timezone.utc),
    )


def _pos(ticker: str, plpc: float = 0.0, strategy: str = "smart_copy",
         price: float = 100.0, peak: float | None = None) -> PositionView:
    return PositionView(
        ticker=ticker, qty=1.0, avg_entry_price=100.0, current_price=price,
        market_value=price, unrealized_pl=(price - 100),
        unrealized_plpc=plpc, strategy_name=strategy,
        hard_stop=None, trail_peak=peak, trail_active=(peak is not None),
        opened_at=None, entry_signal_id=1,
    )


def test_generate_intents_filters_low_scores() -> None:
    s = SmartCopyStrategy()
    intents = s.generate_intents([_sig(score=0.4)], _pf())
    assert intents == []


def test_generate_intents_admits_at_new_threshold() -> None:
    # 2-pol clusters with positive avg quality score 0.48 — must clear the
    # post-knob-1 threshold (0.45). Regression guard so a future bump back
    # to 0.5 doesn't silently re-block them.
    s = SmartCopyStrategy()
    intents = s.generate_intents([_sig(score=0.48)], _pf())
    assert len(intents) == 1


def test_generate_intents_blocks_just_below_threshold() -> None:
    s = SmartCopyStrategy()
    intents = s.generate_intents([_sig(score=0.44)], _pf())
    assert intents == []


def test_generate_intents_skips_tickers_we_hold() -> None:
    s = SmartCopyStrategy()
    intents = s.generate_intents([_sig()], _pf(positions=[_pos("NVDA")]))
    assert intents == []


def test_generate_intents_respects_concurrency_cap() -> None:
    s = SmartCopyStrategy()
    positions = [_pos(f"T{i}") for i in range(10)]
    intents = s.generate_intents([_sig(ticker="NEW", score=0.9)], _pf(positions=positions))
    assert intents == []


def test_generate_intents_picks_highest_scored_first() -> None:
    s = SmartCopyStrategy()
    sigs = [
        _sig(i=1, ticker="A", score=0.55),
        _sig(i=2, ticker="B", score=0.9),
        _sig(i=3, ticker="C", score=0.7),
    ]
    # Force only 1 slot.
    s.max_concurrent_positions = 1
    intents = s.generate_intents(sigs, _pf())
    assert len(intents) == 1
    assert intents[0].ticker == "B"


def test_manage_positions_hard_stop() -> None:
    s = SmartCopyStrategy()
    outs = s.manage_positions([_pos("NVDA", plpc=-0.09)], _pf())
    assert len(outs) == 1
    assert outs[0].side == "sell" and outs[0].action == "close"
    assert outs[0].rationale.get("exit_reason") == "hard_stop"


def test_manage_positions_trail_fires_after_giveback() -> None:
    s = SmartCopyStrategy()
    # +12% unrealized, peak at 120, now at 112 → > 5% giveback → should exit.
    pos = _pos("NVDA", plpc=0.12, price=112.0, peak=120.0)
    outs = s.manage_positions([pos], _pf())
    assert len(outs) == 1
    assert outs[0].rationale.get("exit_reason") == "trail_stop"


def test_manage_positions_no_action_in_comfortable_zone() -> None:
    s = SmartCopyStrategy()
    pos = _pos("NVDA", plpc=0.05, price=105.0)
    outs = s.manage_positions([pos], _pf())
    assert outs == []
