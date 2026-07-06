"""Sleeve allocator: per-strategy capital budgets, volatility targeting, and
regime-gated gross leverage.

This is the portfolio-engine-v2 layer from redesign-2026-07-05 §M6. The old
model sized every trade at a flat 5% of equity regardless of strategy; this
module gives each strategy (sleeve) a capital budget, scales the risky
sleeves by realized volatility toward a target, and bounds TOTAL gross
exposure by the macro regime — which is where the account's 4× buying power
gets used deliberately instead of ignored.

Design rules:
- Pure computation over a PortfolioSnapshot + cached prices. No API calls.
- Fail DOWN, not open: missing vol data → scale 1.0 (budget unscaled);
  unknown regime → the conservative 0.75× gross cap, mirroring the stale-
  regime sizing multiplier in schedule/jobs.py.
- Kelly sizing (risk/kelly.py) activates per-sleeve once the fills ledger
  holds >= KELLY_MIN_TRADES closed trades; until then budgets are static.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta

from jay_trading.risk import kelly
from jay_trading.strategies.base import PortfolioSnapshot

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SleevePolicy:
    """Static per-strategy allocation policy."""

    budget_pct: float           # share of equity this sleeve may deploy
    per_position_cap_pct: float  # hard cap for ONE position in this sleeve
    target_vol: float | None = None   # annualized; None = no vol scaling
    vol_ticker: str | None = None     # instrument whose realized vol we scale by


# Sleeve budgets per redesign-2026-07-05 Part 1 Q2 table. smart_copy /
# insider_follow are demoted to a combined 10% "conviction tilt" pending
# their backtest verdict; the reserve (~35%) is cash for S2/PEAD later.
#
# target_vol is None EVERYWHERE by verdict of the vol-target study
# (scripts/backtest/studies/vol_target_s1.py, verified 2026-07-07): on
# S1-TQQQ the overlay was Sharpe-neutral at best while costing 3-15 CAGR
# points in every walk-forward window — the wrong trade under a max-return
# objective. If a drawdown-control knob is ever wanted, the studied setting
# is target_vol=0.45 with the scale capped at 1.0 (cuts 2020 DD from -55%
# to -34% for ~4 CAGR pts). The machinery below stays tested and ready.
SLEEVES: dict[str, SleevePolicy] = {
    "s1_rotation": SleevePolicy(
        budget_pct=0.45, per_position_cap_pct=0.50,
        target_vol=None, vol_ticker="TQQQ",
    ),
    "crypto_momentum": SleevePolicy(
        budget_pct=0.15, per_position_cap_pct=0.10,
        target_vol=None, vol_ticker=None,
    ),
    "smart_copy": SleevePolicy(budget_pct=0.05, per_position_cap_pct=0.10),
    "insider_follow": SleevePolicy(budget_pct=0.05, per_position_cap_pct=0.10),
}

DEFAULT_POLICY = SleevePolicy(budget_pct=0.05, per_position_cap_pct=0.10)

# Total gross exposure allowed as a multiple of equity, by macro regime.
# FULL_RISK_ON deliberately uses margin (the account has 4x buying power;
# we cap ourselves at 1.5x). None/unknown regime gets the cautious middle.
GROSS_LEVERAGE_CAP: dict[str | None, float] = {
    "FULL_RISK_ON": 1.5,
    "MODERATE_RISK_ON": 1.0,
    "RISK_OFF_DEFENSIVE": 0.6,
    "RISK_OFF_CRISIS": 0.0,
    None: 0.75,
}

VOL_SCALE_MIN = 0.3
VOL_SCALE_MAX = 1.5
VOL_LOOKBACK_DAYS = 20
KELLY_MIN_TRADES = 20


@dataclass(frozen=True)
class SleeveDecision:
    """What the sizer needs to bound one intent from this sleeve."""

    strategy_name: str
    cap_dollars: float          # total capital this sleeve may hold right now
    sleeve_exposure: float      # market value the sleeve already holds
    max_spend: float            # dollars available for NEW exposure (all caps)
    per_position_cap_pct: float
    vol_scale: float
    kelly_fraction: float | None  # informational until ledger matures


def realized_vol(ticker: str, *, lookback: int = VOL_LOOKBACK_DAYS) -> float | None:
    """Annualized realized vol from cached daily closes; None if insufficient."""
    from jay_trading.data.price_cache import get_closes

    closes = get_closes(ticker, date.today() - timedelta(days=lookback * 2 + 10))
    if len(closes) < lookback + 1:
        return None
    prices = [c for _, c in closes][-(lookback + 1):]
    rets = [prices[i] / prices[i - 1] - 1.0 for i in range(1, len(prices))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(1, len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252)


def _vol_scale(policy: SleevePolicy, vol_ticker: str | None) -> float:
    ticker = vol_ticker or policy.vol_ticker
    if policy.target_vol is None or ticker is None:
        return 1.0
    rv = realized_vol(ticker)
    if rv is None or rv <= 0:
        return 1.0  # no data → unscaled budget, never a boost
    return max(VOL_SCALE_MIN, min(VOL_SCALE_MAX, policy.target_vol / rv))


def sleeve_cap(
    strategy_name: str,
    portfolio: PortfolioSnapshot,
    regime_name: str | None,
    *,
    vol_ticker: str | None = None,
) -> SleeveDecision:
    """Compute the sleeve's current capital cap and spend headroom.

    ``max_spend`` is the binding constraint the sizer applies to a new open:
    min(sleeve headroom, regime gross-leverage headroom, 95% buying power).
    """
    policy = SLEEVES.get(strategy_name, DEFAULT_POLICY)
    scale = _vol_scale(policy, vol_ticker)
    cap = portfolio.equity * policy.budget_pct * scale

    exposure = sum(
        abs(p.market_value)
        for p in portfolio.positions
        if p.strategy_name == strategy_name
    )
    headroom_sleeve = max(0.0, cap - exposure)

    gross = sum(abs(p.market_value) for p in portfolio.positions)
    gross_cap_mult = GROSS_LEVERAGE_CAP.get(regime_name, GROSS_LEVERAGE_CAP[None])
    headroom_gross = max(0.0, portfolio.equity * gross_cap_mult - gross)

    max_spend = round(
        min(headroom_sleeve, headroom_gross, portfolio.buying_power * 0.95), 2
    )

    kf = kelly.kelly_fraction(strategy_name, min_trades=KELLY_MIN_TRADES)
    if kf is not None:
        # Informational until we trust the sample; wiring kf into cap is the
        # documented follow-up once every sleeve has >= KELLY_MIN_TRADES.
        log.info("kelly[%s]=%.3f (ledger-based, not yet applied)", strategy_name, kf)

    return SleeveDecision(
        strategy_name=strategy_name,
        cap_dollars=round(cap, 2),
        sleeve_exposure=round(exposure, 2),
        max_spend=max_spend,
        per_position_cap_pct=policy.per_position_cap_pct,
        vol_scale=round(scale, 3),
        kelly_fraction=kf,
    )
