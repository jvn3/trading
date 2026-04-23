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


# ---- Knob 2: conviction (track-record) multiplier ----------------------


def test_conviction_bonus_fires_when_member_has_strong_record() -> None:
    create_all()
    # Dave is a high-conviction politician (trailing return 8% > 5% threshold).
    high_conviction_scores = {
        "Dave": PoliticianScore("Dave", 0.08, 5, True),
        "Eve":  PoliticianScore("Eve", 0.01, 3, True),
    }
    store.upsert_disclosed_trades([
        _row("senate", "Dave", "AVGO", "buy", date(2026, 4, 5), date(2026, 4, 10)),
        _row("house",  "Eve",  "AVGO", "buy", date(2026, 4, 8), date(2026, 4, 14)),
    ])
    clusters = find_clusters(scores=high_conviction_scores)
    avgo = [c for c in clusters if c.ticker == "AVGO" and c.direction == "long"]
    assert avgo
    c = avgo[0]
    # base 0.4 × quality 1.2 × committee 1.0 × conviction 1.2 = 0.576
    assert c.score == pytest.approx(0.576, rel=1e-3)
    assert c.score_components["conviction_mult"] == 1.2


def test_conviction_bonus_skipped_when_no_strong_record() -> None:
    create_all()
    # Both politicians positive but neither above 5%.
    weak_scores = {
        "Frank": PoliticianScore("Frank", 0.04, 2, True),
        "Gail":  PoliticianScore("Gail",  0.02, 2, True),
    }
    store.upsert_disclosed_trades([
        _row("senate", "Frank", "INTC", "buy", date(2026, 4, 5), date(2026, 4, 10)),
        _row("house",  "Gail",  "INTC", "buy", date(2026, 4, 8), date(2026, 4, 14)),
    ])
    clusters = find_clusters(scores=weak_scores)
    intc = [c for c in clusters if c.ticker == "INTC" and c.direction == "long"]
    assert intc
    c = intc[0]
    # base 0.4 × quality 1.2 × no other multipliers = 0.48
    assert c.score == pytest.approx(0.48, rel=1e-3)
    assert c.score_components["conviction_mult"] == 1.0


# ---- Knob 3: insider co-buying confluence ------------------------------


def test_insider_confluence_bonus_fires_with_two_insider_buys() -> None:
    create_all()
    # Two insider BUYS on AAPL within the lookback window.
    store.upsert_disclosed_trades([
        _row("insider", "Insider A", "AAPL", "buy", date(2026, 4, 1), date(2026, 4, 2)),
        _row("insider", "Insider B", "AAPL", "buy", date(2026, 4, 3), date(2026, 4, 4)),
        # Plus a 2-politician congress cluster on the same ticker.
        _row("senate", "Helen", "AAPL", "buy", date(2026, 4, 5), date(2026, 4, 10)),
        _row("house",  "Ian",   "AAPL", "buy", date(2026, 4, 8), date(2026, 4, 14)),
    ])
    scores = {
        "Helen": PoliticianScore("Helen", 0.02, 2, True),
        "Ian":   PoliticianScore("Ian",   0.01, 2, True),
    }
    clusters = find_clusters(scores=scores)
    aapl = [c for c in clusters if c.ticker == "AAPL" and c.direction == "long"]
    assert aapl
    c = aapl[0]
    # base 0.4 × quality 1.2 × insider_confluence 1.15 = 0.552
    assert c.score == pytest.approx(0.552, rel=1e-3)
    assert c.score_components["insider_confluence_mult"] == 1.15
    assert c.score_components["n_insider_buyers"] == 2


def test_insider_confluence_skipped_when_only_sells_on_ticker() -> None:
    create_all()
    # Insider activity is sells-only — does not count toward confluence.
    store.upsert_disclosed_trades([
        _row("insider", "Insider A", "MU", "sell", date(2026, 4, 1), date(2026, 4, 2)),
        _row("insider", "Insider B", "MU", "sell", date(2026, 4, 3), date(2026, 4, 4)),
        _row("senate", "Jane", "MU", "buy", date(2026, 4, 5), date(2026, 4, 10)),
        _row("house",  "Ken",  "MU", "buy", date(2026, 4, 8), date(2026, 4, 14)),
    ])
    scores = {
        "Jane": PoliticianScore("Jane", 0.02, 2, True),
        "Ken":  PoliticianScore("Ken",  0.01, 2, True),
    }
    clusters = find_clusters(scores=scores)
    mu = [c for c in clusters if c.ticker == "MU" and c.direction == "long"]
    assert mu
    c = mu[0]
    assert c.score_components["insider_confluence_mult"] == 1.0
    assert c.score_components["n_insider_buyers"] == 0


def test_all_knobs_compose_for_max_lift() -> None:
    create_all()
    # 2 politicians, one high-conviction, with insider co-buying.
    store.upsert_disclosed_trades([
        _row("insider", "Insider X", "ASML", "buy", date(2026, 4, 1), date(2026, 4, 2)),
        _row("insider", "Insider Y", "ASML", "buy", date(2026, 4, 3), date(2026, 4, 4)),
        _row("senate", "Liam", "ASML", "buy", date(2026, 4, 5), date(2026, 4, 10)),
        _row("house",  "Mia",  "ASML", "buy", date(2026, 4, 8), date(2026, 4, 14)),
    ])
    scores = {
        "Liam": PoliticianScore("Liam", 0.10, 6, True),  # high conviction
        "Mia":  PoliticianScore("Mia",  0.02, 2, True),
    }
    clusters = find_clusters(scores=scores)
    asml = [c for c in clusters if c.ticker == "ASML" and c.direction == "long"]
    assert asml
    c = asml[0]
    # base 0.4 × quality 1.2 × conviction 1.2 × insider 1.15 = 0.6624
    assert c.score == pytest.approx(0.6624, rel=1e-3)
