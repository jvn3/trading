"""Aggregation layer for the dashboard — read-only.

Everything returned here is a plain-dict / list-of-dicts, ready to be
JSON-encoded by FastAPI. A small TTL cache wraps Alpaca-hitting calls so the
browser can poll every few seconds without spamming the broker API.
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

from sqlalchemy import desc, func, select

from jay_trading.config import get_settings
from jay_trading.data import models
from jay_trading.data.alpaca_client import AlpacaPaperClient
from jay_trading.data.db import session_scope

T = TypeVar("T")
_cache: dict[str, tuple[float, Any]] = {}


def _cached(key: str, ttl: float, fn: Callable[[], T]) -> T:
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and (now - hit[0]) < ttl:
        return hit[1]  # type: ignore[return-value]
    val = fn()
    _cache[key] = (now, val)
    return val


# -- Alpaca-backed views ----------------------------------------------------


def account() -> dict[str, Any]:
    def _do() -> dict[str, Any]:
        a = AlpacaPaperClient()
        acct = a.get_account()
        return {
            "account_number": str(acct.account_number),
            "status": str(acct.status),
            "equity": float(acct.equity),
            "cash": float(acct.cash),
            "buying_power": float(acct.buying_power),
            "portfolio_value": float(getattr(acct, "portfolio_value", acct.equity) or acct.equity),
            "pattern_day_trader": bool(getattr(acct, "pattern_day_trader", False)),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

    return _cached("account", ttl=10, fn=_do)


def positions() -> list[dict[str, Any]]:
    def _do() -> list[dict[str, Any]]:
        a = AlpacaPaperClient()
        raw = a.get_positions()
        with session_scope() as s:
            meta = {
                p.ticker.upper(): p
                for p in s.scalars(select(models.Position))
            }
            for p in meta.values():
                s.expunge(p)
        out: list[dict[str, Any]] = []
        for p in raw:
            tic = str(p.symbol).upper()
            m = meta.get(tic)
            out.append(
                {
                    "ticker": tic,
                    "qty": float(p.qty or 0),
                    "avg_entry": float(p.avg_entry_price or 0),
                    "current_price": float(p.current_price or 0),
                    "market_value": float(p.market_value or 0),
                    "unrealized_pl": float(p.unrealized_pl or 0),
                    "unrealized_plpc": float(p.unrealized_plpc or 0),
                    "strategy": m.strategy_name if m else None,
                    "opened_at": m.opened_at.isoformat() if (m and m.opened_at) else None,
                    "trail_active": bool(m.trail_active) if m else False,
                    "entry_signal_id": m.entry_signal_id if m else None,
                }
            )
        return out

    return _cached("positions", ttl=10, fn=_do)


def orders(days: int = 7) -> list[dict[str, Any]]:
    def _do() -> list[dict[str, Any]]:
        a = AlpacaPaperClient()
        try:
            from alpaca.trading.enums import QueryOrderStatus
            from alpaca.trading.requests import GetOrdersRequest

            after = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            req = GetOrdersRequest(status=QueryOrderStatus.ALL, after=after)
            raw = list(a.raw.get_orders(filter=req))
        except Exception:  # noqa: BLE001
            raw = []
        out: list[dict[str, Any]] = []
        for o in raw:
            out.append(
                {
                    "id": str(getattr(o, "id", "")),
                    "client_order_id": str(getattr(o, "client_order_id", "") or ""),
                    "ticker": str(getattr(o, "symbol", "")),
                    "side": str(getattr(o, "side", "")).replace("OrderSide.", ""),
                    "status": str(getattr(o, "status", "")).replace("OrderStatus.", ""),
                    "qty": float(o.qty) if getattr(o, "qty", None) else None,
                    "notional": float(o.notional) if getattr(o, "notional", None) else None,
                    "filled_qty": float(o.filled_qty) if getattr(o, "filled_qty", None) else None,
                    "filled_avg_price": float(o.filled_avg_price)
                    if getattr(o, "filled_avg_price", None)
                    else None,
                    "submitted_at": o.submitted_at.isoformat()
                    if getattr(o, "submitted_at", None)
                    else None,
                    "order_type": str(getattr(o, "order_type", "")).replace("OrderType.", ""),
                }
            )
        return out

    return _cached(f"orders_{days}", ttl=10, fn=_do)


# -- DB-backed views (cheap; short TTL or none) -----------------------------


def signals(limit: int = 40) -> list[dict[str, Any]]:
    with session_scope() as s:
        rows = list(
            s.scalars(
                select(models.Signal)
                .order_by(models.Signal.score.desc(), models.Signal.generated_at.desc())
                .limit(limit)
            )
        )
        for r in rows:
            s.expunge(r)
    out: list[dict[str, Any]] = []
    for r in rows:
        rationale = r.rationale or {}
        cluster = rationale.get("cluster") or {}
        members = cluster.get("members") or []
        out.append(
            {
                "id": r.id,
                "strategy": r.strategy_name,
                "ticker": r.ticker,
                "direction": r.direction,
                "score": float(r.score),
                "acted_on": bool(r.acted_on),
                "acted_order_id": r.acted_order_id,
                "generated_at": r.generated_at.isoformat() if r.generated_at else None,
                "n_members": len(members),
                "members": [
                    {
                        "name": m.get("name"),
                        "role": m.get("role"),
                        "amount_range": m.get("amount_range"),
                        "tx_date": m.get("tx_date"),
                        "quality_score": m.get("quality_score"),
                    }
                    for m in members
                ],
                "window_start": cluster.get("window_start"),
                "window_end": cluster.get("window_end"),
            }
        )
    return out


def recent_disclosures(days: int = 14, limit: int = 40) -> list[dict[str, Any]]:
    since = date.today() - timedelta(days=days)
    with session_scope() as s:
        rows = list(
            s.scalars(
                select(models.DisclosedTrade)
                .where(models.DisclosedTrade.filing_date >= since)
                .order_by(desc(models.DisclosedTrade.filing_date))
                .limit(limit)
            )
        )
        for r in rows:
            s.expunge(r)
    return [
        {
            "source": r.source,
            "person": r.person_name,
            "role": r.person_role,
            "ticker": r.ticker,
            "side": r.transaction_type,
            "tx_date": r.transaction_date.isoformat(),
            "filing_date": r.filing_date.isoformat(),
            "amount_low": r.amount_low,
            "amount_high": r.amount_high,
        }
        for r in rows
    ]


def disclosures_top_tickers(days: int = 14, limit: int = 10) -> list[dict[str, Any]]:
    since = date.today() - timedelta(days=days)
    with session_scope() as s:
        rows = s.execute(
            select(
                models.DisclosedTrade.ticker,
                func.count(models.DisclosedTrade.id).label("n"),
            )
            .where(models.DisclosedTrade.filing_date >= since)
            .group_by(models.DisclosedTrade.ticker)
            .order_by(desc("n"))
            .limit(limit)
        ).all()
    return [{"ticker": t, "n": int(n)} for t, n in rows]


def disclosures_counts(days: int = 14) -> dict[str, int]:
    since = date.today() - timedelta(days=days)
    with session_scope() as s:
        rows = s.execute(
            select(
                models.DisclosedTrade.source,
                func.count(models.DisclosedTrade.id),
            )
            .where(models.DisclosedTrade.filing_date >= since)
            .group_by(models.DisclosedTrade.source)
        ).all()
    return {src: int(n) for src, n in rows}


# -- Scheduler + filesystem views ------------------------------------------


def scheduler_health() -> dict[str, Any]:
    s = get_settings()
    data_dir = Path(s.data_dir)
    pid_file = data_dir / "scheduler.pid"
    heart = data_dir / "heartbeat.txt"
    log_file = Path("logs/scheduler.log")

    pid: int | None = None
    alive = False
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            try:
                os.kill(pid, 0)
                alive = True
            except OSError:
                alive = False
        except (ValueError, OSError):
            pid = None

    last_beat: str | None = None
    age_seconds: float | None = None
    if heart.exists():
        try:
            last_beat = heart.read_text().strip()
            dt = datetime.fromisoformat(last_beat)
            age_seconds = (datetime.now(timezone.utc) - dt).total_seconds()
        except (OSError, ValueError):
            last_beat = None

    tail: list[str] = []
    if log_file.exists():
        try:
            with log_file.open("r", encoding="utf-8", errors="replace") as fh:
                tail = fh.readlines()[-20:]
        except OSError:
            tail = []

    # "Healthy" = PID alive AND heartbeat < 10 min old
    healthy = bool(alive and age_seconds is not None and age_seconds < 600)

    return {
        "pid": pid,
        "alive": alive,
        "last_heartbeat": last_beat,
        "heartbeat_age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
        "healthy": healthy,
        "log_tail": [ln.rstrip() for ln in tail],
    }


def briefings() -> list[dict[str, Any]]:
    vault = get_settings().obsidian_vault_path
    briefings_dir = vault / "briefings"
    if not briefings_dir.exists():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(briefings_dir.glob("*.md"), reverse=True)[:30]:
        try:
            stat = p.stat()
        except OSError:
            continue
        out.append(
            {
                "name": p.name,
                "path": str(p),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return out


def trade_logs() -> list[dict[str, Any]]:
    vault = get_settings().obsidian_vault_path
    d = vault / "trades"
    if not d.exists():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(d.glob("*_trades.md"), reverse=True)[:14]:
        try:
            stat = p.stat()
        except OSError:
            continue
        out.append(
            {
                "name": p.name,
                "path": str(p),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        )
    return out


def today_briefing_markdown() -> str | None:
    """Return the raw markdown of today's EOD or data briefing, if any."""
    vault = get_settings().obsidian_vault_path
    today = date.today().isoformat()
    for suffix in ("_eod.md", "_data.md"):
        p = vault / "briefings" / f"{today}{suffix}"
        if p.exists():
            try:
                return p.read_text(encoding="utf-8")
            except OSError:
                return None
    return None


def snapshot() -> dict[str, Any]:
    """Combine all views into one payload so the browser can do a single poll."""
    return {
        "account": _safe(account, default={}),
        "positions": _safe(positions, default=[]),
        "orders": _safe(orders, default=[]),
        "signals": _safe(signals, default=[]),
        "disclosures_counts": _safe(disclosures_counts, default={}),
        "disclosures_top_tickers": _safe(disclosures_top_tickers, default=[]),
        "recent_disclosures": _safe(recent_disclosures, default=[]),
        "scheduler": _safe(scheduler_health, default={"healthy": False}),
        "briefings": _safe(briefings, default=[]),
        "trade_logs": _safe(trade_logs, default=[]),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _safe(fn: Callable[[], T], *, default: T) -> T:
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        return default  # type: ignore[return-value]
