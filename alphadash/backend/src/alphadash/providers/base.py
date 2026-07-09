"""Provider protocols + errors (S0.3 frozen contract).

Sync protocols on purpose — they match the existing ``jay_trading`` clients, and FastAPI runs sync
dependencies in a threadpool. Real implementations land in S1.1; the stub in ``stub.py`` is the
only implementation until then.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from alphadash.providers.dto import Bar, FundamentalSnapshot, MacroPoint, NewsItem, Quote


class ProviderError(Exception):
    """Base error for any provider failure."""


class StaleDataError(ProviderError):
    """Raised when data is too stale to use even as a degraded input."""


@runtime_checkable
class MarketDataProvider(Protocol):
    def get_quote(self, symbol: str) -> Quote: ...

    def get_bars(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Bar]: ...


@runtime_checkable
class NewsProvider(Protocol):
    def get_news(self, symbols: list[str], since: datetime, limit: int = 50) -> list[NewsItem]: ...


@runtime_checkable
class FundamentalsProvider(Protocol):
    def get_fundamentals(self, symbol: str) -> FundamentalSnapshot: ...


@runtime_checkable
class MacroProvider(Protocol):
    def get_series(self, series_id: str, since: datetime) -> list[MacroPoint]: ...
