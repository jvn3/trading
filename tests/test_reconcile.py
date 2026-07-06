"""Reconcile tests: fills ledger, position lifecycle (close-not-delete),
idempotency. This path was 0%-covered while it silently lost all realized
P&L (audit-2026-07-05); these tests pin the fixed behavior.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select

from jay_trading.data import models
from jay_trading.data.db import create_all, session_scope
from jay_trading.executor.reconcile import reconcile_orders_and_positions


def _order(
    cid: str,
    *,
    symbol: str,
    side: str,
    status: str = "filled",
    fill_price: float | None = None,
    fill_qty: float | None = None,
    oid: str = "alp-1",
) -> SimpleNamespace:
    return SimpleNamespace(
        client_order_id=cid,
        id=oid,
        status=status,
        side=side,
        symbol=symbol,
        filled_avg_price=fill_price,
        filled_qty=fill_qty,
        filled_at=datetime.now(timezone.utc),
    )


def _live_position(symbol: str, qty: float, entry: float, current: float) -> SimpleNamespace:
    return SimpleNamespace(
        symbol=symbol,
        qty=str(qty),
        avg_entry_price=str(entry),
        current_price=str(current),
    )


class _FakeRaw:
    def __init__(self, orders: list) -> None:
        self._orders = orders

    def get_orders(self, filter: object = None) -> list:  # noqa: A002
        return self._orders


class _FakeAlpaca:
    def __init__(self, orders: list, positions: list) -> None:
        self.raw = _FakeRaw(orders)
        self._positions = positions

    def get_positions(self) -> list:
        return self._positions


def _db_order(cid: str, ticker: str, side: str, strategy: str = "smart_copy") -> int:
    with session_scope() as s:
        row = models.Order(
            strategy_name=strategy,
            client_order_id=cid,
            ticker=ticker,
            side=side,
            order_type="market",
            notional=500.0,
            time_in_force="day",
            status="pending",
            submitted_at=datetime.now(timezone.utc),
        )
        s.add(row)
        s.flush()
        return int(row.id)


def test_filled_order_records_fill_row_idempotently() -> None:
    create_all()
    _db_order("cid-buy-1", "MSFT", "buy")
    alpaca = _FakeAlpaca(
        orders=[_order("cid-buy-1", symbol="MSFT", side="buy",
                       fill_price=400.0, fill_qty=1.25, oid="alp-buy-1")],
        positions=[_live_position("MSFT", 1.25, 400.0, 405.0)],
    )

    r1 = reconcile_orders_and_positions(alpaca=alpaca)
    r2 = reconcile_orders_and_positions(alpaca=alpaca)

    assert r1["fills_recorded"] == 1
    assert r2["fills_recorded"] == 0  # idempotent on alpaca_fill_id
    with session_scope() as s:
        fills = list(s.scalars(select(models.Fill)))
        assert len(fills) == 1
        assert fills[0].qty == 1.25
        assert fills[0].price == 400.0
        order_row = s.scalar(select(models.Order))
        assert fills[0].order_id == order_row.id


def test_closed_position_is_kept_with_realized_pnl() -> None:
    create_all()
    _db_order("cid-sell-1", "GLW", "sell")
    with session_scope() as s:
        s.add(
            models.Position(
                ticker="GLW",
                strategy_name="smart_copy",
                qty=2.0,
                avg_entry_price=168.0,
                opened_at=datetime.now(timezone.utc) - timedelta(days=10),
                trail_active=False,
            )
        )
    # Live positions now empty; a filled sell order explains the exit.
    alpaca = _FakeAlpaca(
        orders=[_order("cid-sell-1", symbol="GLW", side="OrderSide.SELL",
                       fill_price=195.0, fill_qty=2.0, oid="alp-sell-1")],
        positions=[],
    )

    result = reconcile_orders_and_positions(alpaca=alpaca)

    assert result["positions_closed"] == 1
    with session_scope() as s:
        row = s.scalar(select(models.Position))
        assert row is not None  # kept, not deleted
        assert row.closed_at is not None
        assert row.exit_price == 195.0
        assert row.realized_pnl == (195.0 - 168.0) * 2.0


def test_ticker_can_reopen_after_close_leaving_history() -> None:
    create_all()
    with session_scope() as s:
        s.add(
            models.Position(
                ticker="AAPL",
                strategy_name="smart_copy",
                qty=1.0,
                avg_entry_price=200.0,
                opened_at=datetime.now(timezone.utc) - timedelta(days=20),
                closed_at=datetime.now(timezone.utc) - timedelta(days=5),
                exit_price=210.0,
                realized_pnl=10.0,
                trail_active=False,
            )
        )
    _db_order("cid-buy-2", "AAPL", "buy", strategy="insider_follow")
    alpaca = _FakeAlpaca(
        orders=[],
        positions=[_live_position("AAPL", 3.0, 220.0, 221.0)],
    )

    reconcile_orders_and_positions(alpaca=alpaca)

    with session_scope() as s:
        rows = list(
            s.scalars(select(models.Position).order_by(models.Position.id))
        )
        assert len(rows) == 2
        closed, reopened = rows
        assert closed.closed_at is not None and closed.realized_pnl == 10.0
        assert reopened.closed_at is None
        assert reopened.qty == 3.0
        assert reopened.strategy_name == "insider_follow"


def test_close_without_sell_order_leaves_pnl_null() -> None:
    create_all()
    with session_scope() as s:
        s.add(
            models.Position(
                ticker="UNH",
                strategy_name="smart_copy",
                qty=1.0,
                avg_entry_price=355.0,
                opened_at=datetime.now(timezone.utc) - timedelta(days=3),
                trail_active=False,
            )
        )
    alpaca = _FakeAlpaca(orders=[], positions=[])

    result = reconcile_orders_and_positions(alpaca=alpaca)

    assert result["positions_closed"] == 1
    with session_scope() as s:
        row = s.scalar(select(models.Position))
        assert row.closed_at is not None
        assert row.exit_price is None
        assert row.realized_pnl is None
