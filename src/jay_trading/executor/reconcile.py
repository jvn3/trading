"""After orders have had a chance to fill, pull Alpaca's truth into our DB.

Run at 15:55 ET by the scheduler. Also triggered opportunistically after an
``execute_strategies`` pass so newly-opened Position rows exist for the next
``manage_positions`` tick.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select

from jay_trading.data import models
from jay_trading.data.alpaca_client import AlpacaPaperClient
from jay_trading.data.db import session_scope

log = logging.getLogger(__name__)


def _parse_dt(v: Any) -> datetime:
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc) if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def reconcile_orders_and_positions(alpaca: AlpacaPaperClient | None = None) -> dict[str, int]:
    alpaca = alpaca or AlpacaPaperClient()

    # 1. Pull today's orders from Alpaca, match by client_order_id, update status.
    today = date.today().isoformat()
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus

        req = GetOrdersRequest(status=QueryOrderStatus.ALL, after=today)
        orders = alpaca.raw.get_orders(filter=req)
    except Exception as e:  # noqa: BLE001
        log.warning("failed to pull orders from Alpaca: %s", e)
        orders = []

    updated = 0
    with session_scope() as s:
        for o in orders:
            cid = getattr(o, "client_order_id", None)
            if not cid:
                continue
            row = s.scalar(
                select(models.Order).where(models.Order.client_order_id == cid)
            )
            if row is None:
                continue
            row.alpaca_order_id = str(o.id) if getattr(o, "id", None) else row.alpaca_order_id
            row.status = str(getattr(o, "status", row.status))
            updated += 1

    # 2. Mirror current positions into our ``positions`` table.
    positions = alpaca.get_positions()
    with session_scope() as s:
        # Snapshot existing tickers so we can prune what's been closed.
        existing = {p.ticker: p for p in s.scalars(select(models.Position))}
        seen: set[str] = set()
        for p in positions:
            tic = str(p.symbol).upper()
            seen.add(tic)
            row = existing.get(tic)
            if row is None:
                # Infer strategy by looking at the most recent BUY order on this ticker.
                strat_row = s.scalar(
                    select(models.Order)
                    .where(models.Order.ticker == tic)
                    .where(models.Order.side == "buy")
                    .order_by(models.Order.submitted_at.desc())
                    .limit(1)
                )
                strategy_name = strat_row.strategy_name if strat_row else "unknown"
                entry_signal_id = strat_row.signal_id if strat_row else None
                row = models.Position(
                    ticker=tic,
                    strategy_name=strategy_name,
                    entry_signal_id=entry_signal_id,
                    qty=float(p.qty or 0),
                    avg_entry_price=float(p.avg_entry_price or 0),
                    opened_at=datetime.now(timezone.utc),
                )
                s.add(row)
            else:
                row.qty = float(p.qty or 0)
                row.avg_entry_price = float(p.avg_entry_price or row.avg_entry_price)
                # Update trail peak if current price exceeds stored peak.
                try:
                    curr = float(p.current_price) if p.current_price else None
                    if curr is not None:
                        row.trail_peak = max(row.trail_peak or curr, curr)
                except (TypeError, ValueError):
                    pass
        # Prune closed positions
        for tic, row in list(existing.items()):
            if tic not in seen:
                s.delete(row)

    return {"orders_updated": updated, "positions_seen": len(positions)}
