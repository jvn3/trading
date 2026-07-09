"""Automated morning verification — unattended, read-only against the account.

Registered as the Windows task ``JayTrading-MorningCheck`` (weekdays 10:15
ET, after the 09:35 execute tick + 10:00 reconcile have settled). Checks the
invariants that must hold each morning and writes a dated PASS/WARN/FAIL
report to the vault (``verifications/YYYY-MM-DD_morning.md``), and mirrors
the most recent run to ``verifications/_latest.md`` so there's a stable path
to check. It deliberately does NOT touch development/log.md — that file is
the human/Claude development narrative; automated daily reports live in
their own folder so they can't corrupt it or race a live edit.

NO orders, NO writes to the trading DB. Safe to run unattended. Exit code is
0 on PASS/WARN, 1 on FAIL, so Task Scheduler's "Last Result" reflects health.
"""
from __future__ import annotations

import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select

from jay_trading.config import get_settings
from jay_trading.data import models, store
from jay_trading.data.alpaca_client import AlpacaPaperClient
from jay_trading.data.db import session_scope
from jay_trading.data.price_cache import get_closes
from jay_trading.vault.writer import write_vault_file

log = logging.getLogger(__name__)

INCEPTION_EQUITY = 10_000.0
HEARTBEAT_MAX_AGE_MIN = 15
REGIME_MAX_AGE_H = 24
SIGNAL_MAX_AGE_DAYS = 7
QQQ_MA_LEN = 200
# A live↔DB position mismatch (or a transient equity reading) is expected while
# orders are still settling. Treat a symbol as "in flight" if it has a working
# order or one that filled within this window; reconcile hasn't mirrored those
# fills into the DB yet, so the snapshot is mid-settlement, not a real fault.
SETTLE_WINDOW_MIN = 20

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
_RANK = {PASS: 0, WARN: 1, FAIL: 2}


def _naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _float(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _in_flight_symbols(alpaca: AlpacaPaperClient) -> set[str]:
    """Symbols whose account state is still settling — a working order, or one
    filled within ``SETTLE_WINDOW_MIN``. A live↔DB mismatch or a transient
    equity reading for these symbols is expected mid-settlement, not a fault.
    Read-only and best-effort: any API hiccup returns what we have so far so a
    fetch failure never turns a benign snapshot into a spurious WARN."""
    syms: set[str] = set()
    try:
        for o in alpaca.get_orders(status="open"):
            sym = str(getattr(o, "symbol", "")).upper()
            if sym:
                syms.add(sym)
    except Exception:  # noqa: BLE001
        pass
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=SETTLE_WINDOW_MIN)
        for o in alpaca.get_orders(status="all", after=date.today().isoformat()):
            fa = getattr(o, "filled_at", None)
            if fa is None:
                continue
            if fa.tzinfo is None:
                fa = fa.replace(tzinfo=timezone.utc)
            if fa >= cutoff:
                sym = str(getattr(o, "symbol", "")).upper()
                if sym:
                    syms.add(sym)
    except Exception:  # noqa: BLE001
        pass
    return syms


def _heartbeat_age_min() -> float | None:
    p = Path(get_settings().data_dir) / "heartbeat.txt"
    if not p.exists():
        return None
    try:
        ts = datetime.fromisoformat(p.read_text().strip())
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds() / 60.0


def check_scheduler() -> tuple[str, str]:
    age = _heartbeat_age_min()
    if age is None:
        return FAIL, "no heartbeat file — scheduler never started"
    if age > HEARTBEAT_MAX_AGE_MIN:
        return FAIL, f"heartbeat {age:.0f} min old (>{HEARTBEAT_MAX_AGE_MIN}) — scheduler dead/hung"
    return PASS, f"heartbeat {age:.1f} min old"


def check_regime() -> tuple[str, str]:
    snap = store.latest_macro_regime()
    if snap is None:
        return WARN, "no macro-regime snapshot — sizing falls back to 0.75x"
    ts = snap.ts.replace(tzinfo=timezone.utc) if snap.ts.tzinfo is None else snap.ts
    age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
    if age_h > REGIME_MAX_AGE_H:
        return WARN, f"regime snapshot {age_h:.0f}h old ({snap.regime}) — sizing at 0.75x until refresh"
    return PASS, f"{snap.regime}, {age_h:.1f}h old"


def check_signal_expiry() -> tuple[str, str]:
    cutoff = _naive_utcnow() - timedelta(days=SIGNAL_MAX_AGE_DAYS)
    with session_scope() as s:
        stale = s.scalar(
            select(func.count(models.Signal.id))
            .where(models.Signal.acted_on.is_(False))
            .where(models.Signal.generated_at < cutoff)
        ) or 0
        unacted = s.scalar(
            select(func.count(models.Signal.id))
            .where(models.Signal.acted_on.is_(False))
        ) or 0
    if stale > 0:
        return FAIL, f"{stale} unacted signals older than {SIGNAL_MAX_AGE_DAYS}d — expiry NOT working"
    return PASS, f"{unacted} unacted signals, none stale"


def check_positions_reconciled(
    alpaca: AlpacaPaperClient, in_flight: set[str]
) -> tuple[str, str]:
    live = {str(p.symbol).upper() for p in alpaca.get_positions()}
    with session_scope() as s:
        db_open = {
            r for (r,) in s.execute(
                select(models.Position.ticker).where(models.Position.closed_at.is_(None))
            )
        }
    db_open = {t.upper() for t in db_open}
    if live == db_open:
        return PASS, f"{len(live)} open positions match Alpaca ↔ DB"
    only_live = live - db_open
    only_db = db_open - live
    detail = (
        f"live={len(live)} db_open={len(db_open)}; "
        f"alpaca-only={sorted(only_live) or '—'} db-only={sorted(only_db) or '—'}"
    )
    # Tolerate mismatches fully explained by orders still settling — reconcile
    # will mirror those fills into the DB on its next pass. Only WARN on drift
    # that no in-flight order accounts for.
    unexplained = (only_live | only_db) - in_flight
    if not unexplained:
        return PASS, detail + f"; explained by {len(in_flight)} order(s) in flight (mid-settlement)"
    return WARN, detail + (
        f"; {len(in_flight)} in flight, unexplained drift={sorted(unexplained)} "
        "(reconcile lagging or real divergence)"
    )


def check_fills_ledger() -> tuple[str, str]:
    with session_scope() as s:
        fills = s.scalar(select(func.count(models.Fill.id))) or 0
        recent_closed = list(
            s.execute(
                select(models.Position.ticker, models.Position.realized_pnl)
                .where(models.Position.closed_at.is_not(None))
                .where(models.Position.closed_at >= _naive_utcnow() - timedelta(hours=24))
            )
        )
    missing_pnl = [t for (t, pnl) in recent_closed if pnl is None]
    if missing_pnl:
        return WARN, (
            f"{len(recent_closed)} positions closed <24h; {len(missing_pnl)} missing "
            f"realized_pnl ({sorted(missing_pnl)}); fills total={fills}"
        )
    if recent_closed:
        total = sum(pnl for (_, pnl) in recent_closed)
        return PASS, (
            f"{len(recent_closed)} closed <24h, realized P&L "
            f"${total:+.2f}; fills total={fills}"
        )
    return PASS, f"no closes in last 24h; fills total={fills}"


def check_risk_events() -> tuple[str, str]:
    since = _naive_utcnow() - timedelta(hours=24)
    with session_scope() as s:
        rows = list(
            s.execute(
                select(models.RiskEvent.kind, models.RiskEvent.severity, models.RiskEvent.reason)
                .where(models.RiskEvent.created_at >= since)
                .order_by(models.RiskEvent.created_at.desc())
            )
        )
    if not rows:
        return PASS, "no risk events in last 24h"
    halts = [r for r in rows if str(r[1]).lower() == "halt"]
    summary = "; ".join(f"{k}/{sev}" for (k, sev, _reason) in rows[:6])
    if halts:
        return WARN, f"{len(rows)} risk events incl. {len(halts)} halt: {summary}"
    return PASS, f"{len(rows)} non-halt risk events (expected: expiry/vetoes): {summary}"


def check_s1_state(alpaca: AlpacaPaperClient) -> tuple[str, str]:
    live = {str(p.symbol).upper() for p in alpaca.get_positions()}
    holds_tqqq = "TQQQ" in live
    closes = get_closes("QQQ", date.today() - timedelta(days=int(QQQ_MA_LEN * 1.7) + 30))
    if len(closes) < QQQ_MA_LEN:
        return WARN, f"only {len(closes)} cached QQQ closes (<{QQQ_MA_LEN}); S1 signal unavailable"
    last = closes[-1][1]
    sma = sum(c for _, c in closes[-QQQ_MA_LEN:]) / QQQ_MA_LEN
    above = last > sma
    want = "hold TQQQ" if above else "cash"
    ok = holds_tqqq == above
    detail = (
        f"QQQ {last:.2f} {'>' if above else '<='} 200dMA {sma:.2f} → want {want}; "
        f"TQQQ held={holds_tqqq}"
    )
    return (PASS if ok else WARN), detail


def check_performance(
    alpaca: AlpacaPaperClient, in_flight: set[str]
) -> tuple[str, str]:
    acct = alpaca.get_account()
    equity = float(acct.equity)
    ret = (equity / INCEPTION_EQUITY - 1) * 100
    base = (
        f"equity ${equity:,.2f} ({ret:+.2f}% vs $10k inception); "
        f"cash ${float(acct.cash):,.2f}"
    )
    # Equity comes straight from Alpaca's account endpoint, but a snapshot taken
    # mid-settlement (orders still filling) can read a transient value that does
    # not yet reflect open positions — this is what produced the misleading
    # "equity -45%" on 2026-07-07. Flag it and anchor to the last settled close.
    if in_flight:
        last = _float(getattr(acct, "last_equity", None))
        anchor = f"; last-close equity ${last:,.2f}" if last is not None else ""
        return PASS, base + (
            f"; {len(in_flight)} order(s) settling — equity may be transient{anchor}"
        )
    return PASS, base


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    alpaca = AlpacaPaperClient()
    # Fetch the in-flight order set once and share it across the settlement-
    # sensitive checks (positions, performance) so a mid-fill run doesn't WARN.
    in_flight = _in_flight_symbols(alpaca)

    checks: list[tuple[str, str, str]] = []

    def run(name: str, fn) -> None:
        try:
            status, detail = fn()
        except Exception as e:  # noqa: BLE001
            status, detail = FAIL, f"check raised: {type(e).__name__}: {e}"
        checks.append((name, status, detail))

    run("scheduler_alive", check_scheduler)
    run("regime_fresh", check_regime)
    run("signal_expiry", check_signal_expiry)
    run("positions_reconciled", lambda: check_positions_reconciled(alpaca, in_flight))
    run("fills_ledger", check_fills_ledger)
    run("risk_events_24h", check_risk_events)
    run("s1_rotation_state", lambda: check_s1_state(alpaca))
    run("performance", lambda: check_performance(alpaca, in_flight))

    verdict = max((_RANK[s] for _, s, _ in checks), default=0)
    verdict_str = {0: PASS, 1: WARN, 2: FAIL}[verdict]
    today = date.today().isoformat()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    lines = [
        "---",
        "type: verification",
        "subtype: morning",
        f"date: {today}",
        f"generated_at: {now}",
        f"verdict: {verdict_str}",
        "---",
        f"# Morning check — {today}",
        "",
        f"**Overall: {verdict_str}**",
        "",
        "| Check | Status | Detail |",
        "| --- | --- | --- |",
    ]
    for name, status, detail in checks:
        lines.append(f"| {name} | {status} | {detail} |")
    report = "\n".join(lines) + "\n"
    write_vault_file(f"verifications/{today}_morning.md", report)
    write_vault_file("verifications/_latest.md", report)

    print(f"morning_check {verdict_str} — report: verifications/{today}_morning.md")
    for name, status, detail in checks:
        print(f"  [{status}] {name}: {detail}")
    return 1 if verdict_str == FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
