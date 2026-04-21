"""FRED (St. Louis Fed) CSV client.

Unauthenticated CSV fetcher for the two macro series Strategy V needs:

- ``T10Y2Y`` — 10-Year Treasury Constant Maturity minus 2-Year Treasury
  Constant Maturity (daily, in percentage points). Negative = inverted curve.
- ``VIXCLS`` — CBOE Volatility Index, daily close.

FRED returns a CSV at ``https://fred.stlouisfed.org/graph/fredgraph.csv?id=X``.

**Why this client shells out to curl instead of using httpx**: as of 2026-04-21
the FRED web endpoint sits behind Akamai bot protection that resets the TLS
stream when the request comes from any Python HTTP stack (httpx HTTP/1.1
times out; httpx HTTP/2 receives StreamReset; ``urllib`` times out). System
``curl`` (HTTP/2, distinct TLS fingerprint) is unaffected. We use a fetcher
abstraction so tests can inject a fake without spawning processes.

Missing observations in FRED's CSV are written as ``.`` — we preserve them as
``Observation(value=None)`` so downstream callers can decide.
"""
from __future__ import annotations

import csv
import io
import logging
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Iterable

log = logging.getLogger(__name__)

BASE_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
DEFAULT_TIMEOUT_SEC = 30


class FREDError(RuntimeError):
    """Raised when a FRED CSV fetch fails or is unparseable."""


@dataclass(frozen=True)
class Observation:
    """One dated observation from a FRED series. ``value`` is ``None`` for gaps."""

    date: date
    value: float | None


# -- Pluggable fetcher -----------------------------------------------------

#: A fetcher receives a series id and returns the raw CSV body. Tests inject
#: a stub here; production uses :func:`_curl_fetcher`.
Fetcher = Callable[[str], str]


def _curl_fetcher(timeout_sec: int = DEFAULT_TIMEOUT_SEC) -> Fetcher:
    """Build a fetcher that shells out to system ``curl``.

    Raises ``FREDError`` at build time if curl isn't on PATH so callers fail
    fast instead of mid-job.
    """
    curl = shutil.which("curl")
    if not curl:
        raise FREDError("curl not on PATH — required for FRED fetches")

    def fetch(series_id: str) -> str:
        url = f"{BASE_URL}?id={series_id}"
        try:
            proc = subprocess.run(
                [curl, "-sS", "--fail-with-body", "--max-time", str(timeout_sec), url],
                capture_output=True,
                check=False,
                text=True,
            )
        except OSError as e:
            raise FREDError(f"FRED {series_id}: curl invocation failed: {e}") from e
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[:200]
            raise FREDError(
                f"FRED {series_id}: curl exit {proc.returncode}: {err!r}"
            )
        return proc.stdout

    return fetch


class FREDClient:
    """Fetch and parse FRED CSV series.

    The ``fetcher`` parameter exists for tests; in production leave it
    unset and we shell out to ``curl``. ``close()`` is a no-op kept for API
    parity with FMPClient but harmless to call.
    """

    def __init__(
        self,
        *,
        fetcher: Fetcher | None = None,
        timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    ) -> None:
        self._fetch: Fetcher = fetcher or _curl_fetcher(timeout_sec=timeout_sec)

    def __enter__(self) -> "FREDClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        # Subprocess-based fetcher has no resources to release. The hook
        # exists so callers can use ``with FREDClient() as f:`` symmetrically
        # with ``FMPClient``.
        return

    # ---- Generic series fetch --------------------------------------------

    def get_series(self, series_id: str) -> list[Observation]:
        """Return the full history of ``series_id`` as ``Observation`` rows.

        Missing values in FRED's CSV (written as ``.``) are preserved as
        ``Observation(date, value=None)`` so downstream code can decide how to
        handle gaps. Rows with malformed dates are dropped with a debug log.
        """
        body = self._fetch(series_id)
        return _parse_csv(series_id, body)

    def latest(self, series_id: str) -> Observation | None:
        """Return the most recent non-``None`` observation, or ``None`` if empty."""
        rows = self.get_series(series_id)
        for obs in reversed(rows):
            if obs.value is not None:
                return obs
        return None


# ---- CSV parsing (pure, easily testable) --------------------------------


def _parse_csv(series_id: str, text: str) -> list[Observation]:
    """Parse a FRED CSV body. Column 1 = ``DATE``, column 2 = series value."""
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        raise FREDError(f"FRED {series_id}: empty CSV body")

    header = [c.strip().upper() for c in rows[0]]
    # FRED's CSV header has shifted between "DATE" and "observation_date"; accept
    # both. The only invariant is that column 0 contains the word "DATE".
    if len(header) < 2 or "DATE" not in header[0]:
        raise FREDError(
            f"FRED {series_id}: unexpected header {header!r} "
            f"(want a date-ish column 0)"
        )

    out: list[Observation] = []
    for raw in rows[1:]:
        if not raw:
            continue
        try:
            d = datetime.strptime(raw[0], "%Y-%m-%d").date()
        except ValueError:
            log.debug("FRED %s: bad date %r, skipping", series_id, raw[0])
            continue
        cell = raw[1].strip() if len(raw) > 1 else "."
        value: float | None
        if cell == "." or cell == "":
            value = None
        else:
            try:
                value = float(cell)
            except ValueError:
                log.debug("FRED %s: bad value %r on %s, skipping", series_id, cell, d)
                continue
        out.append(Observation(date=d, value=value))
    return out


# ---- Convenience helpers for Strategy V ---------------------------------


def series_values(obs: Iterable[Observation]) -> list[float]:
    """Return just the non-``None`` values, in order. Handy for moving averages."""
    return [o.value for o in obs if o.value is not None]


def moving_average(values: list[float], window: int) -> float | None:
    """Trailing-window mean of ``values``. ``None`` if fewer than ``window`` points."""
    if len(values) < window or window <= 0:
        return None
    tail = values[-window:]
    return sum(tail) / window
