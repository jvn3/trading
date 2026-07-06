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
from alpaca.trading.requests import (
    LimitOrderRequest,
    MarketOrderRequest,
    StopLossRequest,
)

from jay_trading.data import models
from jay_trading.data.alpaca_client import AlpacaPaperClient
from jay_trading.data.db import session_scope
from jay_trading.strategies.base import TradeIntent
from jay_trading.vault.writer import write_vault_file

log = logging.getLogger(__name__)

# Canonical slashless crypto symbols (Alpaca accepts both "BTC/USD" and
# "BTCUSD" on submit but reports positions slashless; we standardize on
# slashless everywhere so reconcile's ticker matching keeps working).
CRYPTO_SYMBOLS = {"BTCUSD", "ETHUSD", "SOLUSD", "BTC/USD", "ETH/USD", "SOL/USD"}

_TIF_MAP = {
    "day": TimeInForce.DAY,
    "gtc": TimeInForce.GTC,
    "ioc": TimeInForce.IOC,
}


def is_crypto(ticker: str) -> bool:
    return ticker.upper() in CRYPTO_SYMBOLS or "/" in ticker


def _resolve_tif(intent: TradeIntent) -> TimeInForce:
    """Crypto rejects DAY orders — force GTC there; otherwise honor the
    intent (default day)."""
    if is_crypto(intent.ticker):
        tif = _TIF_MAP.get(intent.time_in_force.lower(), TimeInForce.GTC)
        return tif if tif in (TimeInForce.GTC, TimeInForce.IOC) else TimeInForce.GTC
    return _TIF_MAP.get(intent.time_in_force.lower(), TimeInForce.DAY)


def _build_request(intent: TradeIntent, client_order_id: str) -> Any:
    """TradeIntent → Alpaca order request.

    Previously this always emitted a DAY market order and silently ignored
    intent.order_type/limit_price/stop_price/time_in_force (dead fields per
    audit-2026-07-05). Now:
    - order_type="limit" + limit_price → LimitOrderRequest.
    - stop_price on a whole-share equity BUY open → OTO market order with a
      server-side stop-loss leg (fills the 15-min software-stop gap and the
      overnight gap). Requires whole shares — Alpaca disallows legs on
      fractional/notional orders — so callers wanting a stop leg must size
      in whole-share qty.
    - crypto → GTC (DAY unsupported).
    """
    side = OrderSide.BUY if intent.side == "buy" else OrderSide.SELL
    tif = _resolve_tif(intent)
    common: dict[str, Any] = {
        "symbol": intent.ticker,
        "side": side,
        "time_in_force": tif,
        "client_order_id": client_order_id,
    }

    if intent.order_type == "limit" and intent.limit_price is not None:
        return LimitOrderRequest(
            qty=intent.qty,
            notional=intent.notional if intent.qty is None else None,
            limit_price=float(intent.limit_price),
            **common,
        )

    stop_leg_ok = (
        intent.stop_price is not None
        and intent.action == "open"
        and side is OrderSide.BUY
        and not is_crypto(intent.ticker)
        and intent.qty is not None
        and float(intent.qty) == int(intent.qty)  # whole shares only
    )
    if stop_leg_ok:
        return MarketOrderRequest(
            qty=intent.qty,
            order_class="oto",
            stop_loss=StopLossRequest(stop_price=float(intent.stop_price)),
            **common,
        )
    if intent.stop_price is not None and not stop_leg_ok:
        log.warning(
            "stop_price on %s ignored (needs whole-share equity BUY open); "
            "submitting plain market order — software stops still apply",
            intent.ticker,
        )

    return MarketOrderRequest(
        qty=intent.qty if intent.qty is not None else None,
        notional=intent.notional if intent.qty is None else None,
        **common,
    )


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
        req = _build_request(intent, client_order_id)
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
