"""Equity snapshot + drawdown helpers.

Wraps :mod:`jay_trading.data.store` with the portfolio-level math the
daily-loss and drawdown gates need. Keeps :mod:`guards` free of SQL.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from jay_trading.data import store

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class EquityView:
    equity: float
    last_equity: float   # yesterday's close, from Alpaca's account.last_equity
    high_water_mark: float

    @property
    def daily_change_fraction(self) -> float:
        """(equity - last_equity) / last_equity; 0 if no prior close known."""
        if self.last_equity <= 0:
            return 0.0
        return (self.equity - self.last_equity) / self.last_equity

    @property
    def drawdown_from_hwm(self) -> float:
        """(equity - hwm) / hwm; <= 0 by construction (hwm is a ceiling)."""
        if self.high_water_mark <= 0:
            return 0.0
        return (self.equity - self.high_water_mark) / self.high_water_mark


def build_view(alpaca: Any) -> EquityView:
    """Construct an :class:`EquityView` from a live Alpaca account + the DB.

    If no ``equity_snapshots`` row exists yet, bootstrap one from the
    current Alpaca equity (this becomes the initial HWM).
    """
    acct = alpaca.get_account()
    current = float(acct.equity)
    # Alpaca exposes ``last_equity`` as yesterday's close; on weekends/holidays
    # Alpaca typically returns the last trading day's close in that field.
    last = float(getattr(acct, "last_equity", current) or current)

    snap = store.latest_equity_snapshot()
    if snap is None:
        _id = store.record_equity_snapshot(equity=current, cash=float(acct.cash))
        log.info("equity_tracker: seeded first snapshot (id=%s, equity=%.2f)", _id, current)
        hwm = current
    else:
        hwm = float(snap.high_water_mark)
        # The current live equity may already be above the stored HWM; the
        # stored HWM updates on the daily snapshot job, not on every call.
        # For the drawdown check, use whichever is higher.
        hwm = max(hwm, current)

    return EquityView(equity=current, last_equity=last, high_water_mark=hwm)
