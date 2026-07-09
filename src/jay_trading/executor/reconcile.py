"""After orders have had a chance to fill, pull Alpaca's truth into our DB.

Run at 15:55 ET by the scheduler. Also triggered opportunistically after an
``execute_strategies`` pass so newly-opened Position rows exist for the next
``manage_positions`` tick.

Bookkeeping guarantees (added 2026-07-06, see development/audit-2026-07-05.md
for the bugs this fixes):
- Every filled order gets a ``fills`` row (order-level granularity: one row
  per filled order, keyed on the Alpaca order id, idempotent).
- Fills are recorded even for orders we never submitted through the executor —
  ``liquidate_all``'s close-all legs, OTO/bracket stop-loss children, manual
  closes — by backfilling a minimal ``external`` Order row so the fill has a
  parent (``Fill.order_id`` is a non-nullable FK). Without this the fills
  ledger silently dropped every out-of-band close (2026-07-07: 8 legacy
  liquidation sells → only 1 fill row).
- Closed positions are never deleted; they get ``closed_at`` / ``exit_price``
  / ``realized_pnl`` so per-trade and per-strategy P&L stay computable.
- Orders are pulled over a trailing window (not just today), so a status
  change that lands after midnight is still reconciled.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from jay_trading.data import models
from jay_trading.data.alpaca_client import AlpacaPaperClient
from jay_trading.data.db import session_scope

log = logging.getLogger(__name__)

# Trailing window for the Alpaca order pull. Wide enough to catch late
# status flips (async rejects, weekend-queued orders) without paginating.
ORDER_LOOKBACK_DAYS = 7


def _parse_dt(v: Any) -> datetime:
    if isinstance(v, datetime):
        return v.astimezone(timezone.utc) if v.tzinfo else v.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _float_or_none(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _enum_value(v: Any) -> str | None:
    """Alpaca enums (``OrderType``/``OrderSide``) → their string ``value``
    (e.g. ``"market"``), tolerating plain strings and ``None``."""
    if v is None:
        return None
    return str(getattr(v, "value", v))


def reconcile_orders_and_positions(alpaca: AlpacaPaperClient | None = None) -> dict[str, int]:
    alpaca = alpaca or AlpacaPaperClient()

    # 1. Pull recent orders from Alpaca, match by client_order_id, update
    #    status, and record fills.
    after = (date.today() - timedelta(days=ORDER_LOOKBACK_DAYS)).isoformat()
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus

        req = GetOrdersRequest(status=QueryOrderStatus.ALL, after=after)
        orders = alpaca.raw.get_orders(filter=req)
    except Exception as e:  # noqa: BLE001
        log.warning("failed to pull orders from Alpaca: %s", e)
        orders = []

    updated = 0
    fills_recorded = 0
    backfilled = 0
    # Latest filled SELL per symbol → exit price for positions closed since
    # the last reconcile pass.
    last_sell: dict[str, tuple[datetime, float]] = {}
    with session_scope() as s:
        for o in orders:
            side = str(getattr(o, "side", "")).lower()
            symbol = str(getattr(o, "symbol", "")).upper()
            fill_price = _float_or_none(getattr(o, "filled_avg_price", None))
            fill_qty = _float_or_none(getattr(o, "filled_qty", None))
            filled_at = _parse_dt(getattr(o, "filled_at", None))
            if fill_price and symbol and side.endswith("sell"):
                prev = last_sell.get(symbol)
                if prev is None or filled_at > prev[0]:
                    last_sell[symbol] = (filled_at, fill_price)

            oid = str(o.id) if getattr(o, "id", None) else None
            raw_cid = getattr(o, "client_order_id", None)
            # Effective key. Alpaca sets a client_order_id on every order,
            # auto-generating one for orders we didn't submit (close_all legs,
            # OTO stop-loss children, manual closes). Fall back to the order id
            # so an order that somehow lacks a cid can still be keyed idempotently.
            cid = str(raw_cid) if raw_cid else (f"ext-{oid}" if oid else None)
            if cid is None:
                continue
            row = s.scalar(
                select(models.Order).where(models.Order.client_order_id == cid)
            )
            if row is None:
                # An order we never recorded: liquidate_all's close_all, a
                # bracket/OTO stop-loss child leg, or a manual close. Backfill a
                # minimal Order row so the fill can be attached and the ledger
                # stays complete — this was a silent gap (the 8 legacy
                # liquidation sells on 2026-07-07 produced only 1 fill row).
                # Only filled orders need backfilling; an unfilled out-of-band
                # order carries no fill.
                if fill_price is None or not fill_qty:
                    continue
                row = models.Order(
                    strategy_name="external",
                    client_order_id=cid,
                    alpaca_order_id=oid,
                    ticker=symbol,
                    side="sell" if side.endswith("sell") else "buy",
                    order_type=(_enum_value(getattr(o, "order_type", None)) or "market")[:16],
                    qty=fill_qty,
                    status=str(getattr(o, "status", "filled")),
                    submitted_at=filled_at,
                )
                s.add(row)
                s.flush()  # assign row.id for the Fill FK below
                backfilled += 1
            else:
                new_status = str(getattr(o, "status", row.status))
                if new_status != row.status and (
                    "reject" in new_status.lower()
                    or "cancel" in new_status.lower()
                    or "expired" in new_status.lower()
                ):
                    # An order we thought was in flight died broker-side. Loud,
                    # not silent — this was the fully-silent swallow path.
                    log.warning(
                        "order %s (%s %s) flipped to %s broker-side",
                        cid, row.ticker, row.side, new_status,
                    )
                row.alpaca_order_id = oid or row.alpaca_order_id
                row.status = new_status
                updated += 1

            # Record the fill (idempotent on alpaca_fill_id).
            if fill_price is not None and fill_qty:
                stmt = sqlite_insert(models.Fill).values(
                    order_id=row.id,
                    alpaca_fill_id=(oid or cid),
                    qty=fill_qty,
                    price=fill_price,
                    filled_at=filled_at,
                )
                stmt = stmt.on_conflict_do_nothing(index_elements=["alpaca_fill_id"])
                result = s.execute(stmt)
                if (result.rowcount or 0) > 0:
                    fills_recorded += 1

    # 2. Mirror current positions into our ``positions`` table.
    positions = alpaca.get_positions()
    closed = 0
    with session_scope() as s:
        # Only OPEN rows participate in mirroring; closed rows are history.
        existing = {
            p.ticker: p
            for p in s.scalars(
                select(models.Position).where(models.Position.closed_at.is_(None))
            )
        }
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
        # Close (NOT delete) positions Alpaca no longer holds.
        for tic, row in list(existing.items()):
            if tic not in seen:
                row.closed_at = datetime.now(timezone.utc)
                sell = last_sell.get(tic)
                if sell is not None:
                    row.exit_price = sell[1]
                    row.realized_pnl = (sell[1] - row.avg_entry_price) * row.qty
                else:
                    log.warning(
                        "position %s closed but no filled sell order found in the "
                        "last %d days — realized_pnl left NULL",
                        tic, ORDER_LOOKBACK_DAYS,
                    )
                closed += 1

    return {
        "orders_updated": updated,
        "orders_backfilled": backfilled,
        "positions_seen": len(positions),
        "fills_recorded": fills_recorded,
        "positions_closed": closed,
    }
