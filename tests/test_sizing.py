"""Tests for :mod:`jay_trading.risk.sizing`."""
from __future__ import annotations

from datetime import datetime, timezone

from jay_trading.risk.sizing import size_intent
from jay_trading.strategies.base import PortfolioSnapshot, PositionView, TradeIntent


def _portfolio(equity: float = 10_000.0, cash: float | None = None,
               positions: list[PositionView] | None = None) -> PortfolioSnapshot:
    cash = cash if cash is not None else equity
    return PortfolioSnapshot(
        equity=equity, cash=cash, buying_power=cash * 2,
        positions=positions or [],
        taken_at=datetime.now(timezone.utc),
    )


def _intent(notional: float | None = 500, ticker: str = "NVDA",
            strategy: str = "smart_copy", action: str = "open",
            qty: float | None = None) -> TradeIntent:
    return TradeIntent(
        strategy_name=strategy, ticker=ticker, side="buy",
        notional=notional, qty=qty, action=action,
    )


def _position(ticker: str, strategy: str = "smart_copy") -> PositionView:
    return PositionView(
        ticker=ticker, qty=1.0, avg_entry_price=100.0, current_price=100.0,
        market_value=100.0, unrealized_pl=0.0, unrealized_plpc=0.0,
        strategy_name=strategy, hard_stop=None, trail_peak=None, trail_active=False,
        opened_at=None, entry_signal_id=None,
    )


def test_approves_intent_at_target_size() -> None:
    dec = size_intent(_intent(notional=500), _portfolio(equity=10_000))
    assert dec.verdict == "APPROVE"


def test_caps_oversized_intent_at_hard_cap() -> None:
    # Ask for 50% of equity, hard cap is 10% → expect MODIFY to 1000.
    dec = size_intent(_intent(notional=5_000), _portfolio(equity=10_000))
    assert dec.verdict == "MODIFY"
    assert dec.intent is not None
    assert dec.intent.notional == 1_000


def test_rejects_when_at_concurrency_cap() -> None:
    positions = [_position(f"T{i}") for i in range(10)]
    dec = size_intent(_intent(), _portfolio(positions=positions))
    assert dec.verdict == "REJECT"
    assert "concurrency" in dec.reason


def test_rejects_when_already_holding_ticker() -> None:
    dec = size_intent(
        _intent(ticker="NVDA"),
        _portfolio(positions=[_position("NVDA")]),
    )
    assert dec.verdict == "REJECT"
    assert "already holding" in dec.reason


def test_close_intent_passes_through_unchanged() -> None:
    close = TradeIntent(
        strategy_name="smart_copy", ticker="NVDA", side="sell",
        qty=1.5, action="close",
    )
    dec = size_intent(close, _portfolio(positions=[_position("NVDA")]))
    assert dec.verdict == "APPROVE"
    assert dec.intent is close
