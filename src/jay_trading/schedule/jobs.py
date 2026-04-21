"""Scheduled jobs.

Each is idempotent. Job functions have no args and return a small dict of
counters so the scheduler can log progress.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy import select

from jay_trading.data import models, store
from jay_trading.data.alpaca_client import AlpacaPaperClient
from jay_trading.data.db import create_all, get_engine, session_scope
from jay_trading.data.fmp import FMPClient, normalize, since_window_days
from jay_trading.executor import order_builder, portfolio as portfolio_mod, reconcile
from jay_trading.risk.sizing import size_intent
from jay_trading.signals.cluster_detector import find_clusters, upsert_signals
from jay_trading.strategies.base import SignalView
from jay_trading.strategies.smart_copy import SmartCopyStrategy
from jay_trading.vault.templates import render_data_briefing
from jay_trading.vault.writer import write_vault_file

log = logging.getLogger(__name__)

STRATEGIES = [SmartCopyStrategy()]


# -- Existing Phase 1 ingest (kept) -----------------------------------------


def _format_range(r: object) -> str:
    low = getattr(r, "amount_low", None)
    high = getattr(r, "amount_high", None)
    if low is None and high is None:
        return "-"
    if low == high:
        return f"${low:,.0f}"
    return f"${low:,.0f}-${high:,.0f}"


def _row_to_template_dict(row: object) -> dict[str, object]:
    return {
        "person_name": getattr(row, "person_name", "?"),
        "ticker": getattr(row, "ticker", "?"),
        "transaction_type": getattr(row, "transaction_type", "?"),
        "transaction_date": str(getattr(row, "transaction_date", "?")),
        "filing_date": str(getattr(row, "filing_date", "?")),
        "amount_range": _format_range(row),
    }


def ingest_disclosures(lookback_days: int = 14) -> dict[str, int]:
    create_all()
    fmp = FMPClient()
    all_rows: list[dict[str, object]] = []
    per_source_pulled: dict[str, int] = {}
    try:
        for source, pull in (
            ("senate", fmp.senate_trades),
            ("house", fmp.house_trades),
            ("insider", fmp.insider_trades),
        ):
            try:
                raw = pull()
            except Exception as e:  # noqa: BLE001
                log.warning("FMP %s pull failed: %s", source, e)
                raw = []
            per_source_pulled[source] = len(raw)
            all_rows.extend(normalize(source, raw))
    finally:
        fmp.close()

    report = store.upsert_disclosed_trades(all_rows)
    since = since_window_days(lookback_days)
    counts = store.count_by_source(since=since)
    top = store.top_tickers(since=since, limit=10)

    today = date.today()
    recent = store.recent_disclosed_trades(since=today)
    senate_new = [_row_to_template_dict(r) for r in recent if r.source == "senate"][:25]
    house_new = [_row_to_template_dict(r) for r in recent if r.source == "house"][:25]
    insider_new = [_row_to_template_dict(r) for r in recent if r.source == "insider"][:25]

    md = render_data_briefing(
        date=today.isoformat(),
        generated_at=datetime.now(timezone.utc).isoformat(),
        report={
            "inserted": report.inserted,
            "skipped": report.skipped,
            "total_seen": report.total_seen,
        },
        counts=counts,
        senate_new=senate_new,
        house_new=house_new,
        insider_new=insider_new,
        top_tickers=top,
    )
    write_vault_file(f"briefings/{today.isoformat()}_data.md", md)

    log.info(
        "ingest_disclosures: inserted=%d skipped=%d counts=%s",
        report.inserted,
        report.skipped,
        counts,
    )
    return {
        "inserted": report.inserted,
        "skipped": report.skipped,
        **{f"pulled_{k}": v for k, v in per_source_pulled.items()},
    }


# -- Phase 2 jobs ----------------------------------------------------------


def generate_signals() -> dict[str, int]:
    """Run cluster detection and persist new Signal rows."""
    create_all()
    clusters = find_clusters()
    inserted = upsert_signals(clusters)
    log.info("generate_signals: %d clusters active, %d newly persisted", len(clusters), inserted)
    return {"clusters_found": len(clusters), "signals_inserted": inserted}


def _unacted_signals() -> list[SignalView]:
    with session_scope() as s:
        rows = list(
            s.scalars(
                select(models.Signal)
                .where(models.Signal.acted_on.is_(False))
                .order_by(models.Signal.score.desc())
            )
        )
        # Detach so we can hold SignalView dataclasses outside the session.
        for r in rows:
            s.expunge(r)
    return [
        SignalView(
            id=r.id,
            strategy_name=r.strategy_name,
            ticker=r.ticker,
            direction=r.direction,
            score=float(r.score),
            rationale=dict(r.rationale or {}),
            generated_at=r.generated_at,
        )
        for r in rows
    ]


def execute_strategies() -> dict[str, int]:
    """Generate intents, size them, and submit to Alpaca paper."""
    create_all()
    signals = _unacted_signals()
    alpaca = AlpacaPaperClient()
    portfolio = portfolio_mod.build_snapshot(alpaca)

    submitted = 0
    rejected = 0
    for strat in STRATEGIES:
        if not strat.enabled:
            continue
        my_signals = [s for s in signals if s.strategy_name == strat.name]
        intents = strat.generate_intents(my_signals, portfolio)
        log.info(
            "execute_strategies[%s]: %d raw intents from %d signals",
            strat.name, len(intents), len(my_signals),
        )
        for intent in intents:
            dec = size_intent(intent, portfolio)
            if dec.verdict == "REJECT" or dec.intent is None:
                rejected += 1
                log.info("reject %s %s: %s", intent.ticker, intent.side, dec.reason)
                store.record_risk_event(
                    kind="sizing_veto",
                    reason=dec.reason,
                    strategy_name=intent.strategy_name,
                    ticker=intent.ticker,
                )
                continue
            try:
                order_builder.submit_intent(dec.intent, alpaca=alpaca)
                submitted += 1
            except Exception as e:  # noqa: BLE001
                log.warning("submit failed for %s: %s", intent.ticker, e)

    # Refresh positions so the next `manage_stops` tick sees the new rows.
    try:
        reconcile.reconcile_orders_and_positions(alpaca=alpaca)
    except Exception as e:  # noqa: BLE001
        log.warning("post-submit reconcile failed: %s", e)

    log.info("execute_strategies: submitted=%d rejected=%d", submitted, rejected)
    return {"submitted": submitted, "rejected": rejected}


def manage_stops() -> dict[str, int]:
    """Software-side stop management (Alpaca doesn't stop-order fractionals)."""
    create_all()
    alpaca = AlpacaPaperClient()
    portfolio = portfolio_mod.build_snapshot(alpaca)
    closed = 0
    for strat in STRATEGIES:
        if not strat.enabled:
            continue
        intents = strat.manage_positions(
            [p for p in portfolio.positions if p.strategy_name == strat.name],
            portfolio,
        )
        for intent in intents:
            try:
                order_builder.submit_intent(intent, alpaca=alpaca)
                closed += 1
            except Exception as e:  # noqa: BLE001
                log.warning("close submit failed for %s: %s", intent.ticker, e)

    if closed:
        try:
            reconcile.reconcile_orders_and_positions(alpaca=alpaca)
        except Exception as e:  # noqa: BLE001
            log.warning("post-close reconcile failed: %s", e)
    log.info("manage_stops: closed=%d", closed)
    return {"closed": closed}


def reconcile_now() -> dict[str, int]:
    return reconcile.reconcile_orders_and_positions()


def write_eod_summary() -> dict[str, int]:
    """Short end-of-day summary markdown."""
    today = date.today()
    with session_scope() as s:
        todays_orders = list(
            s.scalars(
                select(models.Order)
                .where(models.Order.submitted_at >= datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc))
            )
        )
        todays_positions = list(s.scalars(select(models.Position)))
    lines: list[str] = [
        "---",
        "type: briefing",
        "subtype: eod",
        f"date: {today.isoformat()}",
        f"generated_at: {datetime.now(timezone.utc).isoformat()}",
        "---",
        f"# EOD summary — {today.isoformat()}",
        "",
        f"## Orders today ({len(todays_orders)})",
    ]
    if todays_orders:
        lines += [
            "| Time | Ticker | Side | Notional | Qty | Status | Strategy |",
            "| --- | --- | --- | ---: | ---: | --- | --- |",
        ]
        for o in todays_orders:
            lines.append(
                f"| {o.submitted_at.strftime('%H:%M') if o.submitted_at else '—'} | "
                f"{o.ticker} | {o.side} | {o.notional or '-'} | {o.qty or '-'} | "
                f"{o.status} | {o.strategy_name} |"
            )
    else:
        lines.append("_(none)_")
    lines.append(f"\n## Open positions ({len(todays_positions)})")
    if todays_positions:
        lines += [
            "| Ticker | Qty | Avg entry | Strategy | Opened |",
            "| --- | ---: | ---: | --- | --- |",
        ]
        for p in todays_positions:
            lines.append(
                f"| {p.ticker} | {p.qty} | ${p.avg_entry_price:.2f} | "
                f"{p.strategy_name} | {p.opened_at.date().isoformat() if p.opened_at else '—'} |"
            )
    else:
        lines.append("_(none)_")

    write_vault_file(f"briefings/{today.isoformat()}_eod.md", "\n".join(lines) + "\n")
    return {"orders": len(todays_orders), "positions": len(todays_positions)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else "ingest"
    mapping = {
        "ingest": ingest_disclosures,
        "signals": generate_signals,
        "execute": execute_strategies,
        "stops": manage_stops,
        "reconcile": reconcile_now,
        "eod": write_eod_summary,
    }
    fn = mapping.get(cmd)
    if fn is None:
        print(f"unknown command: {cmd}. known: {list(mapping)}")
        sys.exit(2)
    print(fn())
    print("engine:", get_engine().url)
