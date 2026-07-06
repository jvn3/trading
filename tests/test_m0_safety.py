"""M0 safety-rail tests: signal expiry, regime staleness bound, tz-aware
position timestamps. See development/audit-2026-07-05.md for the incidents
these guard against.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select

from jay_trading.data import models, store
from jay_trading.data.db import create_all, session_scope
from jay_trading.schedule.jobs import (
    SIGNAL_MAX_AGE_DAYS,
    STALE_REGIME_MULTIPLIER,
    _effective_regime_multiplier,
    _unacted_signals,
)


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _insert_signal(age_days: int, ticker: str = "AAPL", score: float = 0.6) -> int:
    sig_id = store.record_signal(
        strategy_name="smart_copy",
        ticker=ticker,
        direction="long",
        score=score,
        rationale={},
    )
    with session_scope() as s:
        row = s.get(models.Signal, sig_id)
        row.generated_at = _utcnow_naive() - timedelta(days=age_days)
    return sig_id


# -- expire_stale_signals ----------------------------------------------------


def test_expire_marks_only_old_unacted_signals() -> None:
    create_all()
    old_id = _insert_signal(age_days=30, ticker="OLD")
    fresh_id = _insert_signal(age_days=1, ticker="FRESH")

    expired = store.expire_stale_signals(max_age_days=SIGNAL_MAX_AGE_DAYS)

    assert expired == 1
    with session_scope() as s:
        old = s.get(models.Signal, old_id)
        fresh = s.get(models.Signal, fresh_id)
        assert old.acted_on is True
        assert old.acted_order_id == "expired"
        assert fresh.acted_on is False


def test_expire_is_idempotent() -> None:
    create_all()
    _insert_signal(age_days=30)
    assert store.expire_stale_signals(max_age_days=7) == 1
    assert store.expire_stale_signals(max_age_days=7) == 0


def test_unacted_signals_filters_by_age_even_without_expiry() -> None:
    create_all()
    _insert_signal(age_days=30, ticker="OLD")
    _insert_signal(age_days=1, ticker="FRESH")

    views = _unacted_signals()

    assert [v.ticker for v in views] == ["FRESH"]


# -- regime staleness bound ---------------------------------------------------


def _snap(age_hours: float, regime: str = "FULL_RISK_ON") -> SimpleNamespace:
    return SimpleNamespace(
        ts=_utcnow_naive() - timedelta(hours=age_hours), regime=regime
    )


def test_fresh_snapshot_uses_regime_multiplier() -> None:
    name, mult = _effective_regime_multiplier(_snap(age_hours=2))
    assert name == "FULL_RISK_ON"
    assert mult == 1.0


def test_stale_snapshot_sizes_moderate() -> None:
    name, mult = _effective_regime_multiplier(_snap(age_hours=54 * 24))
    assert name is None
    assert mult == STALE_REGIME_MULTIPLIER


def test_missing_snapshot_sizes_moderate() -> None:
    name, mult = _effective_regime_multiplier(None)
    assert name is None
    assert mult == STALE_REGIME_MULTIPLIER


def test_aware_snapshot_ts_handled() -> None:
    snap = SimpleNamespace(
        ts=datetime.now(timezone.utc) - timedelta(hours=1), regime="MODERATE_RISK_ON"
    )
    name, mult = _effective_regime_multiplier(snap)
    assert name == "MODERATE_RISK_ON"
    assert mult == 0.75


# -- tz-aware opened_at through the portfolio snapshot ------------------------


class _FakeAccount:
    equity = "10000"
    cash = "5000"
    buying_power = "20000"


class _FakePosition:
    symbol = "MSFT"
    qty = "2"
    avg_entry_price = "400.0"
    current_price = "410.0"
    market_value = "820.0"
    unrealized_pl = "20.0"
    unrealized_plpc = "0.025"


class _FakeAlpaca:
    def get_account(self) -> _FakeAccount:
        return _FakeAccount()

    def get_positions(self) -> list[_FakePosition]:
        return [_FakePosition()]


def test_snapshot_opened_at_is_tz_aware() -> None:
    """A naive opened_at from SQLite must come out aware-UTC, so strategy
    max-hold math (aware-now minus opened_at) cannot raise TypeError."""
    create_all()
    with session_scope() as s:
        s.add(
            models.Position(
                ticker="MSFT",
                strategy_name="insider_follow",
                qty=2.0,
                avg_entry_price=400.0,
                opened_at=_utcnow_naive() - timedelta(days=3),
                trail_active=False,
            )
        )

    from jay_trading.executor import portfolio as portfolio_mod

    snap = portfolio_mod.build_snapshot(_FakeAlpaca())

    (view,) = snap.positions
    assert view.opened_at is not None
    assert view.opened_at.tzinfo is not None
    held_days = (datetime.now(timezone.utc) - view.opened_at).days
    assert held_days == 3
