"""Detect clusters of politician trades converging on the same ticker.

A cluster is:
- 2+ distinct politicians
- filing same-direction trades (both buys or both sells)
- on the same ticker
- within a 14-day filing-date window

Score (post 2026-04-22 "knobs" change):
    base                     = min(n_distinct_members, 5) / 5
    quality_mult             = 1.2 if mean(politician quality scores) > 0 else 0.8
    committee_mult           = 1.2 if any member on a relevant committee else 1.0
    conviction_mult          = 1.2 if any member's trailing 6mo return > 5% else 1.0
    insider_confluence_mult  = 1.15 if same ticker has >= 2 distinct insider
                               BUYS in the last 30 days else 1.0
    score = clip(base * quality_mult * committee_mult *
                 conviction_mult * insider_confluence_mult, 0, 1)

The new ``conviction_mult`` substitutes for the dead committee data: in
practice ``person_role`` from FMP carries state/district codes ("AR",
"TX10"), never committee names, so ``committee_mult`` is almost always 1.0.
``conviction_mult`` rewards clusters that contain a politician with a
demonstrable trailing track record.

The new ``insider_confluence_mult`` is a lightweight cross-strategy bonus:
when the cluster's ticker also shows real insider buy activity (not the
much-more-common option grants/exercises), the signal earns a 15% kicker.

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

from jay_trading.data import models, store
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

# Knob 2 (2026-04-22): a politician with trailing 6mo return above this
# threshold counts as "high conviction" and triggers the +20% conviction
# multiplier on any cluster they're a member of.
HIGH_CONVICTION_RETURN = 0.05
CONVICTION_MULT = 1.2

# Knob 3 (2026-04-22): if the ticker has at least this many distinct
# insider BUYS in the last 30 days, the cluster gets a +15% kicker.
INSIDER_CONFLUENCE_MIN_BUYERS = 2
INSIDER_CONFLUENCE_LOOKBACK_DAYS = 30
INSIDER_CONFLUENCE_MULT = 1.15


@dataclass
class Cluster:
    ticker: str
    direction: str  # "long" | "short"
    window_start: date
    window_end: date
    members: list[dict[str, Any]]  # dicts ready for Signal.rationale
    score: float
    score_components: dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.score_components is None:
            self.score_components = {}

    @property
    def key(self) -> str:
        return f"{self.ticker}|{self.direction}|{self.window_start.isoformat()}"


def _insider_buys_cache(ticker: str, cache: dict[str, int]) -> int:
    """Look up cached insider-buy count for ``ticker``, populating from store
    on miss. Used by ``find_clusters`` to keep DB hits at one per ticker."""
    hit = cache.get(ticker)
    if hit is not None:
        return hit
    n = store.count_distinct_insider_buys(
        ticker, days=INSIDER_CONFLUENCE_LOOKBACK_DAYS
    )
    cache[ticker] = n
    return n


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

    # Per-call cache so the insider_confluence multiplier hits the DB at
    # most once per ticker, not per sliding-window candidate.
    insider_buys_cache: dict[str, int] = {}

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
            # Knob 2: high-conviction member bonus.
            conviction_mult = (
                CONVICTION_MULT
                if any(m["quality_score"] > HIGH_CONVICTION_RETURN for m in members_payload)
                else 1.0
            )
            # Knob 3: insider co-buying bonus. Cached per ticker via the
            # closure-local ``insider_buys_cache`` so we hit the DB once
            # per ticker, not once per sliding-window cluster candidate.
            n_insider_buyers = _insider_buys_cache(ticker, insider_buys_cache)
            insider_confluence_mult = (
                INSIDER_CONFLUENCE_MULT
                if n_insider_buyers >= INSIDER_CONFLUENCE_MIN_BUYERS
                else 1.0
            )

            score = max(
                0.0,
                min(
                    1.0,
                    base
                    * quality_mult
                    * committee_mult
                    * conviction_mult
                    * insider_confluence_mult,
                ),
            )

            cluster = Cluster(
                ticker=ticker,
                direction=direction,
                window_start=earliest,
                window_end=latest,
                members=members_payload,
                score=score,
                score_components={
                    "base": round(base, 4),
                    "n_members": n_members,
                    "quality_mult": quality_mult,
                    "committee_mult": committee_mult,
                    "conviction_mult": conviction_mult,
                    "insider_confluence_mult": insider_confluence_mult,
                    "n_insider_buyers": n_insider_buyers,
                },
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
                "score_components": cluster.score_components or {
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
