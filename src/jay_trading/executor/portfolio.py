"""Build a PortfolioSnapshot from live Alpaca + our DB metadata."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select

from jay_trading.data import models
from jay_trading.data.alpaca_client import AlpacaPaperClient
from jay_trading.data.db import session_scope
from jay_trading.strategies.base import PortfolioSnapshot, PositionView

log = logging.getLogger(__name__)


def _our_position_rows() -> dict[str, models.Position]:
    with session_scope() as s:
        rows = list(s.scalars(select(models.Position)))
        for r in rows:
            s.expunge(r)
    return {r.ticker.upper(): r for r in rows}


def build_snapshot(alpaca: AlpacaPaperClient | None = None) -> PortfolioSnapshot:
    alpaca = alpaca or AlpacaPaperClient()
    acct = alpaca.get_account()
    raw_positions = alpaca.get_positions()
    our = _our_position_rows()
    positions: list[PositionView] = []
    for p in raw_positions:
        tic = str(p.symbol).upper()
        meta = our.get(tic)
        try:
            current_price = float(p.current_price) if p.current_price else float(p.avg_entry_price)
        except (TypeError, ValueError):
            current_price = float(p.avg_entry_price or 0.0)
        positions.append(
            PositionView(
                ticker=tic,
                qty=float(p.qty),
                avg_entry_price=float(p.avg_entry_price or 0.0),
                current_price=current_price,
                market_value=float(p.market_value or 0.0),
                unrealized_pl=float(p.unrealized_pl or 0.0),
                unrealized_plpc=float(p.unrealized_plpc or 0.0),
                strategy_name=meta.strategy_name if meta else None,
                hard_stop=meta.hard_stop if meta else None,
                trail_peak=meta.trail_peak if meta else None,
                trail_active=bool(meta.trail_active) if meta else False,
                opened_at=meta.opened_at if meta else None,
                entry_signal_id=meta.entry_signal_id if meta else None,
            )
        )
    return PortfolioSnapshot(
        equity=float(acct.equity),
        cash=float(acct.cash),
        buying_power=float(acct.buying_power),
        positions=positions,
        taken_at=datetime.now(timezone.utc),
    )
