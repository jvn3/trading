"""Ingestion + normalization (S1.2).

Pulls quotes/news/fundamentals/macro through the S0.3 providers and persists ONE point-in-time
``data_snapshots`` row per call. Every datum keeps its provenance (source + as_of + is_stale) —
this row is exactly what an agent run may see (no-lookahead guarantee hangs off it, S2.x).

A single failing feed degrades the snapshot (recorded under ``errors``) instead of killing it:
missing/stale data lowers confidence downstream; silence would hide the gap.
Decimals are serialized as strings (JSON payload — never floats).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from alphadash.db.models import DataSnapshot
from alphadash.providers.factory import ProviderBundle

log = logging.getLogger(__name__)


def _json(dto: BaseModel) -> dict[str, Any]:
    return dto.model_dump(mode="json")


def snapshot_market_context(
    session: Session,
    bundle: ProviderBundle,
    symbols: list[str],
    *,
    news_since: datetime,
    macro_series: list[str],
    now: datetime,
    agent_run_id: str | None = None,
) -> DataSnapshot:
    """Fetch, normalize, and persist a cited market-context snapshot. Caller commits."""
    payload: dict[str, Any] = {
        "as_of": now.isoformat(),
        "symbols": [s.upper() for s in symbols],
        "quotes": [],
        "news": [],
        "fundamentals": [],
        "macro": {},
        "errors": [],
    }

    for symbol in symbols:
        try:
            payload["quotes"].append(_json(bundle.market_data.get_quote(symbol)))
        except Exception as e:
            log.warning("quote ingestion failed for %s: %s", symbol, e)
            payload["errors"].append({"feed": "quote", "symbol": symbol, "error": str(e)})
        try:
            payload["fundamentals"].append(_json(bundle.fundamentals.get_fundamentals(symbol)))
        except Exception as e:
            log.warning("fundamentals ingestion failed for %s: %s", symbol, e)
            payload["errors"].append({"feed": "fundamentals", "symbol": symbol, "error": str(e)})

    try:
        payload["news"] = [_json(n) for n in bundle.news.get_news(symbols, since=news_since)]
    except Exception as e:
        log.warning("news ingestion failed: %s", e)
        payload["errors"].append({"feed": "news", "symbol": None, "error": str(e)})

    for series_id in macro_series:
        try:
            points = bundle.macro.get_series(series_id, since=news_since)
            payload["macro"][series_id] = [_json(p) for p in points]
        except Exception as e:
            log.warning("macro ingestion failed for %s: %s", series_id, e)
            payload["errors"].append({"feed": "macro", "symbol": series_id, "error": str(e)})

    snapshot = DataSnapshot(agent_run_id=agent_run_id, payload=payload)
    session.add(snapshot)
    session.flush()
    return snapshot
