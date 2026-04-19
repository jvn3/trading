"""Scheduled jobs. Each is idempotent (running twice does not double-write).

Phase 1 only defines :func:`ingest_disclosures`. Later phases add
``generate_signals``, ``execute_strategies``, ``manage_stops``,
``write_morning_briefing``, ``write_eod_summary``, ``weekly_review``.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from jay_trading.data import store
from jay_trading.data.db import create_all, get_engine
from jay_trading.data.fmp import FMPClient, normalize, since_window_days
from jay_trading.vault.templates import render_data_briefing
from jay_trading.vault.writer import write_vault_file

log = logging.getLogger(__name__)


def _format_range(r: object) -> str:
    low = getattr(r, "amount_low", None)
    high = getattr(r, "amount_high", None)
    if low is None and high is None:
        return "—"
    if low == high:
        return f"${low:,.0f}"
    return f"${low:,.0f}–${high:,.0f}"


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
    """Ingest senate + house + insider disclosures and write a daily briefing.

    Idempotent: re-running the same day updates the existing briefing and
    inserts zero new DB rows.
    """
    # Ensure schema exists even if alembic hasn't been run (dev convenience)
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
                raw = pull()  # default pagination per helper
            except Exception as e:  # noqa: BLE001
                log.warning("FMP %s pull failed: %s", source, e)
                raw = []
            per_source_pulled[source] = len(raw)
            norm = normalize(source, raw)
            all_rows.extend(norm)
    finally:
        fmp.close()

    report = store.upsert_disclosed_trades(all_rows)

    since = since_window_days(lookback_days)
    counts = store.count_by_source(since=since)
    top = store.top_tickers(since=since, limit=10)

    # "New today" subsets: filter the normalized rows down to what was
    # just inserted. For simplicity, we reread recent rows and split by source.
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
        **{f"total_{k}": v for k, v in counts.items()},
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = ingest_disclosures()
    print(result)
    # Confirm engine string for operator sanity
    print("engine:", get_engine().url)
