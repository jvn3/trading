"""Minimal SEC EDGAR client for Form 4 footnote parsing.

Used by the insider_follow strategy to detect 10b5-1 scheduled trades
that FMP does not flag. Only read operations; no auth required. SEC
requires a real contact address in the ``User-Agent`` header (see
https://www.sec.gov/os/accessing-edgar-data) and throttles at 10 req/sec
per source IP.

The SEC does not serve a public API for Form 4 data specifically — each
filing has a URL of the form:

    https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{file}.xml

FMP's ``insider-trading/latest`` feed already includes that URL (with
``-index.htm`` suffix). We convert it to the corresponding XML and
search for ``10b5-1`` in any footnote text.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

log = logging.getLogger(__name__)

#: SEC mandates a real contact string; this is the one baked in for Jay's
#: project. If you fork, change it before running against EDGAR.
USER_AGENT = "jay-trading-research jaynayee7@outlook.com"

#: Throttle below the SEC's 10/sec cap. 5/sec gives headroom on top of any
#: already-in-flight calls from other code paths.
_RATE_PER_SEC = 5.0

_10B5_1_PATTERN = re.compile(r"10b5-?1", re.IGNORECASE)


@dataclass(frozen=True)
class Form4Check:
    url: str
    fetched: bool
    has_10b5_1: bool | None  # None if fetch failed
    detail: str = ""


class _MinimalRateLimiter:
    """Simple monotonic-clock throttle shared across calls."""

    def __init__(self, rate_per_sec: float) -> None:
        self._min_interval = 1.0 / rate_per_sec
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            sleep_for = self._min_interval - (now - self._last)
            if sleep_for > 0:
                time.sleep(sleep_for)
            self._last = time.monotonic()


_limiter = _MinimalRateLimiter(_RATE_PER_SEC)


def _fetch(url: str, *, timeout: float = 15.0) -> httpx.Response:
    _limiter.wait()
    return httpx.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"},
        timeout=timeout,
        follow_redirects=True,
    )


def _index_url_to_xml(index_url: str) -> str | None:
    """Turn an EDGAR ``...-index.htm`` URL into the Form 4 primary XML URL.

    Strategy: fetch the index page, pick out the first ``.xml`` link. EDGAR
    index pages list all documents in the filing; for Form 4s, exactly one
    is the primary XML we want.
    """
    try:
        r = _fetch(index_url)
    except Exception as e:  # noqa: BLE001
        log.warning("edgar index fetch failed (%s): %s", index_url, e)
        return None
    if r.status_code != 200:
        log.warning("edgar index %s returned HTTP %d", index_url, r.status_code)
        return None
    matches = re.findall(r'href="([^"]+\.xml)"', r.text, flags=re.IGNORECASE)
    if not matches:
        return None
    # The primary Form 4 XML uses a predictable naming: <accession>.xml or
    # wk-form4_*.xml. Prefer one whose path starts with "/Archives/" if
    # multiple; these are full paths.
    best = None
    for m in matches:
        if m.endswith(".xsd"):
            continue
        # Resolve relative URLs against the index URL.
        if m.startswith("http"):
            full = m
        elif m.startswith("/"):
            full = "https://www.sec.gov" + m
        else:
            full = index_url.rsplit("/", 1)[0] + "/" + m
        if best is None:
            best = full
        # Prefer names containing "form4" or the primary-document pattern.
        if "form4" in m.lower():
            return full
    return best


def check_10b5_1(index_url: str) -> Form4Check:
    """Return whether any footnote in this Form 4 mentions ``10b5-1``.

    Best-effort: if EDGAR or the parser fails we return ``fetched=False``
    and the caller should fail-open (include the insider in the cluster).
    """
    if not index_url:
        return Form4Check(url="", fetched=False, has_10b5_1=None, detail="empty url")

    xml_url = _index_url_to_xml(index_url)
    if xml_url is None:
        return Form4Check(
            url=index_url, fetched=False, has_10b5_1=None,
            detail="could not resolve xml from index",
        )

    try:
        r = _fetch(xml_url)
    except Exception as e:  # noqa: BLE001
        return Form4Check(
            url=xml_url, fetched=False, has_10b5_1=None,
            detail=f"xml fetch failed: {type(e).__name__}: {e}",
        )
    if r.status_code != 200:
        return Form4Check(
            url=xml_url, fetched=False, has_10b5_1=None,
            detail=f"xml returned HTTP {r.status_code}",
        )

    # The XML has <footnoteText> blocks as well as, in some 2024+ filings, a
    # top-level <rule10b5-1Info> element. Grep both.
    body = r.text
    has_flag = bool(_10B5_1_PATTERN.search(body))
    return Form4Check(
        url=xml_url, fetched=True, has_10b5_1=has_flag,
        detail="ok",
    )
