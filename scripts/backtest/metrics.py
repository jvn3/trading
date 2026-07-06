"""Pure performance metrics over an equity curve (pandas Series).

Conventions:
- ``equity`` is a cumulative equity curve (e.g. starts at 1.0), one row per
  trading day. Index may be a DatetimeIndex (CAGR uses calendar time) or a
  plain RangeIndex (CAGR assumes 252 rows per year).
- ``weights`` (for exposure/turnover) is a DataFrame of daily portfolio
  weights, one column per asset; cash is the implicit remainder.
- ``max_drawdown`` is returned as a negative number (e.g. -0.35 for -35%).
"""
from __future__ import annotations

import math

import pandas as pd

TRADING_DAYS_PER_YEAR = 252


def _years(index: pd.Index) -> float:
    """Span of an index in years; calendar-based for dates, 252/yr otherwise."""
    if len(index) < 2:
        return 1.0 / TRADING_DAYS_PER_YEAR
    if isinstance(index, pd.DatetimeIndex):
        days = (index[-1] - index[0]).days
        return max(days, 1) / 365.25
    return (len(index) - 1) / TRADING_DAYS_PER_YEAR


def cagr(equity: pd.Series) -> float:
    """Compound annual growth rate of the equity curve."""
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return 0.0
    total = float(equity.iloc[-1] / equity.iloc[0])
    if total <= 0:
        return -1.0
    return total ** (1.0 / _years(equity.index)) - 1.0


def sharpe(equity: pd.Series) -> float:
    """Annualized Sharpe ratio (rf=0): daily mean/std scaled by sqrt(252).

    Returns 0.0 when the return std is zero/undefined (flat or too-short curve).
    """
    rets = equity.pct_change().dropna()
    if len(rets) < 2:
        return 0.0
    sd = float(rets.std())
    # Treat float-noise-level std as zero volatility (real daily stds are ~1e-3+).
    if math.isnan(sd) or sd < 1e-12:
        return 0.0
    return float(rets.mean()) / sd * math.sqrt(TRADING_DAYS_PER_YEAR)


def max_drawdown(equity: pd.Series) -> float:
    """Worst peak-to-trough drawdown, as a negative fraction."""
    if len(equity) == 0:
        return 0.0
    dd = equity / equity.cummax() - 1.0
    return float(dd.min())


def exposure(weights: pd.DataFrame) -> float:
    """Fraction of days with any position on (i.e. not 100% cash)."""
    if len(weights) == 0:
        return 0.0
    gross = weights.abs().sum(axis=1)
    return float((gross > 1e-12).mean())


def turnover(weights: pd.DataFrame) -> float:
    """Annualized turnover: sum of |weight changes| per year.

    The first row counts as a trade from all-cash into the initial weights.
    A strategy that buys 100% once and holds for 10 years has turnover ~0.1/yr.
    """
    if len(weights) == 0:
        return 0.0
    deltas = weights.diff()
    deltas.iloc[0] = weights.iloc[0]
    total = float(deltas.abs().sum().sum())
    return total / _years(weights.index)


def summary(equity: pd.Series, name: str, weights: pd.DataFrame | None = None) -> dict:
    """One-row report dict for a strategy/benchmark equity curve."""
    out = {
        "name": name,
        "cagr": cagr(equity),
        "sharpe": sharpe(equity),
        "max_drawdown": max_drawdown(equity),
        "exposure": exposure(weights) if weights is not None else 1.0,
        "turnover": turnover(weights) if weights is not None else 0.0,
    }
    return out
