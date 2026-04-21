"""Tests for the phase-3 risk-layer accessors in ``jay_trading.data.store``."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from jay_trading.data import models, store
from jay_trading.data.db import create_all, session_scope


# -- Equity snapshots -------------------------------------------------------


def test_first_equity_snapshot_sets_hwm_to_equity() -> None:
    create_all()
    snap_id = store.record_equity_snapshot(equity=10_000.0, cash=10_000.0)
    assert snap_id > 0
    snap = store.latest_equity_snapshot()
    assert snap is not None
    assert snap.equity == 10_000.0
    assert snap.high_water_mark == 10_000.0


def test_subsequent_snapshot_carries_hwm_forward_when_equity_drops() -> None:
    create_all()
    store.record_equity_snapshot(equity=10_000.0, cash=10_000.0)
    store.record_equity_snapshot(equity=9_500.0, cash=9_500.0)  # drew down

    snap = store.latest_equity_snapshot()
    assert snap is not None
    assert snap.equity == 9_500.0
    # HWM does NOT drop with equity.
    assert snap.high_water_mark == 10_000.0


def test_snapshot_advances_hwm_on_new_high() -> None:
    create_all()
    store.record_equity_snapshot(equity=10_000.0, cash=10_000.0)
    store.record_equity_snapshot(equity=10_500.0, cash=10_500.0)

    snap = store.latest_equity_snapshot()
    assert snap is not None
    assert snap.high_water_mark == 10_500.0


# -- API call log ----------------------------------------------------------


def test_record_and_query_api_error_rate_within_window() -> None:
    create_all()
    # 3 fails, 7 oks — 30% fail rate, exactly on the threshold.
    for _ in range(3):
        store.record_api_call("fmp", "/stable/senate-latest", "fail", 120.0, "http_500")
    for _ in range(7):
        store.record_api_call("fmp", "/stable/senate-latest", "ok", 85.0)
    fails, total = store.api_error_rate("fmp", window_minutes=30)
    assert fails == 3
    assert total == 10


def test_api_error_rate_excludes_other_providers() -> None:
    create_all()
    store.record_api_call("fmp", "/stable/quote", "ok", 50.0)
    store.record_api_call("alpaca", "get_account", "fail", 500.0, "http_500")
    fails, total = store.api_error_rate("fmp")
    assert fails == 0
    assert total == 1


def test_prune_api_call_log_removes_old_rows_only() -> None:
    create_all()
    # Seed with one row "now" and one row 10 days ago.
    store.record_api_call("fmp", "/stable/quote", "ok", 50.0)
    with session_scope() as s:
        old = models.ApiCallLog(
            ts=datetime.now(timezone.utc) - timedelta(days=10),
            provider="fmp", endpoint="/stable/old", status="ok", latency_ms=10.0,
        )
        s.add(old)
    pruned = store.prune_api_call_log(older_than_days=7)
    assert pruned == 1

    # Surviving row is the recent one.
    _, total = store.api_error_rate("fmp", window_minutes=60)
    assert total == 1


# -- Ticker profile + sector position count --------------------------------


def test_upsert_ticker_profile_inserts_then_updates() -> None:
    create_all()
    store.upsert_ticker_profile("MSFT", sector="Technology", industry="Software", market_cap=3.1e12)
    prof = store.get_ticker_profile("MSFT")
    assert prof is not None
    assert prof.sector == "Technology"

    # Update with new sector (e.g. GICS reclassification)
    store.upsert_ticker_profile("MSFT", sector="Communication Services", industry="Software")
    prof = store.get_ticker_profile("MSFT")
    assert prof is not None
    assert prof.sector == "Communication Services"
    assert prof.market_cap is None  # overwritten


def test_get_ticker_profile_is_case_insensitive() -> None:
    create_all()
    store.upsert_ticker_profile("nvda", sector="Technology")
    prof = store.get_ticker_profile("NVDA")
    assert prof is not None
    assert prof.ticker == "NVDA"


def test_sector_position_count_joins_positions_to_profile() -> None:
    create_all()
    # Create 2 tech positions + 1 healthcare position
    with session_scope() as s:
        s.add(models.Position(
            ticker="MSFT", strategy_name="smart_copy", qty=1.0, avg_entry_price=420.0,
        ))
        s.add(models.Position(
            ticker="NVDA", strategy_name="smart_copy", qty=1.0, avg_entry_price=200.0,
        ))
        s.add(models.Position(
            ticker="PFE", strategy_name="insider_follow", qty=1.0, avg_entry_price=30.0,
        ))
    store.upsert_ticker_profile("MSFT", sector="Technology")
    store.upsert_ticker_profile("NVDA", sector="Technology")
    store.upsert_ticker_profile("PFE", sector="Healthcare")

    assert store.sector_position_count("Technology") == 2
    assert store.sector_position_count("Healthcare") == 1
    assert store.sector_position_count("Energy") == 0


def test_sector_position_count_with_empty_or_missing_profile() -> None:
    create_all()
    # Position exists but no ticker_profile row → does not count
    with session_scope() as s:
        s.add(models.Position(
            ticker="XYZ", strategy_name="smart_copy", qty=1.0, avg_entry_price=1.0,
        ))
    assert store.sector_position_count("Technology") == 0
    assert store.sector_position_count("") == 0
