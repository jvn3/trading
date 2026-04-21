"""Tests for :mod:`jay_trading.signals.confluence`."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jay_trading.data import models, store
from jay_trading.data.db import create_all, session_scope
from jay_trading.signals import confluence


def test_no_partner_signal_returns_1x() -> None:
    create_all()
    assert confluence.multiplier_for_ticker("NVDA", my_strategy="insider_follow") == 1.0


def test_partner_signal_above_threshold_returns_confluence_multiplier() -> None:
    create_all()
    store.record_signal(
        strategy_name="smart_copy", ticker="NVDA", direction="long",
        score=0.7, rationale={},
    )
    mult = confluence.multiplier_for_ticker("NVDA", my_strategy="insider_follow")
    assert mult == confluence.CONFLUENCE_MULTIPLIER


def test_partner_signal_below_threshold_does_not_trigger() -> None:
    create_all()
    store.record_signal(
        strategy_name="smart_copy", ticker="AAPL", direction="long",
        score=0.4, rationale={},  # below CONFLUENCE_MIN_SCORE (0.5)
    )
    assert confluence.multiplier_for_ticker("AAPL", my_strategy="insider_follow") == 1.0


def test_old_partner_signal_outside_window_does_not_trigger() -> None:
    create_all()
    with session_scope() as s:
        sig = models.Signal(
            strategy_name="smart_copy", ticker="MSFT", direction="long",
            score=0.9, rationale={},
            generated_at=datetime.now(timezone.utc) - timedelta(days=60),
        )
        s.add(sig)
    assert confluence.multiplier_for_ticker("MSFT", my_strategy="insider_follow") == 1.0


def test_bidirectional_confluence_smart_copy_looks_up_insider() -> None:
    create_all()
    store.record_signal(
        strategy_name="insider_follow", ticker="GOOG", direction="long",
        score=0.6, rationale={},
    )
    mult = confluence.multiplier_for_ticker("GOOG", my_strategy="smart_copy")
    assert mult == confluence.CONFLUENCE_MULTIPLIER


def test_unknown_strategy_returns_1x() -> None:
    create_all()
    assert confluence.multiplier_for_ticker("NVDA", my_strategy="nonexistent") == 1.0
