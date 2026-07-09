"""Reconciliation (S1.6): replay the fill history and compare against stored state.

Positions and cash are *derived* state; fills (plus starting equity) are the truth. Any
divergence means a bug or tampering — it raises a ``reconcile_discrepancy`` risk event and is
journaled. Reconciliation never "fixes" state silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from alphadash.db.models import (
    Account,
    CashBalance,
    Fill,
    JournalEntryType,
    Order,
    OrderSide,
    Position,
    RiskEvent,
    RiskEventType,
)
from alphadash.services import journal

ZERO = Decimal("0")


@dataclass(frozen=True)
class Discrepancy:
    kind: str  # "position_qty" | "cash" | "unknown_position"
    symbol: str | None
    expected: Decimal
    actual: Decimal

    def as_json(self) -> dict:
        return {
            "kind": self.kind,
            "symbol": self.symbol,
            "expected": str(self.expected),
            "actual": str(self.actual),
        }


def replay_fills(session: Session, account: Account) -> tuple[dict[str, Decimal], Decimal]:
    """Expected (positions qty by symbol, cash) from starting equity + every fill, in order."""
    expected_qty: dict[str, Decimal] = {}
    expected_cash = account.starting_equity
    rows = session.execute(
        select(Fill, Order)
        .join(Order, Fill.order_id == Order.id)
        .where(Order.account_id == account.id)
        .order_by(Fill.filled_at, Fill.id)
    ).all()
    for fill, order in rows:
        notional = fill.qty * fill.price
        if order.side is OrderSide.buy:
            expected_cash -= notional + fill.fee
            expected_qty[order.symbol] = expected_qty.get(order.symbol, ZERO) + fill.qty
        else:
            expected_cash += notional - fill.fee
            expected_qty[order.symbol] = expected_qty.get(order.symbol, ZERO) - fill.qty
    return {s: q for s, q in expected_qty.items() if q != ZERO}, expected_cash


def reconcile_account(session: Session, account: Account) -> list[Discrepancy]:
    """Compare replayed truth vs stored positions/cash. Discrepancies → risk_events + journal."""
    expected_qty, expected_cash = replay_fills(session, account)

    stored_positions = {
        p.symbol: p
        for p in session.scalars(select(Position).where(Position.account_id == account.id))
    }
    discrepancies: list[Discrepancy] = []

    for symbol, qty in expected_qty.items():
        stored = stored_positions.get(symbol)
        actual = stored.quantity if stored else ZERO
        if actual != qty:
            discrepancies.append(Discrepancy("position_qty", symbol, qty, actual))
    for symbol, stored in stored_positions.items():
        if symbol not in expected_qty:
            discrepancies.append(Discrepancy("unknown_position", symbol, ZERO, stored.quantity))

    actual_cash = session.scalar(
        select(CashBalance).where(
            CashBalance.account_id == account.id, CashBalance.currency == account.base_currency
        )
    )
    actual_cash_amount = actual_cash.amount if actual_cash else ZERO
    if actual_cash_amount != expected_cash:
        discrepancies.append(Discrepancy("cash", None, expected_cash, actual_cash_amount))

    for d in discrepancies:
        event = RiskEvent(
            account_id=account.id,
            event_type=RiskEventType.reconcile_discrepancy,
            detail=d.as_json(),
        )
        session.add(event)
        session.flush()
        journal.record(
            session,
            account_id=account.id,
            entry_type=JournalEntryType.risk_event,
            ref_id=event.id,
            payload={"event": "reconcile_discrepancy", **d.as_json()},
        )
    return discrepancies
