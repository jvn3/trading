"""Behavioral feedback (S3.4): deterministic nudges from the account's own trade history.

Two rules, both replayable from fills (no LLM, no clock inside the logic — ``now`` injected):

- **overtrading** — trades this week at ≥80% of ``max_trades_per_week`` (warn) or at/over the
  limit (stop). Churn is the classic beginner mistake; the limit exists to be felt early.
- **loss chasing** — a buy within 48h after a sell that realized a loss. Average cost is
  replayed fill-by-fill, so "realized a loss" is computed, not guessed.

Nudges teach; they never block (blocking is the risk layer's job, S1.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from alphadash.db.models import Account, Fill, Order, OrderSide
from alphadash.domain.risk import RiskLimitSet
from alphadash.services.execution import week_start

LOSS_CHASE_WINDOW = timedelta(hours=48)
OVERTRADE_WARN_RATIO = Decimal("0.8")
ZERO = Decimal("0")


@dataclass(frozen=True)
class Nudge:
    kind: str  # "overtrading" | "loss_chasing"
    severity: str  # "info" | "warn"
    message: str


def _as_utc(dt: datetime, now: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=now.tzinfo)


def _overtrading(
    session: Session, account: Account, limits: RiskLimitSet, now: datetime
) -> Nudge | None:
    if not limits.max_trades_per_week:
        return None
    trades = session.scalar(
        select(func.count(Fill.id))
        .join(Order, Fill.order_id == Order.id)
        .where(Order.account_id == account.id, Fill.filled_at >= week_start(now))
    )
    count = int(trades or 0)
    limit = limits.max_trades_per_week
    if count >= limit:
        return Nudge(
            kind="overtrading",
            severity="warn",
            message=(
                f"You've made {count} of your {limit} trades this week. "
                "More activity rarely means better results — the limit is there to protect "
                "you from churn."
            ),
        )
    if Decimal(count) >= Decimal(limit) * OVERTRADE_WARN_RATIO:
        return Nudge(
            kind="overtrading",
            severity="info",
            message=(
                f"{count} of {limit} weekly trades used. Consider letting your existing "
                "positions work instead of adding more."
            ),
        )
    return None


def _loss_chasing(session: Session, account: Account, now: datetime) -> Nudge | None:
    fills = session.execute(
        select(Fill, Order)
        .join(Order, Fill.order_id == Order.id)
        .where(Order.account_id == account.id)
        .order_by(Fill.filled_at, Fill.id)
    ).all()

    # Replay average cost per symbol to date each sell's realized P/L honestly.
    qty: dict[str, Decimal] = {}
    avg_cost: dict[str, Decimal] = {}
    last_loss_sell: datetime | None = None
    trigger: tuple[datetime, datetime, str] | None = None  # (buy_at, loss_at, buy_symbol)

    for fill, order in fills:
        at = _as_utc(fill.filled_at, now)
        symbol = order.symbol
        if order.side is OrderSide.buy:
            if last_loss_sell is not None and at - last_loss_sell <= LOSS_CHASE_WINDOW:
                trigger = (at, last_loss_sell, symbol)
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
            if cost > 0 and fill.price < cost:
                last_loss_sell = at
            qty[symbol] = qty.get(symbol, ZERO) - fill.qty

    # Only nudge about recent behavior — a months-old pattern isn't feedback, it's nagging.
    if trigger is not None and now - trigger[0] <= LOSS_CHASE_WINDOW * 2:
        return Nudge(
            kind="loss_chasing",
            severity="warn",
            message=(
                "You bought shortly after selling at a loss. Buying to 'win it back' is one of "
                "the most common (and expensive) reflexes in investing — consider waiting a day "
                "and re-reading the evidence first."
            ),
        )
    return None


def analyze(
    session: Session, *, account: Account, limits: RiskLimitSet, now: datetime
) -> list[Nudge]:
    nudges = [
        _overtrading(session, account, limits, now),
        _loss_chasing(session, account, now),
    ]
    return [n for n in nudges if n is not None]
