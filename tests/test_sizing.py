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


# ---- Strategy V regime multiplier --------------------------------------


def test_regime_multiplier_one_is_default_and_no_op() -> None:
    # Default mult=1.0 → existing behavior preserved.
    dec = size_intent(_intent(notional=500), _portfolio(equity=10_000))
    assert dec.verdict == "APPROVE"


def test_regime_multiplier_zero_rejects_with_regime_blocked() -> None:
    dec = size_intent(
        _intent(notional=500),
        _portfolio(equity=10_000),
        regime_multiplier=0.0,
    )
    assert dec.verdict == "REJECT"
    assert "regime_blocked" in dec.reason


def test_regime_multiplier_scales_caller_notional() -> None:
    # 0.75 mult on $500 notional → $375.
    dec = size_intent(
        _intent(notional=500),
        _portfolio(equity=10_000),
        regime_multiplier=0.75,
    )
    assert dec.verdict == "MODIFY"
    assert dec.intent is not None
    assert dec.intent.notional == 375.0


def test_regime_multiplier_scales_default_equity_target() -> None:
    # qty-only intent (notional=None) → sizing layer uses 5% of equity = $500.
    # With mult=0.5 → $250.
    dec = size_intent(
        _intent(notional=None, qty=1.0),
        _portfolio(equity=10_000),
        regime_multiplier=0.5,
    )
    assert dec.verdict == "MODIFY"
    assert dec.intent is not None
    assert dec.intent.notional == 250.0


def test_regime_multiplier_above_one_is_clamped() -> None:
    # Defensive clamp — an upstream bug should not let regime inflate sizing
    # above the configured target_pct.
    dec = size_intent(
        _intent(notional=500),
        _portfolio(equity=10_000),
        regime_multiplier=2.0,
    )
    assert dec.verdict == "APPROVE"  # treated as 1.0


def test_regime_multiplier_negative_treated_as_block() -> None:
    dec = size_intent(
        _intent(notional=500),
        _portfolio(equity=10_000),
        regime_multiplier=-0.1,
    )
    assert dec.verdict == "REJECT"
    assert "regime_blocked" in dec.reason


def test_close_intent_ignores_regime_block() -> None:
    # CRISIS regime must never block exits.
    close = TradeIntent(
        strategy_name="smart_copy", ticker="NVDA", side="sell",
        qty=1.5, action="close",
    )
    dec = size_intent(
        close, _portfolio(positions=[_position("NVDA")]),
        regime_multiplier=0.0,
    )
    assert dec.verdict == "APPROVE"
