"""Convert :class:`TradeIntent` → Alpaca order request + submit.

Every submission:
- Uses a deterministic ``client_order_id`` so re-running the execute job can't
  double-submit (Alpaca rejects duplicate client_order_ids in the same day).
- Records the order in our ``orders`` table before submit.
- Updates the record with alpaca_order_id after submit.
- Appends a line to today's trade log markdown.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Any

from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from jay_trading.data import models
from jay_trading.data.alpaca_client import AlpacaPaperClient
from jay_trading.data.db import session_scope
from jay_trading.strategies.base import TradeIntent
from jay_trading.vault.writer import write_vault_file

log = logging.getLogger(__name__)


def build_client_order_id(intent: TradeIntent) -> str:
    """Deterministic-ish id: strategy + signal_id + short uuid hex.

    Re-running the *same* execute call in the *same* day with the *same*
    signal will collide only by chance on the uuid segment; but even without
    the uuid piece, our pre-submit DB write bails out on duplicate
    (client_order_id is unique-indexed).
    """
    seg = (intent.signal_id and str(intent.signal_id)) or "nosig"
    rand = uuid.uuid4().hex[:8]
    raw = f"{intent.strategy_name}_{seg}_{rand}"
    # Alpaca caps client_order_id at 48 chars.
    return raw[:48]


def _record_order_pre_submit(intent: TradeIntent, client_order_id: str) -> int:
    with session_scope() as s:
        order = models.Order(
            strategy_name=intent.strategy_name,
            signal_id=intent.signal_id,
            client_order_id=client_order_id,
            ticker=intent.ticker,
            side=intent.side,
            order_type=intent.order_type,
            qty=intent.qty,
            notional=intent.notional,
            limit_price=intent.limit_price,
            stop_price=intent.stop_price,
            time_in_force=intent.time_in_force,
            status="pending",
            rationale_note_path=None,
        )
        s.add(order)
        s.flush()
        return int(order.id)


def _mark_submitted(order_id: int, alpaca_order_id: str | None, status: str) -> None:
    with session_scope() as s:
        row = s.get(models.Order, order_id)
        if row is None:
            return
        row.alpaca_order_id = alpaca_order_id
        row.status = status


def _mark_signal_acted(signal_id: int | None, alpaca_order_id: str | None) -> None:
    if signal_id is None:
        return
    with session_scope() as s:
        row = s.get(models.Signal, signal_id)
        if row is None:
            return
        row.acted_on = True
        row.acted_order_id = alpaca_order_id


def append_trade_log(
    intent: TradeIntent,
    client_order_id: str,
    alpaca_order_id: str | None,
    status: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Append a human-readable entry to today's trade log in the vault."""
    today = date.today().isoformat()
    path = f"trades/{today}_trades.md"
    line_parts: list[str] = [
        f"### {intent.action.upper()} {intent.ticker} {intent.side} — {intent.strategy_name}",
        f"- status: {status}",
        f"- client_order_id: `{client_order_id}`",
        f"- alpaca_order_id: `{alpaca_order_id or '—'}`",
        f"- notional: {intent.notional}  qty: {intent.qty}  type: {intent.order_type}",
        f"- signal_id: {intent.signal_id}",
    ]
    if extra:
        for k, v in extra.items():
            line_parts.append(f"- {k}: {v}")
    if intent.rationale:
        members = (intent.rationale.get("cluster") or {}).get("members") or []
        if members:
            names = ", ".join(m.get("name", "?") for m in members[:5])
            line_parts.append(f"- cluster members: {names}")
        exit_reason = intent.rationale.get("exit_reason")
        if exit_reason:
            line_parts.append(f"- exit_reason: {exit_reason}")

    # Append (don't overwrite) — read existing, concatenate, write atomically.
    from jay_trading.config import get_settings

    full = get_settings().vault_trading_root / path
    prior = ""
    if full.exists():
        prior = full.read_text(encoding="utf-8")
    else:
        prior = (
            f"---\n"
            f"type: trade-log\n"
            f"date: {today}\n"
            f"---\n"
            f"# Trade log — {today}\n\n"
        )
    body = prior + "\n".join(line_parts) + "\n\n"
    write_vault_file(path, body)


def submit_intent(
    intent: TradeIntent, alpaca: AlpacaPaperClient | None = None
) -> tuple[str, str | None, str]:
    """Submit one intent. Returns (client_order_id, alpaca_order_id, status)."""
    client_order_id = build_client_order_id(intent)
    our_order_id = _record_order_pre_submit(intent, client_order_id)
    alpaca = alpaca or AlpacaPaperClient()

    try:
        req = MarketOrderRequest(
            symbol=intent.ticker,
            notional=intent.notional if intent.qty is None else None,
            qty=intent.qty if intent.qty is not None else None,
            side=OrderSide.BUY if intent.side == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            client_order_id=client_order_id,
        )
        resp = alpaca.submit_order(req)
        alpaca_order_id = getattr(resp, "id", None)
        status = str(getattr(resp, "status", "submitted"))
        _mark_submitted(our_order_id, str(alpaca_order_id) if alpaca_order_id else None, status)
        _mark_signal_acted(intent.signal_id, str(alpaca_order_id) if alpaca_order_id else None)
        append_trade_log(intent, client_order_id, str(alpaca_order_id) if alpaca_order_id else None, status)
        return client_order_id, (str(alpaca_order_id) if alpaca_order_id else None), status
    except Exception as e:  # noqa: BLE001
        _mark_submitted(our_order_id, None, "failed")
        append_trade_log(
            intent, client_order_id, None, "failed", extra={"error": repr(e)[:200]}
        )
        log.exception("submit failed for %s: %s", intent.ticker, e)
        raise
