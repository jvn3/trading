"""S0.3 tests: stub implements every protocol, fixtures deterministic, staleness stamped."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from alphadash.providers.base import (
    FundamentalsProvider,
    MacroProvider,
    MarketDataProvider,
    NewsProvider,
    ProviderError,
    StaleDataError,
)
from alphadash.providers.dto import Provenance, Quote
from alphadash.providers.freshness import FreshnessPolicy
from alphadash.providers.stub import FIXTURE_AS_OF, STUB_SOURCE, StubProviders


def test_stub_satisfies_all_protocols() -> None:
    stub = StubProviders()
    assert isinstance(stub, MarketDataProvider)
    assert isinstance(stub, NewsProvider)
    assert isinstance(stub, FundamentalsProvider)
    assert isinstance(stub, MacroProvider)


def test_quote_deterministic_with_provenance() -> None:
    stub = StubProviders()
    q1 = stub.get_quote("AAPL")
    q2 = stub.get_quote("AAPL")
    assert q1 == q2
    assert q1.price == Decimal("210.50")
    assert isinstance(q1.price, Decimal)
    assert q1.provenance.source == STUB_SOURCE
    assert q1.provenance.as_of == FIXTURE_AS_OF
    assert q1.provenance.is_stale is False


def test_bars_span_range_with_per_bar_provenance() -> None:
    stub = StubProviders()
    start = FIXTURE_AS_OF - timedelta(days=4)
    bars = stub.get_bars("MSFT", "1D", start, FIXTURE_AS_OF)
    assert len(bars) == 5
    assert bars[0].ts == start
    assert all(b.provenance.as_of == b.ts for b in bars)
    assert all(isinstance(b.close, Decimal) for b in bars)
    assert all(b.high >= b.low for b in bars)


def test_news_filters_by_symbol_since_and_limit() -> None:
    stub = StubProviders()
    since = FIXTURE_AS_OF - timedelta(days=7)
    aapl = stub.get_news(["AAPL"], since)
    assert {n.id for n in aapl} == {"stub-news-1", "stub-news-2"}
    recent = stub.get_news(["AAPL"], FIXTURE_AS_OF - timedelta(hours=3))
    assert {n.id for n in recent} == {"stub-news-1"}
    limited = stub.get_news(["AAPL"], since, limit=1)
    assert len(limited) == 1


def test_fundamentals_and_macro_fixtures() -> None:
    stub = StubProviders()
    fund = stub.get_fundamentals("AAPL")
    assert fund.metrics["pe_ratio"] == Decimal("32.10")
    assert fund.provenance.source == STUB_SOURCE

    points = stub.get_series("FEDFUNDS", FIXTURE_AS_OF - timedelta(days=90))
    assert len(points) == 3
    assert points[-1].value == Decimal("4.08")
    empty = stub.get_series("FEDFUNDS", FIXTURE_AS_OF + timedelta(days=1))
    assert empty == []


def _quote_as_of(as_of: datetime) -> Quote:
    return Quote(
        symbol="AAPL",
        price=Decimal("210.50"),
        provenance=Provenance(source=STUB_SOURCE, as_of=as_of),
    )


def test_freshness_stamp_fresh_and_stale() -> None:
    policy = FreshnessPolicy(max_age={"quote": timedelta(minutes=5)})
    now = datetime(2026, 7, 1, 15, 0, tzinfo=UTC)

    fresh = policy.stamp("quote", _quote_as_of(now - timedelta(minutes=4)), now=now)
    assert fresh.provenance.is_stale is False

    boundary = policy.stamp("quote", _quote_as_of(now - timedelta(minutes=5)), now=now)
    assert boundary.provenance.is_stale is False  # exactly max_age is not (>) stale

    stale = policy.stamp("quote", _quote_as_of(now - timedelta(minutes=5, seconds=1)), now=now)
    assert stale.provenance.is_stale is True


def test_error_hierarchy() -> None:
    assert issubclass(StaleDataError, ProviderError)
    assert issubclass(ProviderError, Exception)


def test_no_jay_trading_import() -> None:
    import sys

    import alphadash.providers.base  # noqa: F401
    import alphadash.providers.dto  # noqa: F401
    import alphadash.providers.freshness  # noqa: F401
    import alphadash.providers.stub  # noqa: F401

    assert not any(mod.startswith("jay_trading") for mod in sys.modules)
