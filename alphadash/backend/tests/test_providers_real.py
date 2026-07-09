"""S1.1 tests: real providers normalized to S0.3 DTOs, freshness stamped, caching, backoff.

Unit tests run against fakes — no network, no jay_trading import (the real providers are
duck-typed over the engine clients). Live-API tests are marked ``integration``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from alphadash.providers.base import ProviderError
from alphadash.providers.cache import TTLCache
from alphadash.providers.real import (
    FMPFundamentalsProvider,
    FMPMarketDataProvider,
    FMPNewsProvider,
    FREDMacroProvider,
)

NOW = datetime(2026, 7, 8, 15, 0, tzinfo=UTC)


def fixed_now() -> datetime:
    return NOW


class FakeFMP:
    def __init__(self) -> None:
        self.quote_calls = 0

    def quote(self, symbol: str) -> dict:
        self.quote_calls += 1
        return {
            "symbol": symbol.upper(),
            "price": 210.5,
            "timestamp": int(NOW.timestamp()) - 60,
        }

    def historical_prices(self, symbol: str, from_=None, to=None) -> list[dict]:
        return [
            {
                "date": "2026-07-07",
                "open": 209,
                "high": 211,
                "low": 208,
                "close": 210,
                "volume": 1000,
            },
            {
                "date": "2026-07-06",
                "open": 207,
                "high": 210,
                "low": 206,
                "close": 209,
                "volume": 900,
            },
            {"date": "bogus", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1},
        ]

    def request(self, endpoint_key: str, params=None) -> list[dict]:
        assert endpoint_key == "financial_scores"
        return [
            {
                "symbol": params["symbol"],
                "altmanZScore": 5.13,
                "piotroskiScore": 7,
                "workingCapital": 60000000000,
                "reportedCurrency": "USD",
            }
        ]


@dataclass(frozen=True)
class FakeObservation:
    date: date
    value: float | None


class FakeFRED:
    def get_series(self, series_id: str) -> list[FakeObservation]:
        return [
            FakeObservation(date(2026, 5, 1), 4.33),
            FakeObservation(date(2026, 6, 1), None),  # FRED gap — must be dropped
            FakeObservation(date(2026, 7, 1), 4.08),
        ]


# --- Market data -----------------------------------------------------------


def test_quote_normalized_and_fresh() -> None:
    provider = FMPMarketDataProvider(FakeFMP(), now_fn=fixed_now)
    q = provider.get_quote("aapl")
    assert q.symbol == "AAPL"
    assert q.price == Decimal("210.5")
    assert q.provenance.source == "fmp:quote"
    assert q.provenance.is_stale is False  # 60s old vs 30min budget


def test_quote_cached_within_ttl() -> None:
    fake = FakeFMP()
    provider = FMPMarketDataProvider(fake, now_fn=fixed_now)
    provider.get_quote("AAPL")
    provider.get_quote("AAPL")
    assert fake.quote_calls == 1


def test_bars_sorted_normalized_bad_rows_dropped() -> None:
    provider = FMPMarketDataProvider(FakeFMP(), now_fn=fixed_now)
    bars = provider.get_bars("AAPL", "1D", NOW - timedelta(days=5), NOW)
    assert [b.ts.date().isoformat() for b in bars] == ["2026-07-06", "2026-07-07"]
    assert bars[0].close == Decimal("209")
    assert all(b.provenance.source == "fmp:historical" for b in bars)
    assert bars[-1].provenance.is_stale is False  # 1 day old vs 4-day budget


def test_bars_reject_unsupported_timeframe() -> None:
    provider = FMPMarketDataProvider(FakeFMP(), now_fn=fixed_now)
    with pytest.raises(ProviderError, match="1D"):
        provider.get_bars("AAPL", "5Min", NOW - timedelta(days=1), NOW)


def test_quote_non_numeric_price_raises() -> None:
    class BadFMP(FakeFMP):
        def quote(self, symbol: str) -> dict:
            return {"price": "n/a"}

    provider = FMPMarketDataProvider(BadFMP(), now_fn=fixed_now)
    with pytest.raises(ProviderError, match="price"):
        provider.get_quote("AAPL")


# --- News (httpx MockTransport — exercises the real HTTP adapter) -----------


def _news_transport(payload: list[dict], *, fail_first: bool = False) -> httpx.MockTransport:
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        assert "apikey" in request.url.params
        if fail_first and state["calls"] == 1:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


NEWS_PAYLOAD = [
    {
        "symbol": "AAPL",
        "publishedDate": "2026-07-08 09:30:00",
        "title": "Apple headline",
        "text": "Body",
        "site": "Reuters",
        "url": "https://example.com/a",
    },
    {
        "symbol": "AAPL",
        "publishedDate": "2026-06-01 09:30:00",  # older than `since` — filtered
        "title": "Old news",
        "site": "Reuters",
        "url": "https://example.com/old",
    },
]


def test_news_normalized_filtered_sorted() -> None:
    provider = FMPNewsProvider(api_key="k", transport=_news_transport(NEWS_PAYLOAD))
    items = provider.get_news(["aapl"], since=NOW - timedelta(days=7))
    assert len(items) == 1
    item = items[0]
    assert item.headline == "Apple headline"
    assert item.symbols == ["AAPL"]
    assert item.source == "Reuters"
    assert item.published_at.tzinfo is not None
    assert item.sentiment is None


def test_news_retries_transient_transport_error() -> None:
    provider = FMPNewsProvider(
        api_key="k", transport=_news_transport(NEWS_PAYLOAD, fail_first=True)
    )
    items = provider.get_news(["AAPL"], since=NOW - timedelta(days=7))
    assert len(items) == 1  # first attempt exploded, tenacity retried


def test_news_auth_failure_raises() -> None:
    transport = httpx.MockTransport(lambda req: httpx.Response(401, json={}))
    provider = FMPNewsProvider(api_key="bad", transport=transport)
    with pytest.raises(ProviderError, match="auth"):
        provider.get_news(["AAPL"], since=NOW - timedelta(days=7))


# --- Fundamentals ------------------------------------------------------------


def test_fundamentals_metrics_decimal_and_stamped() -> None:
    provider = FMPFundamentalsProvider(FakeFMP(), now_fn=fixed_now)
    snap = provider.get_fundamentals("aapl")
    assert snap.symbol == "AAPL"
    assert snap.metrics["altmanZScore"] == Decimal("5.13")
    assert "reportedCurrency" not in snap.metrics  # non-numeric fields excluded
    assert all(isinstance(v, Decimal) for v in snap.metrics.values())
    assert snap.provenance.is_stale is False


# --- Macro -------------------------------------------------------------------


def test_macro_series_since_filter_and_gap_dropping() -> None:
    provider = FREDMacroProvider(FakeFRED(), now_fn=fixed_now)
    points = provider.get_series("FEDFUNDS", since=datetime(2026, 6, 1, tzinfo=UTC))
    assert [p.value for p in points] == [Decimal("4.08")]  # gap dropped, old point filtered
    assert points[0].provenance.source == "fred:FEDFUNDS"
    assert points[0].provenance.is_stale is False  # 7 days old vs 45-day budget


# --- Cache primitive ----------------------------------------------------------


def test_ttl_cache_expires() -> None:
    clock = {"t": 0.0}
    cache = TTLCache(ttl_seconds=10, clock=lambda: clock["t"])
    calls = {"n": 0}

    def loader():
        calls["n"] += 1
        return calls["n"]

    assert cache.get_or_load("k", loader) == 1
    assert cache.get_or_load("k", loader) == 1
    clock["t"] = 11.0
    assert cache.get_or_load("k", loader) == 2


# --- Live integration (opt-in) --------------------------------------------------


@pytest.mark.integration
def test_live_fmp_quote_and_bars() -> None:
    from alphadash.config import get_settings
    from alphadash.providers.factory import build_real_bundle

    bundle = build_real_bundle(get_settings())
    q = bundle.market_data.get_quote("AAPL")
    assert q.price > 0
    bars = bundle.market_data.get_bars(
        "AAPL", "1D", datetime.now(UTC) - timedelta(days=10), datetime.now(UTC)
    )
    assert bars and bars[-1].close > 0


@pytest.mark.integration
def test_live_news_fundamentals_macro() -> None:
    from alphadash.config import get_settings
    from alphadash.providers.factory import build_real_bundle

    bundle = build_real_bundle(get_settings())
    news = bundle.news.get_news(["AAPL"], since=datetime.now(UTC) - timedelta(days=14))
    assert isinstance(news, list)
    snap = bundle.fundamentals.get_fundamentals("AAPL")
    assert snap.metrics
    points = bundle.macro.get_series("FEDFUNDS", since=datetime.now(UTC) - timedelta(days=365))
    assert points
