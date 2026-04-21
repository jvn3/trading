"""Tests for cluster detection (pure logic on a controlled DB)."""
from __future__ import annotations

from datetime import date

import pytest

from jay_trading.data.db import create_all
from jay_trading.data.fmp import _dedup_key
from jay_trading.data import store
from jay_trading.signals.cluster_detector import (
    STRATEGY_NAME,
    find_clusters,
    upsert_signals,
)
from jay_trading.signals.politician_scorer import PoliticianScore


def _row(source: str, person: str, ticker: str, side: str, tx: date, filed: date,
         amt: tuple[float | None, float | None] = (15000.0, 50000.0)) -> dict:
    low, high = amt
    row: dict = {
        "source": source,
        "person_name": person,
        "person_role": "Rep",
        "ticker": ticker,
        "transaction_type": side,
        "transaction_date": tx,
        "filing_date": filed,
        "amount_low": low,
        "amount_high": high,
        "amount_exact": None,
        "raw_payload": {},
    }
    row["dedup_key"] = _dedup_key(
        source, [person, ticker, tx, side, low, high, filed]
    )
    return row


@pytest.fixture
def scores() -> dict[str, PoliticianScore]:
    """Neutral scores so tests exercise cluster logic, not scorer logic."""
    return {
        "Alice": PoliticianScore("Alice", 0.05, 3, True),
        "Bob": PoliticianScore("Bob", 0.02, 2, True),
        "Cara": PoliticianScore("Cara", -0.05, 4, False),
    }


def test_two_distinct_buyers_same_ticker_form_a_cluster(scores) -> None:
    create_all()
    store.upsert_disclosed_trades([
        _row("senate", "Alice", "NVDA", "buy", date(2026, 4, 5), date(2026, 4, 10)),
        _row("house", "Bob", "NVDA", "buy", date(2026, 4, 8), date(2026, 4, 14)),
    ])
    clusters = find_clusters(scores=scores)
    nvda_long = [c for c in clusters if c.ticker == "NVDA" and c.direction == "long"]
    assert nvda_long, "expected a long cluster on NVDA"
    c = nvda_long[0]
    assert {m["name"] for m in c.members} == {"Alice", "Bob"}
    assert 0 < c.score <= 1


def test_single_politician_does_not_form_a_cluster(scores) -> None:
    create_all()
    store.upsert_disclosed_trades([
        _row("senate", "Alice", "AAPL", "buy", date(2026, 4, 5), date(2026, 4, 10)),
    ])
    clusters = find_clusters(scores=scores)
    assert not [c for c in clusters if c.ticker == "AAPL"]


def test_mixed_direction_does_not_form_a_cluster(scores) -> None:
    create_all()
    store.upsert_disclosed_trades([
        _row("senate", "Alice", "TSLA", "buy", date(2026, 4, 5), date(2026, 4, 10)),
        _row("house", "Bob", "TSLA", "sell", date(2026, 4, 8), date(2026, 4, 14)),
    ])
    clusters = find_clusters(scores=scores)
    tsla = [c for c in clusters if c.ticker == "TSLA"]
    # We may get a single-member "cluster" per direction but not a valid one
    # with >=2 members on either side.
    assert all(len(c.members) < 2 for c in tsla)


def test_trades_outside_window_do_not_cluster(scores) -> None:
    create_all()
    store.upsert_disclosed_trades([
        _row("senate", "Alice", "GOOG", "buy", date(2026, 3, 1), date(2026, 3, 5)),
        _row("house", "Bob", "GOOG", "buy", date(2026, 4, 18), date(2026, 4, 19)),
    ])
    # 45 days apart: should not cluster within the 14-day filing window.
    clusters = find_clusters(scores=scores)
    goog = [c for c in clusters if c.ticker == "GOOG" and c.direction == "long"]
    assert not goog


def test_upsert_signals_is_idempotent(scores) -> None:
    create_all()
    store.upsert_disclosed_trades([
        _row("senate", "Alice", "META", "buy", date(2026, 4, 5), date(2026, 4, 10)),
        _row("house", "Bob", "META", "buy", date(2026, 4, 8), date(2026, 4, 14)),
    ])
    clusters = find_clusters(scores=scores)
    n1 = upsert_signals(clusters)
    n2 = upsert_signals(clusters)
    assert n1 >= 1
    assert n2 == 0


def test_committee_bonus_applies_when_relevant(scores) -> None:
    create_all()
    # LMT is in "armed services" mapping; role contains "armed services".
    row1 = _row("senate", "Alice", "LMT", "buy", date(2026, 4, 5), date(2026, 4, 10))
    row1["person_role"] = "Armed Services Committee"
    row2 = _row("house", "Bob", "LMT", "buy", date(2026, 4, 8), date(2026, 4, 14))
    store.upsert_disclosed_trades([row1, row2])
    clusters = find_clusters(scores=scores)
    lmt = [c for c in clusters if c.ticker == "LMT" and c.direction == "long"]
    assert lmt
    # With committee relevance we expect score >= base * 1.2 * 1.2
    # base = 2/5 = 0.4, so minimum with bonuses = 0.4 * 1.2 * 1.2 = 0.576
    assert lmt[0].score >= 0.5
