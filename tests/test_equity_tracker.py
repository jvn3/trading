"""Tests for :mod:`jay_trading.risk.equity_tracker`."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jay_trading.data import store
from jay_trading.data.db import create_all
from jay_trading.risk import equity_tracker


@dataclass
class _FakeAccount:
    equity: float
    last_equity: float
    cash: float


class _FakeAlpaca:
    def __init__(self, equity: float, last_equity: float | None = None, cash: float | None = None) -> None:
        self._acct = _FakeAccount(
            equity=equity,
            last_equity=last_equity if last_equity is not None else equity,
            cash=cash if cash is not None else equity,
        )

    def get_account(self) -> Any:
        return self._acct


def test_build_view_seeds_snapshot_when_empty() -> None:
    create_all()
    view = equity_tracker.build_view(_FakeAlpaca(equity=10_000.0))
    assert view.equity == 10_000.0
    assert view.high_water_mark == 10_000.0

    snap = store.latest_equity_snapshot()
    assert snap is not None
    assert snap.equity == 10_000.0


def test_daily_change_fraction_reflects_prev_close() -> None:
    create_all()
    view = equity_tracker.build_view(_FakeAlpaca(equity=9_800.0, last_equity=10_000.0))
    assert view.daily_change_fraction == -0.02  # -2% from last close


def test_drawdown_from_hwm_uses_max_of_stored_and_live() -> None:
    create_all()
    # Seed a snapshot at $10k so HWM is 10k.
    store.record_equity_snapshot(equity=10_000.0, cash=10_000.0)
    # Current equity drawn down to $9,500.
    view = equity_tracker.build_view(_FakeAlpaca(equity=9_500.0, last_equity=9_500.0))
    assert view.drawdown_from_hwm == -0.05  # exactly -5%


def test_drawdown_is_zero_when_at_new_high() -> None:
    create_all()
    view = equity_tracker.build_view(_FakeAlpaca(equity=10_500.0))
    # HWM was seeded to the current equity, so DD is 0.
    assert view.drawdown_from_hwm == 0.0
