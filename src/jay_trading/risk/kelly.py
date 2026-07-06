"""Fractional-Kelly sizing estimator over the closed-trade ledger.

Kelly criterion for a win-probability ``p`` with win/loss payoff ratio
``b = avg_win / avg_loss``:  f* = p - (1 - p) / b.

We only trust it once a sleeve has a real sample (``min_trades`` closed
round trips in ``positions`` with ``realized_pnl`` populated — the ledger
that reconcile started writing on 2026-07-06), and we always halve it
(half-Kelly), the standard guard against estimation error. Returns ``None``
whenever the estimate would be junk: small sample, no losses yet (b
undefined → overconfident), or a negative edge (caller should not size UP
a losing sleeve; a negative value is returned as 0.0 so callers can also
choose to pause the sleeve).
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from jay_trading.data import models
from jay_trading.data.db import session_scope

log = logging.getLogger(__name__)

HALF_KELLY = 0.5


def closed_trade_pnls(strategy_name: str) -> list[float]:
    """Realized P&L of every closed round trip for the sleeve."""
    with session_scope() as s:
        rows = s.scalars(
            select(models.Position.realized_pnl)
            .where(models.Position.strategy_name == strategy_name)
            .where(models.Position.closed_at.is_not(None))
            .where(models.Position.realized_pnl.is_not(None))
        )
        return [float(v) for v in rows]


def kelly_fraction(
    strategy_name: str,
    *,
    min_trades: int = 20,
    fraction: float = HALF_KELLY,
) -> float | None:
    """Half-Kelly bet fraction for the sleeve, or ``None`` if unestimable."""
    pnls = closed_trade_pnls(strategy_name)
    n = len(pnls)
    if n < min_trades:
        return None

    wins = [p for p in pnls if p > 0]
    losses = [-p for p in pnls if p < 0]
    if not wins or not losses:
        # All-win or all-loss samples give degenerate Kelly (infinite or
        # undefined b). Refuse rather than emit a confident nonsense number.
        return None

    p = len(wins) / n
    b = (sum(wins) / len(wins)) / (sum(losses) / len(losses))
    if b <= 0:
        return None

    f_star = p - (1.0 - p) / b
    if f_star <= 0:
        # Negative edge: never size up; report 0 so allocators can throttle.
        return 0.0
    return round(f_star * fraction, 4)
