"""Detect clusters of politician trades converging on the same ticker.

A cluster is:
- 2+ distinct politicians
- filing same-direction trades (both buys or both sells)
- on the same ticker
- within a 14-day filing-date window

Score:
    base         = min(n_distinct_members, 5) / 5
    quality_mult = 1.2 if mean(politician quality scores) > 0 else 0.8
    committee_mult = 1.2 if any member on a relevant committee else 1.0
    score        = clip(base * quality_mult * committee_mult, 0, 1)

Emits :class:`jay_trading.data.models.Signal` rows only for clusters we
haven't seen yet (keyed by ticker + direction + earliest-in-cluster filing
date). Idempotent.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from jay_trading.data import models
from jay_trading.data.db import session_scope
from jay_trading.signals.politician_scorer import (
    PoliticianScore,
    committee_is_relevant,
    score_all,
)

log = logging.getLogger(__name__)

CLUSTER_WINDOW_DAYS = 14
MIN_MEMBERS = 2
STRATEGY_NAME = "smart_copy"


@dataclass
class Cluster:
    ticker: str
    direction: str  # "long" | "short"
    window_start: date
    window_end: date
    members: list[dict[str, Any]]  # dicts ready for Signal.rationale
    score: float

    @property
    def key(self) -> str:
        return f"{self.ticker}|{self.direction}|{self.window_start.isoformat()}"


def _recent_congressional_trades(lookback_days: int) -> list[models.DisclosedTrade]:
    since = date.today() - timedelta(days=lookback_days)
    with session_scope() as s:
        stmt = (
            select(models.DisclosedTrade)
            .where(models.DisclosedTrade.source.in_(("senate", "house")))
            .where(models.DisclosedTrade.filing_date >= since)
            .order_by(models.DisclosedTrade.filing_date.asc())
        )
        rows = list(s.scalars(stmt))
        for r in rows:
            s.expunge(r)
        return rows


def _side_to_direction(side: str) -> str | None:
    if side == "buy":
        return "long"
    if side == "sell":
        return "short"
    return None  # "exchange" → ignored


def find_clusters(
    lookback_days: int = CLUSTER_WINDOW_DAYS * 3,
    window_days: int = CLUSTER_WINDOW_DAYS,
    min_members: int = MIN_MEMBERS,
    scores: dict[str, PoliticianScore] | None = None,
) -> list[Cluster]:
    """Return the current set of active clusters."""
    trades = _recent_congressional_trades(lookback_days)
    # Bucket by (ticker, direction) → list of trades sorted by filing_date.
    buckets: dict[tuple[str, str], list[models.DisclosedTrade]] = defaultdict(list)
    for t in trades:
        direction = _side_to_direction(t.transaction_type)
        if direction is None:
            continue
        buckets[(t.ticker, direction)].append(t)

    if scores is None:
        # Only score politicians we'll actually need, for speed.
        needed = {t.person_name for bucket in buckets.values() for t in bucket}
        scores = score_all(needed)

    clusters: list[Cluster] = []
    for (ticker, direction), bucket in buckets.items():
        bucket.sort(key=lambda t: t.filing_date)
        # Slide a window over the bucket; record a cluster whenever the
        # window has ≥ min_members distinct politicians.
        n = len(bucket)
        left = 0
        for right in range(n):
            while (bucket[right].filing_date - bucket[left].filing_date).days > window_days:
                left += 1
            window = bucket[left : right + 1]
            members_by_name: dict[str, list[models.DisclosedTrade]] = defaultdict(list)
            for tr in window:
                members_by_name[tr.person_name].append(tr)
            if len(members_by_name) < min_members:
                continue
            # Collapse so the recorded window is the smallest enclosing one
            # with all current members.
            earliest = min(tr.filing_date for tr in window)
            latest = max(tr.filing_date for tr in window)
            members_payload: list[dict[str, Any]] = []
            for name, trs in members_by_name.items():
                ps = scores.get(name)
                first = trs[0]
                members_payload.append(
                    {
                        "name": name,
                        "role": first.person_role,
                        "tx_date": first.transaction_date.isoformat(),
                        "filing_date": first.filing_date.isoformat(),
                        "amount_range": (
                            None if first.amount_low is None
                            else f"${first.amount_low:,.0f}-${first.amount_high:,.0f}"
                        ),
                        "quality_score": round(ps.trailing_6mo_return, 4) if ps else 0.0,
                        "n_past_trades_scored": ps.n_trades if ps else 0,
                    }
                )

            n_members = len(members_by_name)
            base = min(n_members, 5) / 5.0
            quality_vals = [m["quality_score"] for m in members_payload]
            quality_mult = 1.2 if (sum(quality_vals) / max(1, len(quality_vals)) > 0) else 0.8
            committee_mult = (
                1.2
                if any(committee_is_relevant(m.get("role"), ticker) for m in members_payload)
                else 1.0
            )
            score = max(0.0, min(1.0, base * quality_mult * committee_mult))

            cluster = Cluster(
                ticker=ticker,
                direction=direction,
                window_start=earliest,
                window_end=latest,
                members=members_payload,
                score=score,
            )
            clusters.append(cluster)

    # Dedup: keep the strongest cluster per (ticker, direction, window_start).
    dedup: dict[str, Cluster] = {}
    for c in clusters:
        existing = dedup.get(c.key)
        if existing is None or c.score > existing.score:
            dedup[c.key] = c
    return list(dedup.values())


def cluster_to_signal_kwargs(cluster: Cluster) -> dict[str, Any]:
    """Materialize a Cluster as kwargs for a Signal row."""
    return {
        "strategy_name": STRATEGY_NAME,
        "ticker": cluster.ticker,
        "direction": cluster.direction,
        "score": cluster.score,
        "rationale": {
            "strategy": STRATEGY_NAME,
            "cluster": {
                "ticker": cluster.ticker,
                "direction": cluster.direction,
                "window_start": cluster.window_start.isoformat(),
                "window_end": cluster.window_end.isoformat(),
                "members": cluster.members,
                "score_components": {
                    "base": round(min(len(cluster.members), 5) / 5.0, 4),
                    "n_members": len(cluster.members),
                },
            },
            "computed_score": cluster.score,
        },
    }


def _existing_keys() -> set[str]:
    """Return the dedup keys of clusters already written as Signals."""
    with session_scope() as s:
        rows = s.execute(
            select(models.Signal.ticker, models.Signal.direction, models.Signal.rationale)
            .where(models.Signal.strategy_name == STRATEGY_NAME)
        ).all()
    keys: set[str] = set()
    for ticker, direction, rationale in rows:
        try:
            ws = rationale["cluster"]["window_start"]
        except (KeyError, TypeError):
            continue
        keys.add(f"{ticker}|{direction}|{ws}")
    return keys


def upsert_signals(clusters: list[Cluster]) -> int:
    """Persist new cluster signals. Returns the count of inserted rows."""
    existing = _existing_keys()
    inserted = 0
    with session_scope() as s:
        for c in clusters:
            if c.key in existing:
                continue
            kwargs = cluster_to_signal_kwargs(c)
            sig = models.Signal(**kwargs)
            s.add(sig)
            inserted += 1
    return inserted
