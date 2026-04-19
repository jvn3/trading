"""Tests for normalization helpers in :mod:`jay_trading.data.fmp`.

These are pure functions — no network, no DB.
"""
from __future__ import annotations

from datetime import date

from jay_trading.data.fmp import (
    _parse_amount_range,
    _parse_iso_date,
    _normalize_side,
    normalize,
    normalize_insider_row,
    normalize_senate_row,
)


def test_parse_amount_range_typical() -> None:
    assert _parse_amount_range("$15,001 - $50,000") == (15001.0, 50000.0)


def test_parse_amount_range_single_value() -> None:
    low, high = _parse_amount_range("$1,000")
    assert low == 1000.0 and high == 1000.0


def test_parse_amount_range_empty() -> None:
    assert _parse_amount_range(None) == (None, None)
    assert _parse_amount_range("") == (None, None)


def test_normalize_side_variants() -> None:
    assert _normalize_side("Purchase") == "buy"
    assert _normalize_side("Sale (Partial)") == "sell"
    assert _normalize_side("P") == "buy"
    assert _normalize_side("S") == "sell"
    assert _normalize_side("exchange") == "exchange"
    assert _normalize_side(None) == "exchange"


def test_parse_iso_date_handles_datetime_string() -> None:
    assert _parse_iso_date("2026-04-10T00:00:00") == date(2026, 4, 10)


def test_normalize_senate_row_populates_required_fields() -> None:
    raw = {
        "symbol": "nvda",
        "representative": "Jane Doe",
        "transactionDate": "2026-04-10",
        "disclosureDate": "2026-04-14",
        "type": "Purchase",
        "amount": "$15,001 - $50,000",
    }
    out = normalize_senate_row(raw)
    assert out is not None
    assert out["ticker"] == "NVDA"
    assert out["transaction_type"] == "buy"
    assert out["person_name"] == "Jane Doe"
    assert out["transaction_date"] == date(2026, 4, 10)
    assert out["amount_low"] == 15001.0 and out["amount_high"] == 50000.0


def test_normalize_senate_row_skips_unusable() -> None:
    # No ticker
    assert normalize_senate_row({"transactionDate": "2026-04-10"}) is None
    # No date
    assert normalize_senate_row({"symbol": "NVDA"}) is None


def test_normalize_insider_row_computes_exact_amount() -> None:
    raw = {
        "symbol": "AAPL",
        "reportingName": "Tim Cook",
        "typeOfOwner": "CEO",
        "transactionDate": "2026-04-10",
        "filingDate": "2026-04-12",
        "acquistionOrDisposition": "A",
        "securitiesTransacted": 1000,
        "price": 180.50,
        "transactionType": "Purchase",
    }
    out = normalize_insider_row(raw)
    assert out is not None
    assert out["ticker"] == "AAPL"
    assert out["amount_exact"] == 180500.0
    assert out["dedup_key"]  # must be populated


def test_insider_multi_line_filings_get_distinct_dedup_keys() -> None:
    # Same filer + ticker + date, but distinct transactionType and price —
    # these are separate line items on one Form 4 and must dedup separately.
    raw1 = {
        "symbol": "GOOG", "reportingName": "A. Officer",
        "transactionDate": "2026-04-10", "filingDate": "2026-04-11",
        "reportingCik": "0001234", "transactionType": "P-Purchase",
        "securitiesTransacted": 100, "price": 150.0,
    }
    raw2 = {**raw1, "transactionType": "S-Sale", "price": 160.0}
    a = normalize_insider_row(raw1)
    b = normalize_insider_row(raw2)
    assert a and b
    assert a["dedup_key"] != b["dedup_key"]


def test_insider_null_amounts_still_distinct_per_transaction() -> None:
    # Two transactions with null amounts but different reportingCik should
    # not collapse — catches the NULL-collides bug.
    raw1 = {
        "symbol": "GRAB", "reportingName": "X",
        "transactionDate": "2026-04-15", "filingDate": "2026-04-16",
        "reportingCik": "A", "transactionType": "F",
    }
    raw2 = {**raw1, "reportingCik": "B"}
    a = normalize_insider_row(raw1)
    b = normalize_insider_row(raw2)
    assert a and b and a["dedup_key"] != b["dedup_key"]


def test_normalize_dispatches_by_source() -> None:
    rows = [
        {"symbol": "NVDA", "representative": "Jane", "transactionDate": "2026-04-10",
         "type": "Purchase", "amount": "$1,001 - $15,000"},
    ]
    out = normalize("senate", rows)
    assert len(out) == 1 and out[0]["source"] == "senate"
