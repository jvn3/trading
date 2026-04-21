"""Tests for :mod:`jay_trading.signals.insider_cluster_detector`."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from jay_trading.data import models, store
from jay_trading.data.db import create_all, session_scope
from jay_trading.data.fmp import _dedup_key
from jay_trading.signals import insider_cluster_detector
from jay_trading.signals.insider_cluster_detector import (
    STRATEGY_NAME,
    find_insider_clusters,
    upsert_insider_signals,
)


def _insider_row(
    person: str, ticker: str, *, role: str = "director", tx_date: date | None = None,
    filing_date: date | None = None, url: str = "",
) -> dict[str, Any]:
    tx = tx_date or date.today() - timedelta(days=5)
    fd = filing_date or tx
    return {
        "source": "insider",
        "person_name": person,
        "person_role": role,
        "ticker": ticker.upper(),
        "transaction_type": "buy",
        "transaction_date": tx,
        "filing_date": fd,
        "amount_low": 50_000.0,
        "amount_high": 50_000.0,
        "amount_exact": 50_000.0,
        "dedup_key": _dedup_key("insider", [person, ticker, tx, fd, role, url]),
        "raw_payload": {
            "transactionType": "P-Purchase",
            "typeOfOwner": role,
            "url": url,
            "securitiesTransacted": 100,
            "price": 50.0,
        },
    }


def _stub_fmp(piotroski: int | None = 7) -> Any:
    class _Stub:
        def request(self, endpoint_key: str, params: dict[str, Any] | None = None, **_: Any) -> Any:
            if endpoint_key == "financial_scores":
                return [{"symbol": params["symbol"], "piotroskiScore": piotroski}]
            raise KeyError(endpoint_key)

        def close(self) -> None: pass

    return _Stub()


def _no_edgar() -> bool:
    """check_edgar=False in tests to avoid live network."""
    return False


def test_cluster_requires_three_distinct_insiders() -> None:
    create_all()
    # Only 2 insiders → no cluster.
    rows = [
        _insider_row("Alice", "NVDA"),
        _insider_row("Bob", "NVDA"),
    ]
    store.upsert_disclosed_trades(rows)
    clusters = find_insider_clusters(check_edgar=False, fmp=_stub_fmp())
    assert clusters == []


def test_cluster_with_three_distinct_insiders_fires() -> None:
    create_all()
    rows = [
        _insider_row("Alice", "NVDA", role="officer: CEO"),
        _insider_row("Bob", "NVDA", role="officer: CFO"),
        _insider_row("Carol", "NVDA", role="director"),
    ]
    store.upsert_disclosed_trades(rows)
    clusters = find_insider_clusters(check_edgar=False, fmp=_stub_fmp(piotroski=7))
    assert len(clusters) == 1
    c = clusters[0]
    assert c.ticker == "NVDA"
    assert c.direction == "long"
    # weighted_count = 3.0 + 2.5 + 1.0 = 6.5
    assert c.weighted_count == 6.5
    assert c.piotroski == 7
    # base = 6.5/10 = 0.65; piotroski_mult=1.2 (score >=7); recency=1.1 (today-5d=5d)
    assert 0.0 < c.score <= 1.0
    assert c.score > 0.4  # above the strategy threshold


def test_cluster_score_drops_with_weak_piotroski() -> None:
    create_all()
    rows = [
        _insider_row("Alice", "MSFT", role="officer: CEO"),
        _insider_row("Bob", "MSFT", role="officer: CFO"),
        _insider_row("Carol", "MSFT", role="director"),
    ]
    store.upsert_disclosed_trades(rows)
    strong = find_insider_clusters(check_edgar=False, fmp=_stub_fmp(piotroski=8))
    weak = find_insider_clusters(check_edgar=False, fmp=_stub_fmp(piotroski=3))
    assert strong[0].score > weak[0].score


def test_old_filings_outside_window_do_not_form_cluster() -> None:
    create_all()
    # 3 insiders but filings spread across 45 days (> 30-day window).
    rows = [
        _insider_row("Alice", "TSLA", filing_date=date.today() - timedelta(days=45)),
        _insider_row("Bob",   "TSLA", filing_date=date.today() - timedelta(days=25)),
        _insider_row("Carol", "TSLA", filing_date=date.today() - timedelta(days=1)),
    ]
    store.upsert_disclosed_trades(rows)
    clusters = find_insider_clusters(check_edgar=False, fmp=_stub_fmp())
    # The 45-day-old filing is outside any 30-day window with the other two,
    # leaving only 2 distinct insiders in any valid window → no cluster.
    assert clusters == []


def test_signals_dedup_across_upsert_calls() -> None:
    create_all()
    rows = [
        _insider_row("Alice", "AAPL", role="officer: CEO"),
        _insider_row("Bob", "AAPL", role="officer: CFO"),
        _insider_row("Carol", "AAPL", role="director"),
    ]
    store.upsert_disclosed_trades(rows)
    clusters = find_insider_clusters(check_edgar=False, fmp=_stub_fmp())
    assert len(clusters) >= 1

    first = upsert_insider_signals(clusters)
    second = upsert_insider_signals(clusters)
    assert first >= 1
    assert second == 0  # idempotent


def test_signal_row_has_insider_follow_strategy_name() -> None:
    create_all()
    rows = [
        _insider_row("Alice", "GOOG", role="officer: CEO"),
        _insider_row("Bob", "GOOG", role="officer: CFO"),
        _insider_row("Carol", "GOOG", role="director"),
    ]
    store.upsert_disclosed_trades(rows)
    clusters = find_insider_clusters(check_edgar=False, fmp=_stub_fmp())
    upsert_insider_signals(clusters)

    with session_scope() as s:
        from sqlalchemy import select
        sig = s.scalar(select(models.Signal).where(models.Signal.ticker == "GOOG"))
        assert sig is not None
        assert sig.strategy_name == STRATEGY_NAME
        assert sig.direction == "long"
