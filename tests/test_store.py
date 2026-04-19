"""Tests for the data store / DAO."""
from __future__ import annotations

from datetime import date

from jay_trading.data import store
from jay_trading.data.db import create_all
from jay_trading.data.fmp import _dedup_key


def _make_row(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "source": "senate",
        "person_name": "Jane Doe",
        "person_role": "Rep",
        "ticker": "NVDA",
        "transaction_type": "buy",
        "transaction_date": date(2026, 4, 10),
        "filing_date": date(2026, 4, 14),
        "amount_low": 15001.0,
        "amount_high": 50000.0,
        "amount_exact": None,
        "raw_payload": {"x": 1},
    }
    base.update(over)
    # Compute dedup_key from the identity-defining fields so different
    # overrides yield different keys.
    base["dedup_key"] = _dedup_key(
        base["source"],  # type: ignore[arg-type]
        [
            base["person_name"],
            base["ticker"],
            base["transaction_date"],
            base["transaction_type"],
            base["amount_low"],
            base["amount_high"],
            base.get("filing_date"),
        ],
    )
    return base


def test_upsert_is_idempotent() -> None:
    create_all()
    rows = [_make_row(), _make_row(ticker="AAPL")]
    first = store.upsert_disclosed_trades(rows)
    second = store.upsert_disclosed_trades(rows)
    assert first.inserted == 2
    assert second.inserted == 0
    assert second.skipped == 2


def test_count_by_source_reflects_inserts() -> None:
    create_all()
    store.upsert_disclosed_trades([
        _make_row(source="senate"),
        _make_row(source="house", person_name="House Rep", ticker="MSFT"),
        _make_row(source="insider", person_name="CEO Person", ticker="GOOG"),
    ])
    counts = store.count_by_source()
    assert counts == {"senate": 1, "house": 1, "insider": 1}


def test_top_tickers_orders_by_frequency() -> None:
    create_all()
    store.upsert_disclosed_trades([
        _make_row(person_name=f"Person {i}", ticker="NVDA",
                  transaction_date=date(2026, 4, 1 + i))
        for i in range(3)
    ])
    store.upsert_disclosed_trades([
        _make_row(person_name="One Person", ticker="AAPL",
                  transaction_date=date(2026, 4, 1)),
    ])
    top = store.top_tickers(limit=5)
    assert top[0] == ("NVDA", 3)
    assert ("AAPL", 1) in top


def test_recent_disclosed_trades_filters_by_since() -> None:
    create_all()
    store.upsert_disclosed_trades([
        _make_row(filing_date=date(2026, 1, 1)),
        _make_row(ticker="AAPL", filing_date=date(2026, 4, 19)),
    ])
    rows = store.recent_disclosed_trades(since=date(2026, 4, 1))
    assert len(rows) == 1 and rows[0].ticker == "AAPL"


def test_record_risk_event_round_trip() -> None:
    create_all()
    eid = store.record_risk_event(
        kind="veto",
        reason="position size too large",
        strategy_name="smart_copy",
        ticker="NVDA",
    )
    assert isinstance(eid, int) and eid > 0
