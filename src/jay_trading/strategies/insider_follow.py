"""InsiderFollowStrategy — trade Form 4 P-Purchase clusters.

Parallels :class:`jay_trading.strategies.smart_copy.SmartCopyStrategy`
with the deltas from ``strategies/phase2_build_spec.md §4-§5``:

- Wider hard stop (-10% vs -8%): insider-buy signals are more conviction
  driven than politician-copy, give them room.
- Higher trail activation (+15% vs +10%): academic literature shows the
  insider-purchase drift runs 3-6 months.
- 90-day max hold: beyond that the alpha decays toward SPY beta.
- Insider-sell reversal exit: close on ≥ 2 officer sales in 30 days.
- Shadow mode default is False (user override, matching smart_copy).
- Concurrency starts at 5; raise to 10 after 20 closed trades.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
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

SCORE_THRESHOLD = 0.4
HARD_STOP_PCT = -0.10
TRAIL_ACTIVATE_PCT = 0.15
TRAIL_GIVE_BACK_PCT = 0.07
MAX_HOLD_DAYS = 90
REVERSAL_LOOKBACK_DAYS = 30
REVERSAL_MIN_OFFICER_SALES = 2


class InsiderFollowStrategy(Strategy):
    name = "insider_follow"
    enabled = True
    shadow_mode = False  # user override: go live paper immediately, matching smart_copy
    max_concurrent_positions = 5

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
                "insider_follow: at concurrency cap (%d/%d); skipping entries",
                len(open_for_me),
                self.max_concurrent_positions,
            )
            return []

        slots_remaining = self.max_concurrent_positions - len(open_for_me)
        for sig in sorted(signals, key=lambda s: s.score, reverse=True):
            if slots_remaining <= 0:
                break
            if sig.strategy_name != self.name:
                continue
            if sig.score < SCORE_THRESHOLD:
                continue
            if sig.direction != "long":
                continue
            if portfolio.holds(sig.ticker):
                continue

            # Confluence: if smart_copy has a signal on the same ticker in the
            # last 30 days, size up to 7.5% (base is 5%). Risk layer's hard
            # cap (10%) still applies via sizing.py.
            mult = confluence.multiplier_for_ticker(
                sig.ticker, my_strategy=self.name,
            )
            notional_pct = 0.05 * mult
            intents.append(TradeIntent(
                strategy_name=self.name,
                ticker=sig.ticker,
                side="buy",
                notional=round(portfolio.equity * notional_pct, 2),
                signal_id=sig.id,
                rationale={**sig.rationale, "confluence_multiplier": mult},
                action="open",
            ))
            slots_remaining -= 1
        return intents

    def manage_positions(
        self,
        positions: list[PositionView],
        portfolio: PortfolioSnapshot,  # noqa: ARG002 — same shape as smart_copy
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
                peak = max(p.trail_peak or p.current_price, p.current_price)
                if p.current_price <= peak * (1 - TRAIL_GIVE_BACK_PCT):
                    intents.append(self._close(p, reason="trail_stop"))
                    continue
            # 3. Max hold
            if p.opened_at is not None:
                held_days = (datetime.now(timezone.utc) - p.opened_at).days
                if held_days >= MAX_HOLD_DAYS:
                    intents.append(self._close(p, reason="max_hold"))
                    continue
            # 4. Insider-sell reversal
            if _insider_sell_reversal(
                p.ticker, REVERSAL_LOOKBACK_DAYS, REVERSAL_MIN_OFFICER_SALES,
            ):
                intents.append(self._close(p, reason="insider_sell_reversal"))
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


def _insider_sell_reversal(
    ticker: str,
    lookback_days: int = REVERSAL_LOOKBACK_DAYS,
    min_officer_sales: int = REVERSAL_MIN_OFFICER_SALES,
) -> bool:
    """True if ≥ ``min_officer_sales`` distinct insiders with officer/director
    role filed ``S-Sale`` transactions on ``ticker`` in the last ``lookback_days``.
    """
    since = date.today() - timedelta(days=lookback_days)
    with session_scope() as s:
        stmt = (
            select(models.DisclosedTrade.person_name, models.DisclosedTrade.person_role)
            .where(models.DisclosedTrade.ticker == ticker.upper())
            .where(models.DisclosedTrade.source == "insider")
            .where(models.DisclosedTrade.filing_date >= since)
            .where(models.DisclosedTrade.transaction_type == "sell")
            .distinct()
        )
        rows = list(s.execute(stmt).all())
    officer_names: set[str] = set()
    for name, role in rows:
        if not role:
            continue
        role_l = role.lower()
        if "officer" in role_l or "director" in role_l or "ceo" in role_l or "cfo" in role_l:
            officer_names.add(name)
    return len(officer_names) >= min_officer_sales
