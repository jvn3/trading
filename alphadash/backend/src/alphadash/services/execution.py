"""Paper execution engine (S1.5).

Deterministic, idempotent, journaled. The flow for every order:

    idempotency check → Order(pending) → risk gate (S1.3) → veto? rejected + risk_event
                                                     → allow? simulated fill → positions/cash updated

Slippage model (frozen): market orders fill at quote ± ``SLIPPAGE_BPS`` (adverse); limit orders
must be marketable now (buy: limit ≥ quote, sell: limit ≤ quote) — the slipped price is clamped
to the limit so a fill can never violate it. Non-marketable limits are REJECTED with a teaching
reason (Phase 1 has no resting book; S4.x could add one). Fees are 0 in paper mode.

Everything time-based is injected (``now``); the current price is injected (``quote_price``) —
this module never touches a provider.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from alphadash.db.models import (
    Account,
    CashBalance,
    Fill,
    JournalEntryType,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    RiskEvent,
    RiskEventType,
)
from alphadash.domain.risk import (
    AccountState,
    Decision,
    OrderIntent,
    PositionState,
    RiskLimitSet,
    validate_order,
)
from alphadash.services import journal

SLIPPAGE_BPS = Decimal("5")  # 0.05% adverse on market orders
TEN_THOUSAND = Decimal("10000")
CENT = Decimal("0.01")
QTY_STEP = Decimal("0.00000001")


@dataclass(frozen=True)
class ExecutionResult:
    order: Order
    fill: Fill | None
    decision: Decision | None  # None when the order was an idempotent replay
    replayed: bool = False


def week_start(now: datetime) -> datetime:
    monday = (now - timedelta(days=now.weekday())).date()
    return datetime(monday.year, monday.month, monday.day, tzinfo=UTC)


def build_account_state(
    session: Session,
    account: Account,
    prices: dict[str, Decimal],
    *,
    now: datetime,
    drawdown_pct: Decimal = Decimal("0"),
    paused: bool = False,
) -> AccountState:
    """Assemble the risk-gate view of an account from DB rows + injected prices."""
    positions: dict[str, PositionState] = {}
    for row in session.scalars(select(Position).where(Position.account_id == account.id)):
        price = prices.get(row.symbol)
        market_value = row.quantity * price if price is not None else row.quantity * row.avg_cost
        positions[row.symbol] = PositionState(
            symbol=row.symbol,
            asset_class=row.asset_class,
            quantity=row.quantity,
            market_value=market_value,
        )
    cash = session.scalar(
        select(func.coalesce(func.sum(CashBalance.amount), 0)).where(
            CashBalance.account_id == account.id, CashBalance.currency == account.base_currency
        )
    )
    cash = Decimal(cash)
    equity = cash + sum((p.market_value for p in positions.values()), Decimal("0"))
    trades = session.scalar(
        select(func.count(Fill.id))
        .join(Order, Fill.order_id == Order.id)
        .where(Order.account_id == account.id, Fill.filled_at >= week_start(now))
    )
    return AccountState(
        equity=equity,
        cash=cash,
        positions=positions,
        trades_this_week=int(trades or 0),
        drawdown_pct=drawdown_pct,
        paused=paused,
    )


def _fill_price(
    side: OrderSide, order_type: OrderType, quote_price: Decimal, limit_price: Decimal | None
) -> Decimal | None:
    """Simulated fill price, or None when a limit order is not marketable."""
    slip = quote_price * SLIPPAGE_BPS / TEN_THOUSAND
    slipped = quote_price + slip if side is OrderSide.buy else quote_price - slip
    if order_type is OrderType.market:
        return slipped
    assert limit_price is not None
    if side is OrderSide.buy:
        return min(slipped, limit_price) if limit_price >= quote_price else None
    return max(slipped, limit_price) if limit_price <= quote_price else None


def place_order(
    session: Session,
    *,
    account: Account,
    symbol: str,
    asset_class,
    side: OrderSide,
    order_type: OrderType,
    qty: Decimal,
    quote_price: Decimal,
    limits: RiskLimitSet,
    idempotency_key: str,
    now: datetime,
    limit_price: Decimal | None = None,
    suggestion_id: str | None = None,
    drawdown_pct: Decimal = Decimal("0"),
    paused: bool = False,
) -> ExecutionResult:
    """Run one order through the full lifecycle. Caller commits."""
    if order_type is OrderType.limit and limit_price is None:
        raise ValueError("limit orders require limit_price")

    # --- Idempotency: same key → return the original outcome, do nothing ---
    existing = session.scalar(select(Order).where(Order.idempotency_key == idempotency_key))
    if existing is not None:
        fill = session.scalar(select(Fill).where(Fill.order_id == existing.id))
        return ExecutionResult(order=existing, fill=fill, decision=None, replayed=True)

    order = Order(
        account_id=account.id,
        symbol=symbol.upper(),
        asset_class=asset_class,
        side=side,
        order_type=order_type,
        qty=qty,
        limit_price=limit_price,
        status=OrderStatus.pending,
        idempotency_key=idempotency_key,
        suggestion_id=suggestion_id,
    )
    session.add(order)
    session.flush()
    journal.record(
        session,
        account_id=account.id,
        entry_type=JournalEntryType.order,
        ref_id=order.id,
        payload={
            "event": "submitted",
            "symbol": order.symbol,
            "side": side.value,
            "order_type": order_type.value,
            "qty": str(qty),
            "limit_price": str(limit_price) if limit_price is not None else None,
            "at": now.isoformat(),
        },
    )

    # --- Risk gate (S1.3) — validated against the effective (limit or slipped) price ---
    state = build_account_state(
        session,
        account,
        prices={symbol.upper(): quote_price},
        now=now,
        drawdown_pct=drawdown_pct,
        paused=paused,
    )
    gate_price = limit_price if order_type is OrderType.limit else quote_price
    intent = OrderIntent(
        symbol=symbol.upper(), asset_class=asset_class, side=side, qty=qty, price=gate_price
    )
    decision = validate_order(intent, state, limits)

    if not decision.allow:
        order.status = OrderStatus.rejected
        order.rejected_reason = decision.reason[:500]
        risk_event = RiskEvent(
            account_id=account.id,
            event_type=RiskEventType.veto,
            detail={"violations": [v.message for v in decision.violations]},
            order_id=order.id,
            suggestion_id=suggestion_id,
        )
        session.add(risk_event)
        session.flush()
        journal.record(
            session,
            account_id=account.id,
            entry_type=JournalEntryType.risk_event,
            ref_id=risk_event.id,
            payload={"event": "veto", "order_id": order.id, "reason": decision.reason},
        )
        return ExecutionResult(order=order, fill=None, decision=decision)

    order.status = OrderStatus.validated

    fill_price = _fill_price(side, order_type, quote_price, limit_price)
    if fill_price is None:
        order.status = OrderStatus.rejected
        order.rejected_reason = (
            f"limit not marketable: {side.value} limit {limit_price} vs market {quote_price} "
            "(paper mode fills immediately or not at all)"
        )
        journal.record(
            session,
            account_id=account.id,
            entry_type=JournalEntryType.order,
            ref_id=order.id,
            payload={"event": "rejected", "reason": order.rejected_reason},
        )
        return ExecutionResult(order=order, fill=None, decision=decision)

    fill_price = fill_price.quantize(CENT)
    fill = Fill(order_id=order.id, qty=qty, price=fill_price, fee=Decimal("0"), filled_at=now)
    session.add(fill)
    order.status = OrderStatus.filled
    _apply_fill(session, account, order, fill)
    session.flush()
    journal.record(
        session,
        account_id=account.id,
        entry_type=JournalEntryType.fill,
        ref_id=fill.id,
        payload={
            "order_id": order.id,
            "symbol": order.symbol,
            "side": side.value,
            "qty": str(qty),
            "price": str(fill_price),
            "fee": "0",
            "at": now.isoformat(),
        },
    )
    return ExecutionResult(order=order, fill=fill, decision=decision)


def _apply_fill(session: Session, account: Account, order: Order, fill: Fill) -> None:
    """Update position (weighted avg cost) and cash for a fill."""
    notional = fill.qty * fill.price
    cash = session.scalar(
        select(CashBalance).where(
            CashBalance.account_id == account.id, CashBalance.currency == account.base_currency
        )
    )
    if cash is None:
        raise RuntimeError(f"account {account.id} has no {account.base_currency} cash balance")

    position = session.scalar(
        select(Position).where(Position.account_id == account.id, Position.symbol == order.symbol)
    )

    if order.side is OrderSide.buy:
        cash.amount -= notional + fill.fee
        if position is None:
            position = Position(
                account_id=account.id,
                symbol=order.symbol,
                asset_class=order.asset_class,
                quantity=fill.qty,
                avg_cost=fill.price,
            )
            session.add(position)
        else:
            total_cost = position.quantity * position.avg_cost + notional
            position.quantity += fill.qty
            position.avg_cost = total_cost / position.quantity
    else:
        cash.amount += notional - fill.fee
        if position is None or position.quantity < fill.qty:
            raise RuntimeError(
                "sell fill without sufficient position (risk gate must prevent this)"
            )
        position.quantity -= fill.qty
        if position.quantity == 0:
            session.delete(position)
