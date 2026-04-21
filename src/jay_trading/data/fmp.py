"""FMP client.

Endpoints are centralized in :data:`ENDPOINTS`. FMP periodically moves paths
between ``/api/v3/``, ``/api/v4/``, and ``/stable/``. When an endpoint 404s we
log loudly and surface the error — we do **not** silently swallow.

All requests go through :class:`FMPClient.request`, which applies:

- a small token-bucket rate limiter (default 250/min — below the 300/min
  Starter cap for safety),
- retries via :mod:`tenacity` on 5xx/network errors (not 4xx, which are
  programmer errors or paywalled endpoints),
- ``api_key`` query-param injection (the key never appears in logs).
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable

import httpx
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from jay_trading.config import get_settings

log = logging.getLogger(__name__)

# Base URL is stable; endpoint *paths* shift. Try multiple paths, take the
# first one that returns 200.
BASE_URL = "https://financialmodelingprep.com"

#: Centralized FMP endpoint paths.
#:
#: Empirically probed on 2026-04-19 against the upgraded plan:
#: - ``/stable/*-latest`` endpoints are the "daily firehose" (paginated).
#: - ``/stable/*-trades`` / ``/stable/insider-trading/search`` endpoints are
#:   per-ticker historical lookups (require ``symbol=``).
#: Everything under ``/api/v4/`` is legacy-only and 403s for new subscribers.
ENDPOINTS: dict[str, tuple[str, ...]] = {
    # Congressional disclosures -- firehose (no symbol required)
    "senate_trades": ("/stable/senate-latest",),
    "house_trades": ("/stable/house-latest",),
    # Congressional disclosures -- per-ticker historical
    "senate_trades_by_symbol": ("/stable/senate-trades",),
    "house_trades_by_symbol": ("/stable/house-trades",),
    # Corporate insider Form 4
    "insider_trades": ("/stable/insider-trading/latest",),
    "insider_trades_by_symbol": ("/stable/insider-trading/search",),
    # Market data
    "quote": ("/stable/quote",),
    "historical": ("/stable/historical-price-eod/full",),
    "profile": ("/stable/profile",),
    "sector_perf": (
        "/stable/sectors-performance",
        "/api/v3/stock/sectors-performance",
    ),
    # Fundamentals (used by insider_follow Piotroski gate + correlation cap)
    "financial_scores": ("/stable/financial-scores",),
}


class FMPError(RuntimeError):
    """Raised for non-retryable FMP failures (4xx, schema, etc.)."""


@dataclass
class _TokenBucket:
    """A very small thread-safe token bucket."""

    rate_per_sec: float
    capacity: int
    _tokens: float = 0.0
    _last: float = 0.0
    _lock: threading.Lock = threading.Lock()  # type: ignore[assignment]

    def __post_init__(self) -> None:
        # dataclass default_factory for Lock is awkward; just reset here.
        self._lock = threading.Lock()
        self._tokens = float(self.capacity)
        self._last = time.monotonic()

    def take(self, n: int = 1) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._tokens = min(
                    float(self.capacity), self._tokens + elapsed * self.rate_per_sec
                )
                self._last = now
                if self._tokens >= n:
                    self._tokens -= n
                    return
                # How long until we have enough tokens?
                deficit = n - self._tokens
                sleep_for = deficit / self.rate_per_sec
            time.sleep(sleep_for)


class FMPClient:
    """Thin, retrying, rate-limited FMP HTTP client."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        requests_per_minute: int = 250,
        timeout: float = 20.0,
    ) -> None:
        self._api_key = api_key or get_settings().fmp_api_key
        self._client = httpx.Client(
            base_url=BASE_URL,
            timeout=timeout,
            headers={"User-Agent": "jay-trading/0.1"},
        )
        self._bucket = _TokenBucket(
            rate_per_sec=requests_per_minute / 60.0,
            capacity=max(1, requests_per_minute // 10),
        )

    # Context manager ergonomics
    def __enter__(self) -> "FMPClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    # ---- Low-level request -------------------------------------------------

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
        retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
    )
    def _get(self, path: str, params: dict[str, Any]) -> httpx.Response:
        self._bucket.take(1)
        merged = {**params, "apikey": self._api_key}
        start = time.monotonic()
        try:
            r = self._client.get(path, params=merged)
        except (httpx.TransportError, httpx.TimeoutException) as e:
            # Log the failed attempt BEFORE tenacity retries consume this.
            # Tenacity will re-invoke _get; each attempt gets its own row.
            _log_api_call(
                path, "fail", latency_ms=(time.monotonic() - start) * 1000,
                error_kind=type(e).__name__,
            )
            raise
        ok = 200 <= r.status_code < 300
        _log_api_call(
            path, "ok" if ok else "fail",
            latency_ms=(time.monotonic() - start) * 1000,
            error_kind=None if ok else f"http_{r.status_code}",
        )
        return r

    def request(self, endpoint_key: str, params: dict[str, Any] | None = None,
                path_args: dict[str, str] | None = None) -> Any:
        """Call an endpoint by logical name, trying known path variants in order."""
        paths = ENDPOINTS.get(endpoint_key)
        if not paths:
            raise KeyError(f"unknown FMP endpoint key: {endpoint_key}")
        last_status: int | None = None
        last_body: str = ""
        tried: list[str] = []
        for tmpl in paths:
            path = tmpl.format(**(path_args or {}))
            tried.append(path)
            try:
                r = self._get(path, params or {})
            except RetryError as e:
                last_body = f"retries exhausted: {e!r}"
                continue
            last_status = r.status_code
            if r.status_code == 200:
                body = r.json() if r.text else []
                if isinstance(body, dict) and "Error Message" in body:
                    last_body = f"FMP error body: {body['Error Message']}"
                    continue
                return body
            if r.status_code in (401, 403):
                raise FMPError(
                    f"FMP auth failure on {path}: HTTP {r.status_code}. "
                    f"Check FMP_API_KEY."
                )
            if r.status_code == 404:
                log.warning("FMP 404 on %s -- trying next variant", path)
                last_body = f"404 at {path}"
                continue
            last_body = f"HTTP {r.status_code}: {r.text[:200]!r}"
        raise FMPError(
            f"all FMP paths failed for {endpoint_key!r} "
            f"(tried={tried}, last_status={last_status}, detail={last_body})"
        )

    # ---- Typed endpoint helpers -------------------------------------------

    def _paginated(
        self,
        endpoint_key: str,
        pages: int = 4,
        per_page: int = 100,
        extra_params: dict[str, Any] | None = None,
        fingerprint: tuple[str, ...] = (
            "symbol", "transactionDate", "firstName", "lastName", "amount",
        ),
    ) -> list[dict[str, Any]]:
        """Iterate ``page=0..pages-1`` on a firehose endpoint, dedup across pages."""
        out: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        for p in range(max(1, pages)):
            params: dict[str, Any] = {"page": p, "limit": per_page}
            if extra_params:
                params.update(extra_params)
            try:
                rows = self.request(endpoint_key, params=params)
            except FMPError:
                break
            if not isinstance(rows, list) or not rows:
                break
            new_this_page = 0
            for r in rows:
                fp = tuple(r.get(k) for k in fingerprint)
                if fp in seen:
                    continue
                seen.add(fp)
                out.append(r)
                new_this_page += 1
            if new_this_page == 0:
                break
        return out

    def senate_trades(
        self, pages: int = 2, per_page: int = 100, **_: Any
    ) -> list[dict[str, Any]]:
        return self._paginated("senate_trades", pages=pages, per_page=per_page)

    def house_trades(
        self, pages: int = 2, per_page: int = 100, **_: Any
    ) -> list[dict[str, Any]]:
        return self._paginated("house_trades", pages=pages, per_page=per_page)

    def insider_trades(
        self, ticker: str | None = None, pages: int = 2, per_page: int = 100, **_: Any
    ) -> list[dict[str, Any]]:
        # Per-ticker search uses a different endpoint; no pagination needed.
        if ticker:
            rows = self.request(
                "insider_trades_by_symbol", params={"symbol": ticker.upper()}
            )
            return list(rows) if isinstance(rows, list) else []
        return self._paginated(
            "insider_trades",
            pages=pages,
            per_page=per_page,
            fingerprint=(
                "symbol", "filingDate", "transactionDate",
                "reportingCik", "transactionType",
            ),
        )

    # Per-ticker historical helpers (used by strategies in later phases).
    def senate_trades_for_symbol(self, symbol: str) -> list[dict[str, Any]]:
        rows = self.request(
            "senate_trades_by_symbol", params={"symbol": symbol.upper()}
        )
        return list(rows) if isinstance(rows, list) else []

    def house_trades_for_symbol(self, symbol: str) -> list[dict[str, Any]]:
        rows = self.request(
            "house_trades_by_symbol", params={"symbol": symbol.upper()}
        )
        return list(rows) if isinstance(rows, list) else []

    def quote(self, symbol: str) -> dict[str, Any]:
        rows = self.request("quote", params={"symbol": symbol.upper()})
        if isinstance(rows, list) and rows:
            return rows[0]
        if isinstance(rows, dict):
            return rows
        raise FMPError(f"quote({symbol!r}) returned unexpected shape: {type(rows).__name__}")

    def historical_prices(
        self, symbol: str, from_: date | None = None, to: date | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"symbol": symbol.upper()}
        if from_:
            params["from"] = from_.isoformat()
        if to:
            params["to"] = to.isoformat()
        body = self.request("historical", params=params)
        if isinstance(body, dict) and "historical" in body:
            return list(body["historical"])
        return list(body) if isinstance(body, list) else []

    def sector_performance(self) -> list[dict[str, Any]]:
        rows = self.request("sector_perf", params={})
        return list(rows) if isinstance(rows, list) else []


# ---- Normalization helpers (pure, unit-testable) --------------------------


def _parse_iso_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _parse_amount_range(s: str | None) -> tuple[float | None, float | None]:
    """Politicians report ranges like '$15,001 - $50,000'. Return (low, high)."""
    if not s:
        return None, None
    cleaned = s.replace("$", "").replace(",", "").strip()
    parts = [p.strip() for p in cleaned.replace("to", "-").split("-") if p.strip()]
    try:
        nums = [float(p) for p in parts if p.replace(".", "", 1).isdigit()]
    except ValueError:
        return None, None
    if len(nums) >= 2:
        return nums[0], nums[1]
    if len(nums) == 1:
        return nums[0], nums[0]
    return None, None


def _normalize_side(raw: str | None) -> str:
    """Map many FMP variants to {'buy', 'sell', 'exchange'}."""
    if not raw:
        return "exchange"
    s = raw.strip().lower()
    if "purchase" in s or s in {"p", "buy", "acquired"}:
        return "buy"
    if "sale" in s or "sold" in s or s in {"s", "sell"}:
        return "sell"
    return "exchange"


def _dedup_key(source: str, parts: Iterable[Any]) -> str:
    """Stable 40-char hash of ``source`` + all ``parts``.

    None values are rendered as an empty string so two rows differing only in
    whether a nullable field is populated remain distinct.
    """
    payload = "|".join([source, *(("" if p is None else str(p)) for p in parts)])
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def normalize_senate_row(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Map one FMP senate/house row into DisclosedTrade kwargs.

    Returns ``None`` if the row is unusable (missing ticker or date).
    """
    ticker = raw.get("symbol") or raw.get("ticker")
    tx_date = _parse_iso_date(raw.get("transactionDate") or raw.get("transaction_date"))
    filing_date = _parse_iso_date(
        raw.get("disclosureDate") or raw.get("dateRecieved") or raw.get("filingDate")
    )
    if not ticker or not tx_date:
        return None
    # FMP /stable/*-latest uses firstName/lastName + "office" (which is actually
    # a verbose display string). Fall back to legacy representative/senator
    # fields for /api/v4/ paths.
    composed = " ".join(
        p for p in (raw.get("firstName", ""), raw.get("lastName", "")) if p
    ).strip()
    person = (
        composed
        or raw.get("representative")
        or raw.get("senator")
        or raw.get("office")
        or "UNKNOWN"
    )
    side = _normalize_side(raw.get("type") or raw.get("transactionType"))
    amt_low, amt_high = _parse_amount_range(raw.get("amount") or raw.get("range"))
    ticker_u = str(ticker).upper()
    # Congressional filings are uniquely identified by person + ticker + tx
    # date + reported amount range + side; a politician filing the same
    # ticker twice on the same day with the same range is vanishingly rare,
    # and if it happens the unique side (buy vs. sell) still distinguishes.
    key = _dedup_key(
        "senate_or_house",
        [person, ticker_u, tx_date, side, amt_low, amt_high, filing_date],
    )
    return {
        "person_name": person,
        "person_role": raw.get("district") or raw.get("office") or None,
        "ticker": ticker_u,
        "transaction_type": side,
        "transaction_date": tx_date,
        "filing_date": filing_date or tx_date,
        "amount_low": amt_low,
        "amount_high": amt_high,
        "amount_exact": None,
        "dedup_key": key,
        "raw_payload": raw,
    }


def normalize_insider_row(raw: dict[str, Any]) -> dict[str, Any] | None:
    ticker = raw.get("symbol") or raw.get("ticker")
    tx_date = _parse_iso_date(raw.get("transactionDate") or raw.get("filingDate"))
    filing_date = _parse_iso_date(raw.get("filingDate")) or tx_date
    if not ticker or not tx_date:
        return None
    # ``transactionType`` (e.g. "P-Purchase", "S-Sale", "A-Award", "F-InKind",
    # "M-Exempt") is more specific than the A/D letter. Consult it first so
    # P-Purchase → "buy" and non-informative codes (Award, InKind, Exempt,
    # Gift) fall through to "exchange" correctly.
    side = _normalize_side(
        raw.get("transactionType")
        or raw.get("acquistionOrDisposition")
        or raw.get("acquisitionOrDisposition")
    )
    qty = raw.get("securitiesTransacted") or raw.get("transactionQuantity")
    price = raw.get("price") or raw.get("transactionPrice")
    exact: float | None = None
    try:
        if qty and price:
            exact = float(qty) * float(price)
    except (TypeError, ValueError):
        exact = None
    ticker_u = str(ticker).upper()
    person_name = raw.get("reportingName") or raw.get("name") or "UNKNOWN"
    # A single Form 4 can have multiple line items with the same person,
    # ticker, and date — distinguish on the reporting CIK + a transaction
    # type code + qty/price, and fall back to the raw link + the full raw
    # record's hash to guarantee uniqueness even when all scalars collide.
    key = _dedup_key(
        "insider",
        [
            person_name,
            ticker_u,
            tx_date,
            filing_date,
            raw.get("reportingCik"),
            raw.get("transactionType"),
            raw.get("securitiesTransacted") or raw.get("transactionQuantity"),
            raw.get("price") or raw.get("transactionPrice"),
            raw.get("link") or raw.get("url") or "",
            raw.get("securityName") or "",
        ],
    )
    return {
        "person_name": person_name,
        "person_role": raw.get("typeOfOwner") or raw.get("title") or None,
        "ticker": ticker_u,
        "transaction_type": side,
        "transaction_date": tx_date,
        "filing_date": filing_date,
        "amount_low": exact,
        "amount_high": exact,
        "amount_exact": exact,
        "dedup_key": key,
        "raw_payload": raw,
    }


def since_window_days(days: int) -> date:
    """Return the ``date`` ``days`` calendar days ago (UTC)."""
    return date.today() - timedelta(days=days)


# Call tracking for the Phase 3 api_health breaker. Defined here (module level,
# below FMPClient) so FMPClient._get can reference it without closing the class
# body mid-definition.
def _log_api_call(path: str, status: str, *, latency_ms: float,
                  error_kind: str | None) -> None:
    """Best-effort FMP call logger. Imported lazily to dodge a circular import."""
    try:
        from jay_trading.data import store
        store.record_api_call(
            provider="fmp", endpoint=path, status=status,
            latency_ms=latency_ms, error_kind=error_kind,
        )
    except Exception as e:  # noqa: BLE001
        log.debug("api-call-log for fmp %s failed: %s", path, e)


# Convenience: iterate normalized rows from a source name.
def normalize(source: str, rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        if source in ("senate", "house"):
            norm = normalize_senate_row(r)
        elif source == "insider":
            norm = normalize_insider_row(r)
        else:
            raise ValueError(f"unknown source: {source}")
        if norm is None:
            continue
        norm["source"] = source
        out.append(norm)
    return out
