"""Honest performance review (S3.5).

Deterministic composition over the S1.7 performance series + a fill replay:
return is ALWAYS paired with the benchmark and drawdown, closed-trade stats carry a
small-sample caveat, and the disclaimers are part of the payload (not optional frontend
decoration). No naked returns leave this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from alphadash.db.models import Account, Fill, Order, OrderSide
from alphadash.providers.base import MarketDataProvider
from alphadash.services.portfolio import PerformanceReport, performance_series

ZERO = Decimal("0")
TWO_DP = Decimal("0.01")
SMALL_SAMPLE = 10

DISCLAIMERS = (
    "This is a simulated paper account — no real money is at risk and real-world fills, fees "
    "and taxes would differ.",
    "Past performance (simulated or real) does not predict future results.",
    "This is not investment advice.",
)


@dataclass(frozen=True)
class ClosedTradeStats:
    closed_trades: int
    wins: int
    losses: int
    win_rate_pct: Decimal | None  # None until at least one closed trade
    small_sample: bool


@dataclass(frozen=True)
class HonestReview:
    performance: PerformanceReport
    trades: ClosedTradeStats
    verdict: str  # plain-language, benchmark-relative framing
    disclaimers: tuple[str, ...]


def closed_trade_stats(session: Session, account: Account) -> ClosedTradeStats:
    """Replay fills; every sell realizes P/L against the replayed average cost."""
    fills = session.execute(
        select(Fill, Order)
        .join(Order, Fill.order_id == Order.id)
        .where(Order.account_id == account.id)
        .order_by(Fill.filled_at, Fill.id)
    ).all()

    qty: dict[str, Decimal] = {}
    avg_cost: dict[str, Decimal] = {}
    wins = losses = 0
    for fill, order in fills:
        symbol = order.symbol
        if order.side is OrderSide.buy:
            held = qty.get(symbol, ZERO)
            new_qty = held + fill.qty
            avg_cost[symbol] = (
                (avg_cost.get(symbol, ZERO) * held + fill.price * fill.qty) / new_qty
                if new_qty > 0
                else ZERO
            )
            qty[symbol] = new_qty
        else:
            cost = avg_cost.get(symbol, ZERO)
            if fill.price > cost:
                wins += 1
            else:
                losses += 1  # break-even counts against — honesty over flattery
            qty[symbol] = qty.get(symbol, ZERO) - fill.qty

    closed = wins + losses
    win_rate = (
        (Decimal(wins) / Decimal(closed) * Decimal("100")).quantize(TWO_DP) if closed else None
    )
    return ClosedTradeStats(
        closed_trades=closed,
        wins=wins,
        losses=losses,
        win_rate_pct=win_rate,
        small_sample=closed < SMALL_SAMPLE,
    )


def _verdict(report: PerformanceReport, trades: ClosedTradeStats) -> str:
    if not report.points:
        return "Not enough history yet for an honest verdict. That's fine — no data beats bad data."
    edge = report.return_pct - report.benchmark_return_pct
    if edge > 0:
        base = (
            f"You're ahead of {report.benchmark_symbol} by {edge.quantize(TWO_DP)} percentage "
            f"points over this period."
        )
        if trades.small_sample:
            base += (
                f" With only {trades.closed_trades} closed trade(s), luck and skill are still "
                "indistinguishable — don't scale up on this alone."
            )
        return base
    if edge < 0:
        return (
            f"Simply holding {report.benchmark_symbol} would have done better by "
            f"{(-edge).quantize(TWO_DP)} percentage points. That's normal while learning — "
            "the tuition here is simulated."
        )
    return f"You're exactly level with {report.benchmark_symbol} over this period."


def honest_review(
    session: Session,
    account: Account,
    market_data: MarketDataProvider,
    *,
    start: date,
    end: date,
) -> HonestReview:
    report = performance_series(session, account, market_data, start=start, end=end)
    trades = closed_trade_stats(session, account)
    return HonestReview(
        performance=report,
        trades=trades,
        verdict=_verdict(report, trades),
        disclaimers=DISCLAIMERS,
    )
