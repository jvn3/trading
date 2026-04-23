"""SmartCopyStrategy — trade congressional clusters.

Entries: one market-buy intent per new cluster signal with score >= 0.45, up
to :attr:`max_concurrent_positions` open at a time, no duplicates.

Exits (managed in software, since Alpaca doesn't support stop orders on
fractional positions):
- Hard stop: ``unrealized_plpc <= -0.08``
- Trail activation: once ``unrealized_plpc >= +0.10``, ``trail_active = True``
- Trail update: each tick, ``trail_peak = max(trail_peak, current_price)``
- Trail exit: if active and ``current_price <= trail_peak * (1 - 0.05)``
- Signal reversal: 2+ same-ticker, opposite-direction politician trades
  filed in the last 14 days → close.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from jay_trading.data import models
from jay_trading.data.db import session_scope
from jay_trading.signals import confluence
from jay_trading.strategies.base import (
    PortfolioSnapshot,
    PositionView,
    SignalView,
    Strategy,
    TradeIntent,
)

log = logging.getLogger(__name__)

# Lowered from 0.5 → 0.45 on 2026-04-22 so 2-politician clusters with a
# positive avg quality (max plain score 0.48) can clear the bar. See
# development/log.md 2026-04-22 — "knobs" change.
SCORE_THRESHOLD = 0.45
HARD_STOP_PCT = -0.08
TRAIL_ACTIVATE_PCT = 0.10
TRAIL_GIVE_BACK_PCT = 0.05
REVERSAL_LOOKBACK_DAYS = 14
REVERSAL_MIN_MEMBERS = 2


class SmartCopyStrategy(Strategy):
    name = "smart_copy"
    enabled = True
    shadow_mode = False  # user override: go live paper immediately
    max_concurrent_positions = 10

    def generate_intents(
        self,
        signals: list[SignalView],
        portfolio: PortfolioSnapshot,
    ) -> list[TradeIntent]:
        if not self.enabled:
            return []
        intents: list[TradeIntent] = []
        open_for_me = portfolio.positions_for(self.name)
        if len(open_for_me) >= self.max_concurrent_positions:
            log.info(
                "smart_copy: at concurrency cap (%d/%d); skipping entries",
                len(open_for_me),
                self.max_concurrent_positions,
            )
            return []

        slots_remaining = self.max_concurrent_positions - len(open_for_me)
        # Rank signals strongest-first so the cap selects best-scored clusters.
        for sig in sorted(signals, key=lambda s: s.score, reverse=True):
            if slots_remaining <= 0:
                break
            if sig.strategy_name != self.name:
                continue
            if sig.score < SCORE_THRESHOLD:
                continue
            if sig.direction != "long":
                # Shorting paper: punt for now. The plan's smart_copy is long-only.
                continue
            if portfolio.holds(sig.ticker):
                continue
            mult = confluence.multiplier_for_ticker(sig.ticker, my_strategy=self.name)
            notional_pct = 0.05 * mult
            intents.append(
                TradeIntent(
                    strategy_name=self.name,
                    ticker=sig.ticker,
                    side="buy",
                    notional=round(portfolio.equity * notional_pct, 2),  # sizer may cap further
                    signal_id=sig.id,
                    rationale={**sig.rationale, "confluence_multiplier": mult},
                    action="open",
                )
            )
            slots_remaining -= 1
        return intents

    def manage_positions(
        self,
        positions: list[PositionView],
        portfolio: PortfolioSnapshot,
    ) -> list[TradeIntent]:
        intents: list[TradeIntent] = []
        for p in positions:
            if p.strategy_name != self.name:
                continue
            # 1. Hard stop
            if p.unrealized_plpc <= HARD_STOP_PCT:
                intents.append(self._close(p, reason="hard_stop"))
                continue
            # 2. Trail management
            if p.unrealized_plpc >= TRAIL_ACTIVATE_PCT:
                # Once activated, any drop of TRAIL_GIVE_BACK_PCT from peak exits.
                peak = max(p.trail_peak or p.current_price, p.current_price)
                if p.current_price <= peak * (1 - TRAIL_GIVE_BACK_PCT):
                    intents.append(self._close(p, reason="trail_stop"))
                    continue
            # 3. Signal reversal (explicit opposite cluster in recent filings)
            if _reversal_detected(p.ticker, REVERSAL_LOOKBACK_DAYS, REVERSAL_MIN_MEMBERS):
                intents.append(self._close(p, reason="signal_reversal"))
                continue
        return intents

    # -- helpers --

    def _close(self, p: PositionView, reason: str) -> TradeIntent:
        return TradeIntent(
            strategy_name=self.name,
            ticker=p.ticker,
            side="sell",
            qty=abs(p.qty),
            signal_id=p.entry_signal_id,
            rationale={"exit_reason": reason, "entry_signal_id": p.entry_signal_id},
            action="close",
        )


def _reversal_detected(
    ticker: str, lookback_days: int = REVERSAL_LOOKBACK_DAYS, min_members: int = 2
) -> bool:
    """True if ≥ ``min_members`` distinct politicians filed *sell* trades on
    ``ticker`` in the last ``lookback_days`` days.
    """
    since = date.today() - timedelta(days=lookback_days)
    with session_scope() as s:
        stmt = (
            select(models.DisclosedTrade.person_name)
            .where(models.DisclosedTrade.ticker == ticker.upper())
            .where(models.DisclosedTrade.source.in_(("senate", "house")))
            .where(models.DisclosedTrade.filing_date >= since)
            .where(models.DisclosedTrade.transaction_type == "sell")
            .distinct()
        )
        distinct_names = list(s.scalars(stmt))
    return len(distinct_names) >= min_members
