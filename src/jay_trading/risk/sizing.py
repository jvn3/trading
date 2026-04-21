"""Position sizing + per-strategy concurrency guard.

This is the only risk check the user opted to keep beyond paper-URL and the
per-strategy ``enabled`` flag. No circuit breakers, no sector heat, no
correlation check — those are reserved for a later risk layer.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from jay_trading.strategies.base import PortfolioSnapshot, TradeIntent

log = logging.getLogger(__name__)

DEFAULT_TARGET_PCT = 0.05  # 5% of equity per trade
DEFAULT_HARD_CAP_PCT = 0.10  # 10% absolute maximum
DEFAULT_MAX_CONCURRENT = 10


@dataclass
class SizingDecision:
    verdict: str  # "APPROVE" | "REJECT" | "MODIFY"
    intent: TradeIntent | None
    reason: str = ""


def size_intent(
    intent: TradeIntent,
    portfolio: PortfolioSnapshot,
    target_pct: float = DEFAULT_TARGET_PCT,
    hard_cap_pct: float = DEFAULT_HARD_CAP_PCT,
    max_concurrent: int = DEFAULT_MAX_CONCURRENT,
) -> SizingDecision:
    """Apply position-size cap + concurrency cap to an *open*-action intent.

    Close / adjust intents are passed through unchanged.
    """
    if intent.action != "open":
        return SizingDecision("APPROVE", intent)

    # Concurrency cap
    open_same_strategy = [
        p for p in portfolio.positions if p.strategy_name == intent.strategy_name
    ]
    if len(open_same_strategy) >= max_concurrent:
        return SizingDecision(
            "REJECT",
            None,
            reason=f"concurrency cap: {len(open_same_strategy)} >= {max_concurrent}",
        )

    # Don't double-buy a ticker we already hold
    if portfolio.holds(intent.ticker):
        return SizingDecision(
            "REJECT", None, reason=f"already holding {intent.ticker}"
        )

    # Don't spend more cash than we have (paper accounts are more lenient but
    # rejections are cheap; real orders would bounce).
    if intent.notional is not None:
        target_notional = intent.notional
    else:
        # Convert qty to notional using current price if supplied, else skip.
        target_notional = None

    target_from_equity = round(portfolio.equity * target_pct, 2)
    hard_cap = round(portfolio.equity * hard_cap_pct, 2)

    # If the caller didn't pick a size, default to target_pct of equity.
    if target_notional is None:
        target_notional = target_from_equity

    # Never exceed hard cap.
    target_notional = min(target_notional, hard_cap)

    # Cash availability sanity: leave a small buffer.
    if target_notional > portfolio.cash * 0.98:
        target_notional = round(portfolio.cash * 0.95, 2)

    # Discard intents that collapse to near-zero (less than $10 is noise).
    if target_notional < 10:
        return SizingDecision(
            "REJECT",
            None,
            reason=f"computed notional too small: ${target_notional:.2f}",
        )

    if intent.notional is not None and abs(intent.notional - target_notional) < 0.01:
        return SizingDecision("APPROVE", intent)

    # Emit a modified intent with the capped notional.
    from dataclasses import replace

    modified = replace(intent, notional=target_notional, qty=None)
    return SizingDecision("MODIFY", modified, reason="notional capped to sizing policy")
