"""Rolling-window API health tracking.

Reads `api_call_log` rows via :mod:`jay_trading.data.store` to compute the
fraction of failed calls to a given provider over a recent window. Used
by the ``api_health`` pipeline gate in :mod:`jay_trading.risk.guards`.

Also provides a minimal TTL cache for the market-regime gate's SPY quote
call so we don't hit FMP on every ``execute_strategies`` run.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from jay_trading.data import store

DEFAULT_WINDOW_MINUTES = 30
DEFAULT_MIN_CALLS = 10
DEFAULT_FAIL_THRESHOLD = 0.30


@dataclass(frozen=True)
class HealthSummary:
    provider: str
    window_minutes: int
    fails: int
    total: int

    @property
    def fail_rate(self) -> float:
        return self.fails / self.total if self.total else 0.0

    @property
    def enough_data(self) -> bool:
        return self.total >= DEFAULT_MIN_CALLS


def summary(provider: str, window_minutes: int = DEFAULT_WINDOW_MINUTES) -> HealthSummary:
    fails, total = store.api_error_rate(provider, window_minutes=window_minutes)
    return HealthSummary(
        provider=provider, window_minutes=window_minutes, fails=fails, total=total,
    )


# -- TTL cache ---------------------------------------------------------------


class TTLCache:
    """Tiny in-process TTL cache. Not thread-safe across processes, which is
    fine — the scheduler is single-process, and a miss on scheduler restart
    just re-fetches.
    """

    def __init__(self, default_ttl_sec: float = 300.0) -> None:
        self._default_ttl = default_ttl_sec
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        item = self._store.get(key)
        if item is None:
            return None
        expires_at, value = item
        if time.monotonic() >= expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl_sec: float | None = None) -> None:
        ttl = ttl_sec if ttl_sec is not None else self._default_ttl
        self._store[key] = (time.monotonic() + ttl, value)

    def clear(self) -> None:
        self._store.clear()


#: Shared TTL cache instance. Module-level so the scheduler's single
#: long-lived process can benefit across job ticks.
_cache = TTLCache()


def cache() -> TTLCache:
    return _cache
