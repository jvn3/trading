"""Real S0.3 provider implementations backed by the ``jay_trading`` engine clients (S1.1).

- Market data + fundamentals: ``jay_trading.data.fmp.FMPClient`` (rate-limited, retrying).
- Macro: ``jay_trading.data.fred.FREDClient``.
- News: FMP's stock-news API via a small httpx adapter here — the engine's FMP client has no
  news endpoint and its endpoint table is not ours to extend (live engine stays untouched).

Every DTO leaving this module carries provenance and has been stamped by the ``FreshnessPolicy``.
``now_fn`` is injected everywhere (repo convention: no wall-clock inside logic).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from datetime import time as dt_time
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from alphadash.providers.base import ProviderError
from alphadash.providers.cache import TTLCache
from alphadash.providers.dto import (
    Bar,
    FundamentalSnapshot,
    MacroPoint,
    NewsItem,
    Provenance,
    Quote,
)
from alphadash.providers.freshness import FreshnessPolicy

log = logging.getLogger(__name__)

# Default freshness budget per feed. Quotes are EOD-grade from FMP /stable/quote (delayed), so
# the budget is generous; suggestion-time strictness is the risk layer's call, not ours.
DEFAULT_FRESHNESS = FreshnessPolicy(
    max_age={
        "quote": timedelta(minutes=30),
        "bar": timedelta(days=4),  # EOD bars: allow weekend + holiday gap
        "news": timedelta(days=7),
        "fundamentals": timedelta(days=120),  # quarterly cadence
        "macro": timedelta(days=45),  # monthly series + publication lag
    }
)


def _dec(value: Any, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as e:
        raise ProviderError(f"non-numeric {field!r}: {value!r}") from e


def _dec_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


class FMPMarketDataProvider:
    """MarketDataProvider over FMP quote + EOD historical prices."""

    def __init__(
        self,
        fmp: Any,  # jay_trading.data.fmp.FMPClient (Any: engine type, duck-typed here)
        *,
        policy: FreshnessPolicy = DEFAULT_FRESHNESS,
        now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
        cache_ttl_seconds: float = 60.0,
    ) -> None:
        self._fmp = fmp
        self._policy = policy
        self._now = now_fn
        self._quote_cache = TTLCache(cache_ttl_seconds)
        self._bars_cache = TTLCache(cache_ttl_seconds * 15)

    def get_quote(self, symbol: str) -> Quote:
        raw = self._quote_cache.get_or_load(symbol, lambda: self._fmp.quote(symbol))
        ts = raw.get("timestamp")
        as_of = (
            datetime.fromtimestamp(int(ts), tz=UTC) if isinstance(ts, (int, float)) else self._now()
        )
        quote = Quote(
            symbol=symbol.upper(),
            price=_dec(raw.get("price"), "price"),
            bid=_dec_or_none(raw.get("bid")),
            ask=_dec_or_none(raw.get("ask")),
            provenance=Provenance(source="fmp:quote", as_of=as_of),
        )
        return self._policy.stamp("quote", quote, now=self._now())

    def get_bars(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> list[Bar]:
        if timeframe != "1D":
            raise ProviderError(f"FMP EOD provider supports timeframe '1D' only, got {timeframe!r}")
        key = (symbol.upper(), start.date(), end.date())
        rows = self._bars_cache.get_or_load(
            key, lambda: self._fmp.historical_prices(symbol, from_=start.date(), to=end.date())
        )
        bars: list[Bar] = []
        for row in rows:
            d = row.get("date")
            try:
                bar_date = date.fromisoformat(str(d)[:10])
            except ValueError:
                log.warning("dropping FMP bar with bad date %r for %s", d, symbol)
                continue
            ts = datetime.combine(bar_date, dt_time(0, 0), tzinfo=UTC)
            bar = Bar(
                symbol=symbol.upper(),
                timeframe="1D",
                open=_dec(row.get("open"), "open"),
                high=_dec(row.get("high"), "high"),
                low=_dec(row.get("low"), "low"),
                close=_dec(row.get("close"), "close"),
                volume=_dec(row.get("volume") or 0, "volume"),
                ts=ts,
                provenance=Provenance(source="fmp:historical", as_of=ts),
            )
            bars.append(self._policy.stamp("bar", bar, now=self._now()))
        bars.sort(key=lambda b: b.ts)
        return bars


class FMPNewsProvider:
    """NewsProvider over FMP's stock-news endpoint (own adapter — engine client lacks news)."""

    PATHS = ("/stable/news/stock", "/api/v3/stock_news")

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://financialmodelingprep.com",
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
        cache_ttl_seconds: float = 300.0,
    ) -> None:
        self._api_key = api_key
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={"User-Agent": "alphadash/0.1"},
            transport=transport,
        )
        self._cache = TTLCache(cache_ttl_seconds)

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
    )
    def _get(self, path: str, params: dict[str, Any]) -> httpx.Response:
        return self._client.get(path, params={**params, "apikey": self._api_key})

    def _fetch(self, symbols: tuple[str, ...], limit: int) -> list[dict[str, Any]]:
        last_error = "no path attempted"
        for path in self.PATHS:
            params = (
                {"symbols": ",".join(symbols), "limit": limit}
                if path.startswith("/stable")
                else {"tickers": ",".join(symbols), "limit": limit}
            )
            resp = self._get(path, params)
            if resp.status_code == 200:
                body = resp.json()
                if isinstance(body, list):
                    return body
                last_error = f"unexpected body shape at {path}"
                continue
            if resp.status_code in (401, 403):
                raise ProviderError(f"FMP news auth failure: HTTP {resp.status_code}")
            last_error = f"HTTP {resp.status_code} at {path}"
        raise ProviderError(f"all FMP news paths failed: {last_error}")

    def get_news(self, symbols: list[str], since: datetime, limit: int = 50) -> list[NewsItem]:
        wanted = tuple(s.upper() for s in symbols)
        rows = self._cache.get_or_load((wanted, limit), lambda: self._fetch(wanted, limit))
        items: list[NewsItem] = []
        for row in rows:
            published = _parse_dt(row.get("publishedDate") or row.get("date"))
            if published is None or published < since:
                continue
            symbol = str(row.get("symbol") or "").upper()
            items.append(
                NewsItem(
                    id=str(row.get("url") or f"{symbol}-{published.isoformat()}"),
                    symbols=[symbol] if symbol else list(wanted),
                    headline=str(row.get("title") or ""),
                    summary=(str(row["text"]) if row.get("text") else None),
                    url=(str(row["url"]) if row.get("url") else None),
                    published_at=published,
                    source=str(row.get("site") or row.get("publisher") or "fmp:news"),
                    sentiment=None,  # sentiment scoring is S4.4, not pretend-data now
                )
            )
        items.sort(key=lambda n: n.published_at, reverse=True)
        return items[:limit]

    def close(self) -> None:
        self._client.close()


class FMPFundamentalsProvider:
    """FundamentalsProvider over FMP financial-scores (+ratios in future sessions)."""

    def __init__(
        self,
        fmp: Any,
        *,
        policy: FreshnessPolicy = DEFAULT_FRESHNESS,
        now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
        cache_ttl_seconds: float = 3600.0,
    ) -> None:
        self._fmp = fmp
        self._policy = policy
        self._now = now_fn
        self._cache = TTLCache(cache_ttl_seconds)

    def get_fundamentals(self, symbol: str) -> FundamentalSnapshot:
        rows = self._cache.get_or_load(
            symbol.upper(),
            lambda: self._fmp.request("financial_scores", params={"symbol": symbol.upper()}),
        )
        row = rows[0] if isinstance(rows, list) and rows else rows if isinstance(rows, dict) else {}
        if not row:
            raise ProviderError(f"no fundamentals returned for {symbol!r}")
        metrics: dict[str, Decimal] = {}
        for key, value in row.items():
            if key in ("symbol", "reportedCurrency"):
                continue
            dec = _dec_or_none(value)
            if dec is not None:
                metrics[key] = dec
        as_of = self._now()  # financial-scores payload carries no as-of; stamp retrieval time
        snapshot = FundamentalSnapshot(
            symbol=symbol.upper(),
            as_of=as_of,
            metrics=metrics,
            provenance=Provenance(source="fmp:financial_scores", as_of=as_of),
        )
        return self._policy.stamp("fundamentals", snapshot, now=self._now())


class FREDMacroProvider:
    """MacroProvider over the engine's FRED CSV client."""

    def __init__(
        self,
        fred: Any,  # jay_trading.data.fred.FREDClient
        *,
        policy: FreshnessPolicy = DEFAULT_FRESHNESS,
        now_fn: Callable[[], datetime] = lambda: datetime.now(UTC),
        cache_ttl_seconds: float = 3600.0,
    ) -> None:
        self._fred = fred
        self._policy = policy
        self._now = now_fn
        self._cache = TTLCache(cache_ttl_seconds)

    def get_series(self, series_id: str, since: datetime) -> list[MacroPoint]:
        observations = self._cache.get_or_load(series_id, lambda: self._fred.get_series(series_id))
        points: list[MacroPoint] = []
        for obs in observations:
            if obs.value is None:
                continue
            ts = datetime.combine(obs.date, dt_time(0, 0), tzinfo=UTC)
            if ts < since:
                continue
            point = MacroPoint(
                series_id=series_id,
                ts=ts,
                value=_dec(obs.value, "value"),
                provenance=Provenance(source=f"fred:{series_id}", as_of=ts),
            )
            points.append(self._policy.stamp("macro", point, now=self._now()))
        return points


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
