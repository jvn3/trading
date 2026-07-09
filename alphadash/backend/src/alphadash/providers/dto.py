"""Provider DTOs (S0.3 frozen contract).

Pydantic v2 models, ``Decimal`` for every number that touches money/quantities. Every DTO embeds
``Provenance`` — data without a source and an as-of timestamp does not enter the system.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class Provenance(BaseModel):
    """Where a datum came from and when it was true. ``is_stale`` is set by FreshnessPolicy."""

    model_config = ConfigDict(frozen=False)

    source: str
    as_of: datetime  # UTC
    is_stale: bool = False


class Quote(BaseModel):
    symbol: str
    price: Decimal
    bid: Decimal | None = None
    ask: Decimal | None = None
    provenance: Provenance


class Bar(BaseModel):
    symbol: str
    timeframe: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    ts: datetime
    provenance: Provenance


class NewsItem(BaseModel):
    id: str
    symbols: list[str]
    headline: str
    summary: str | None = None
    url: str | None = None
    published_at: datetime
    source: str
    sentiment: float | None = None


class FundamentalSnapshot(BaseModel):
    symbol: str
    as_of: datetime
    metrics: dict[str, Decimal]
    provenance: Provenance


class MacroPoint(BaseModel):
    series_id: str
    ts: datetime
    value: Decimal
    provenance: Provenance
