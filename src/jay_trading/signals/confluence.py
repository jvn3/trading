"""Cross-strategy signal confluence.

Per ``lessons/strategy_evaluation.md §6.1``: when a ticker has a strong
signal from BOTH ``smart_copy`` and ``insider_follow`` within a 30-day
rolling window, size the new position at 7.5% of equity instead of the
5% base. The risk layer's 10% hard cap still applies.

Kept as a stand-alone helper (not wired into sizing.py) because it is
strategy-aware: the multiplier depends on *which* strategy is asking.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from jay_trading.data import models
from jay_trading.data.db import session_scope

log = logging.getLogger(__name__)

CONFLUENCE_LOOKBACK_DAYS = 30
CONFLUENCE_MIN_SCORE = 0.5

#: Strategy pairs we treat as confluent. Extend as new strategies ship.
_CONFLUENT_PAIRS: dict[str, list[str]] = {
    "smart_copy": ["insider_follow"],
    "insider_follow": ["smart_copy"],
}

CONFLUENCE_MULTIPLIER = 1.5  # 5% × 1.5 = 7.5%


def multiplier_for_ticker(ticker: str, *, my_strategy: str) -> float:
    """Return the notional multiplier for ``ticker`` from ``my_strategy``'s POV.

    ``1.5`` if any *partner* strategy has a signal above ``CONFLUENCE_MIN_SCORE``
    on this ticker within the last ``CONFLUENCE_LOOKBACK_DAYS``, else ``1.0``.
    """
    partners = _CONFLUENT_PAIRS.get(my_strategy)
    if not partners:
        return 1.0

    since = datetime.now(timezone.utc) - timedelta(days=CONFLUENCE_LOOKBACK_DAYS)
    with session_scope() as s:
        stmt = (
            select(models.Signal.id)
            .where(models.Signal.ticker == ticker.upper())
            .where(models.Signal.strategy_name.in_(partners))
            .where(models.Signal.score >= CONFLUENCE_MIN_SCORE)
            .where(models.Signal.generated_at >= since)
            .limit(1)
        )
        hit = s.scalar(stmt)
    return CONFLUENCE_MULTIPLIER if hit is not None else 1.0
