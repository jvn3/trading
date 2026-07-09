"""Tiny in-process TTL cache for provider responses (S1.1).

Clock is injected (defaults to ``time.monotonic``) so tests never sleep. This is deliberately
process-local — a shared cache (Redis etc.) is a scaling concern, not a Phase 1 one.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

_MISS = object()


class TTLCache:
    def __init__(self, ttl_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._data: dict[Any, tuple[float, Any]] = {}

    def get_or_load(self, key: Any, loader: Callable[[], Any]) -> Any:
        with self._lock:
            hit = self._data.get(key, _MISS)
            if hit is not _MISS:
                expires_at, value = hit
                if self._clock() < expires_at:
                    return value
                del self._data[key]
        value = loader()
        with self._lock:
            self._data[key] = (self._clock() + self._ttl, value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
