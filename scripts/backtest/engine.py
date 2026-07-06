"""Vectorized daily-bar backtest engine.

Model:
- ``prices``: DataFrame of daily (adjusted) closes, one column per asset.
- ``weights``: DataFrame of TARGET portfolio weights decided at each day's
  close using information available that day. Rows must sum to <= 1.0; the
  remainder is cash earning 0.

NEXT-DAY CONVENTION (no lookahead): a weight decided at day t's close is held
DURING day t+1, i.e. it earns day t+1's close-to-close return. Implemented as
``weights.shift(1)``. A signal therefore can never earn the return of the bar
that produced it.

Costs: ``cost_bps`` basis points are charged on each day's turnover
(sum of |held_t - held_{t-1}| across assets), including the initial entry
from all-cash.
"""
from __future__ import annotations

import pandas as pd


def run_weights(prices: pd.DataFrame, weights: pd.DataFrame, cost_bps: float = 0.0) -> pd.Series:
    """Run target weights against daily closes; return the equity curve (starts at 1.0)."""
    if prices.empty:
        raise ValueError("prices is empty")
    unknown = set(weights.columns) - set(prices.columns)
    if unknown:
        raise ValueError(f"weights reference assets with no prices: {sorted(unknown)}")

    prices = prices.sort_index()
    weights = weights.reindex(index=prices.index, columns=prices.columns).fillna(0.0)

    if (weights < -1e-12).any().any():
        raise ValueError("negative weights not supported (long-only engine)")
    if (weights.sum(axis=1) > 1.0 + 1e-9).any():
        raise ValueError("weights rows must sum to <= 1.0 (remainder is cash)")

    # Next-day convention: the weight decided at day t's close is held during
    # day t+1. Day 0 is always flat (there is no prior signal).
    held = weights.shift(1).fillna(0.0)

    asset_rets = prices.pct_change().fillna(0.0)
    gross_ret = (held * asset_rets).sum(axis=1)

    # Turnover on the day a new target takes effect; first row is the move
    # from all-cash into the initial held weights.
    deltas = held.diff()
    deltas.iloc[0] = held.iloc[0]
    day_turnover = deltas.abs().sum(axis=1)
    costs = day_turnover * (cost_bps / 10_000.0)

    equity = (1.0 + gross_ret - costs).cumprod()
    equity.name = "equity"
    return equity
