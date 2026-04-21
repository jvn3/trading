"""Tests for :class:`jay_trading.strategies.insider_follow.InsiderFollowStrategy`."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from jay_trading.data import models, store
from jay_trading.data.db import create_all, session_scope
from jay_trading.data.fmp import _dedup_key
from jay_trading.strategies.base import PortfolioSnapshot, PositionView, SignalView, TradeIntent
from jay_trading.strategies.insider_follow import (
    HARD_STOP_PCT,
    InsiderFollowStrategy,
    TRAIL_ACTIVATE_PCT,
    _insider_sell_reversal,
)


def _portfolio(equity: float = 10_000.0, positions: list[PositionView] | None = None) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        equity=equity, cash=equity, buying_power=equity * 2,
        positions=positions or [],
        taken_at=datetime.now(timezone.utc),
    )


def _signal(ticker: str = "NVDA", score: float = 0.6, sid: int = 1) -> SignalView:
    return SignalView(
        id=sid, strategy_name="insider_follow", ticker=ticker,
        direction="long", score=score, rationale={"cluster": {}},
        generated_at=datetime.now(timezone.utc),
    )


def _position(ticker: str, strategy: str = "insider_follow", plpc: float = 0.0,
              current: float = 100.0, opened_days_ago: int = 0,
              trail_peak: float | None = None) -> PositionView:
    return PositionView(
        ticker=ticker, qty=1.0, avg_entry_price=100.0, current_price=current,
        market_value=current, unrealized_pl=0.0, unrealized_plpc=plpc,
        strategy_name=strategy, hard_stop=None, trail_peak=trail_peak,
        trail_active=trail_peak is not None,
        opened_at=datetime.now(timezone.utc) - timedelta(days=opened_days_ago),
        entry_signal_id=None,
    )


# -- Entry logic -----------------------------------------------------------


def test_generates_intent_at_base_5pct_notional_when_no_confluence() -> None:
    create_all()
    strat = InsiderFollowStrategy()
    intents = strat.generate_intents([_signal(score=0.6)], _portfolio(equity=10_000))
    assert len(intents) == 1
    assert intents[0].notional == 500.0  # 5% of 10k
    assert intents[0].rationale["confluence_multiplier"] == 1.0


def test_confluence_bumps_notional_to_75pct() -> None:
    create_all()
    # Seed a smart_copy signal for the same ticker → confluence multiplier 1.5.
    store.record_signal(
        strategy_name="smart_copy", ticker="NVDA", direction="long",
        score=0.7, rationale={"cluster": {}},
    )
    strat = InsiderFollowStrategy()
    intents = strat.generate_intents([_signal(ticker="NVDA", score=0.6)], _portfolio(equity=10_000))
    assert len(intents) == 1
    assert intents[0].notional == 750.0  # 7.5% of 10k
    assert intents[0].rationale["confluence_multiplier"] == 1.5


def test_rejects_signal_below_threshold() -> None:
    create_all()
    strat = InsiderFollowStrategy()
    intents = strat.generate_intents([_signal(score=0.3)], _portfolio())
    assert intents == []


def test_at_concurrency_cap_produces_no_intents() -> None:
    create_all()
    strat = InsiderFollowStrategy()
    positions = [_position(f"T{i}") for i in range(5)]  # cap is 5
    intents = strat.generate_intents([_signal()], _portfolio(positions=positions))
    assert intents == []


def test_does_not_double_buy_open_ticker() -> None:
    create_all()
    strat = InsiderFollowStrategy()
    intents = strat.generate_intents(
        [_signal(ticker="NVDA")],
        _portfolio(positions=[_position("NVDA")]),
    )
    assert intents == []


# -- Exit logic ------------------------------------------------------------


def test_hard_stop_triggers_at_or_below_threshold() -> None:
    strat = InsiderFollowStrategy()
    intents = strat.manage_positions([_position("NVDA", plpc=HARD_STOP_PCT)], _portfolio())
    assert len(intents) == 1
    assert intents[0].action == "close"
    assert intents[0].rationale["exit_reason"] == "hard_stop"


def test_trail_activates_and_exits_on_giveback() -> None:
    strat = InsiderFollowStrategy()
    # After +15% the trail arms. If price drops 7% off the peak, exit.
    pos = _position("NVDA", plpc=TRAIL_ACTIVATE_PCT, current=93.0, trail_peak=100.0)
    intents = strat.manage_positions([pos], _portfolio())
    assert len(intents) == 1
    assert intents[0].rationale["exit_reason"] == "trail_stop"


def test_max_hold_exit_at_90_days() -> None:
    strat = InsiderFollowStrategy()
    intents = strat.manage_positions([_position("NVDA", opened_days_ago=95)], _portfolio())
    assert len(intents) == 1
    assert intents[0].rationale["exit_reason"] == "max_hold"


def test_ignores_positions_from_other_strategies() -> None:
    strat = InsiderFollowStrategy()
    intents = strat.manage_positions(
        [_position("NVDA", strategy="smart_copy", plpc=-0.2)],
        _portfolio(),
    )
    assert intents == []


# -- Insider sell reversal -------------------------------------------------


def _insider_sell_row(person: str, ticker: str, role: str) -> dict:
    tx = date.today() - timedelta(days=5)
    return {
        "source": "insider", "person_name": person, "person_role": role,
        "ticker": ticker.upper(), "transaction_type": "sell",
        "transaction_date": tx, "filing_date": tx,
        "amount_low": None, "amount_high": None, "amount_exact": None,
        "dedup_key": _dedup_key("insider", [person, ticker, tx, "sell", role]),
        "raw_payload": {"transactionType": "S-Sale", "typeOfOwner": role},
    }


def test_reversal_fires_on_two_officer_sales() -> None:
    create_all()
    store.upsert_disclosed_trades([
        _insider_sell_row("Alice", "NVDA", "officer: CEO"),
        _insider_sell_row("Bob", "NVDA", "officer: CFO"),
    ])
    assert _insider_sell_reversal("NVDA") is True


def test_reversal_does_not_fire_on_single_sale() -> None:
    create_all()
    store.upsert_disclosed_trades([_insider_sell_row("Alice", "NVDA", "officer: CEO")])
    assert _insider_sell_reversal("NVDA") is False


def test_reversal_ignores_non_officer_sales() -> None:
    create_all()
    # 2 sales but both by "10 percent owner" — not officer/director.
    store.upsert_disclosed_trades([
        _insider_sell_row("Alice", "NVDA", "10 percent owner"),
        _insider_sell_row("Bob", "NVDA", "10 percent owner"),
    ])
    assert _insider_sell_reversal("NVDA") is False
