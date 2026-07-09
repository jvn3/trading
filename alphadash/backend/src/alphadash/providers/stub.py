"""Deterministic fixture-backed provider stub (S0.3).

Implements every S0.3 protocol from in-memory fixtures — no network, no randomness, no wall-clock.
Unit tests and early UI work run against this; real ``jay_trading``-backed providers land in S1.1.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from alphadash.providers.dto import (
    Bar,
    FundamentalSnapshot,
    MacroPoint,
    NewsItem,
    Provenance,
    Quote,
)

STUB_SOURCE = "stub"

# Fixed anchor so every fixture timestamp is deterministic.
FIXTURE_AS_OF = datetime(2026, 7, 1, 14, 30, tzinfo=UTC)

_QUOTES: dict[str, dict[str, Decimal]] = {
    "AAPL": {"price": Decimal("210.50"), "bid": Decimal("210.48"), "ask": Decimal("210.52")},
    "MSFT": {"price": Decimal("455.10"), "bid": Decimal("455.05"), "ask": Decimal("455.15")},
    "BTCUSD": {
        "price": Decimal("67250.00"),
        "bid": Decimal("67245.00"),
        "ask": Decimal("67255.00"),
    },
}

_FUNDAMENTALS: dict[str, dict[str, Decimal]] = {
    "AAPL": {
        "pe_ratio": Decimal("32.10"),
        "eps_ttm": Decimal("6.56"),
        "revenue_ttm": Decimal("391000000000"),
    },
    "MSFT": {
        "pe_ratio": Decimal("36.80"),
        "eps_ttm": Decimal("12.37"),
        "revenue_ttm": Decimal("245000000000"),
    },
}

_MACRO: dict[str, list[tuple[datetime, Decimal]]] = {
    "FEDFUNDS": [
        (FIXTURE_AS_OF - timedelta(days=60), Decimal("4.33")),
        (FIXTURE_AS_OF - timedelta(days=30), Decimal("4.33")),
        (FIXTURE_AS_OF, Decimal("4.08")),
    ],
}

_NEWS: list[NewsItem] = [
    NewsItem(
        id="stub-news-1",
        symbols=["AAPL"],
        headline="Apple announces new on-device AI features",
        summary="Deterministic stub headline for testing.",
        url="https://example.com/stub-news-1",
        published_at=FIXTURE_AS_OF - timedelta(hours=2),
        source=STUB_SOURCE,
        sentiment=0.4,
    ),
    NewsItem(
        id="stub-news-2",
        symbols=["MSFT", "AAPL"],
        headline="Big tech capex guidance steady",
        summary=None,
        url=None,
        published_at=FIXTURE_AS_OF - timedelta(hours=8),
        source=STUB_SOURCE,
        sentiment=0.1,
    ),
    NewsItem(
        id="stub-news-3",
        symbols=["BTCUSD"],
        headline="Crypto volumes flat week over week",
        summary=None,
        url=None,
        published_at=FIXTURE_AS_OF - timedelta(days=2),
        source=STUB_SOURCE,
        sentiment=-0.1,
    ),
]


def _provenance(as_of: datetime = FIXTURE_AS_OF) -> Provenance:
    return Provenance(source=STUB_SOURCE, as_of=as_of)


class StubProviders:
    """One object implementing all four S0.3 protocols from deterministic fixtures."""

    # MarketDataProvider ----------------------------------------------------

    def get_quote(self, symbol: str) -> Quote:
        fixture = _QUOTES.get(symbol, {"price": Decimal("100.00"), "bid": None, "ask": None})
        return Quote(
            symbol=symbol,
            price=fixture["price"],
            bid=fixture.get("bid"),
            ask=fixture.get("ask"),
            provenance=_provenance(),
        )

    def get_bars(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> list[Bar]:
        base = _QUOTES.get(symbol, {"price": Decimal("100.00")})["price"]
        bars: list[Bar] = []
        step = timedelta(days=1)
        ts = start
        offset = Decimal("0")
        while ts <= end:
            open_ = base + offset
            close = open_ + Decimal("0.50")
            bars.append(
                Bar(
                    symbol=symbol,
                    timeframe=timeframe,
                    open=open_,
                    high=close + Decimal("0.25"),
                    low=open_ - Decimal("0.25"),
                    close=close,
                    volume=Decimal("1000000"),
                    ts=ts,
                    provenance=_provenance(as_of=ts),
                )
            )
            ts += step
            offset += base * Decimal("0.005")  # ~0.5%/day drift → momentum rules can fire in dev
        return bars

    # NewsProvider ----------------------------------------------------------

    def get_news(self, symbols: list[str], since: datetime, limit: int = 50) -> list[NewsItem]:
        wanted = set(symbols)
        hits = [
            item
            for item in _NEWS
            if item.published_at >= since and (not wanted or wanted & set(item.symbols))
        ]
        return hits[:limit]

    # FundamentalsProvider ----------------------------------------------------

    def get_fundamentals(self, symbol: str) -> FundamentalSnapshot:
        metrics = _FUNDAMENTALS.get(symbol, {"pe_ratio": Decimal("20.00")})
        return FundamentalSnapshot(
            symbol=symbol,
            as_of=FIXTURE_AS_OF,
            metrics=dict(metrics),
            provenance=_provenance(),
        )

    # MacroProvider -----------------------------------------------------------

    def get_series(self, series_id: str, since: datetime) -> list[MacroPoint]:
        points = _MACRO.get(series_id, [])
        return [
            MacroPoint(series_id=series_id, ts=ts, value=value, provenance=_provenance(as_of=ts))
            for ts, value in points
            if ts >= since
        ]
