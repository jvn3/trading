"""Detect clusters of Form 4 insider purchases on the same ticker.

Parallels :mod:`jay_trading.signals.cluster_detector` but with:
- wider window (30 days, vs. 14 for congress)
- role-weighted member count (CEO 3x > CFO 2.5x > director 1x)
- Piotroski-F-score quality multiplier
- a post-cluster EDGAR footnote check to filter 10b5-1 scheduled trades

Cluster definition per ``strategies/phase2_build_spec.md §3``:
    - ≥ 3 distinct insiders
    - ``P-Purchase`` only (we rely on ingest already mapping this to
      ``transaction_type == "buy"``; other codes land as ``"exchange"``)
    - same ticker
    - 30-day filing window

Score per spec §1.5:
    weighted_count = sum(role_weight)
    base           = min(weighted_count, 10) / 10
    piotroski_mult = piotroski_multiplier(score)
    recency_mult   = 1.1 if newest filing <= 5 days else 1.0
    score          = clip(base * piotroski_mult * recency_mult, 0, 1)

Score threshold 0.4 (applied by ``InsiderFollowStrategy``, not here —
this module returns all qualifying clusters and lets the strategy decide).
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
from jay_trading.data.edgar import check_10b5_1
from jay_trading.data.fmp import FMPClient
from jay_trading.signals import insider_scorer

log = logging.getLogger(__name__)

CLUSTER_WINDOW_DAYS = 30
MIN_DISTINCT_INSIDERS = 3
STRATEGY_NAME = "insider_follow"


@dataclass
class InsiderCluster:
    ticker: str
    direction: str  # always "long" — we only follow P-Purchases
    window_start: date
    window_end: date
    members: list[dict[str, Any]]
    weighted_count: float
    piotroski: int | None
    score: float
    all_10b5_1: bool  # True if every checked member was flagged 10b5-1

    @property
    def key(self) -> str:
        return f"{self.ticker}|{self.direction}|{self.window_start.isoformat()}"


def _recent_insider_purchases(lookback_days: int) -> list[models.DisclosedTrade]:
    """Fetch insider ``P-Purchase`` rows from the last ``lookback_days``.

    Checks both the normalized ``transaction_type`` column AND the raw
    FMP code in ``raw_payload.transactionType``. The latter handles rows
    that were ingested before the 2026-04 normalizer fix, which had every
    insider row landing as ``transaction_type='exchange'`` because the
    letter-coded ``acquisitionOrDisposition`` field took precedence over
    the more specific ``transactionType`` string.
    """
    since = date.today() - timedelta(days=lookback_days)
    with session_scope() as s:
        stmt = (
            select(models.DisclosedTrade)
            .where(models.DisclosedTrade.source == "insider")
            .where(models.DisclosedTrade.filing_date >= since)
            .order_by(models.DisclosedTrade.filing_date.asc())
        )
        rows = list(s.scalars(stmt))
        for r in rows:
            s.expunge(r)
    # Post-filter in Python so we support SQLite without needing a
    # JSON-operator predicate (SQLite's JSON1 is optional on some builds).
    out: list[models.DisclosedTrade] = []
    for r in rows:
        if r.transaction_type == "buy":
            out.append(r)
            continue
        raw_code = (r.raw_payload or {}).get("transactionType", "")
        if isinstance(raw_code, str) and raw_code.startswith("P-"):
            out.append(r)
    return out


def find_insider_clusters(
    lookback_days: int = CLUSTER_WINDOW_DAYS * 2,
    window_days: int = CLUSTER_WINDOW_DAYS,
    min_distinct_insiders: int = MIN_DISTINCT_INSIDERS,
    check_edgar: bool = True,
    fmp: FMPClient | None = None,
) -> list[InsiderCluster]:
    """Return the current set of active insider-purchase clusters."""
    trades = _recent_insider_purchases(lookback_days)
    buckets: dict[str, list[models.DisclosedTrade]] = defaultdict(list)
    for t in trades:
        buckets[t.ticker].append(t)

    own_client = fmp is None
    fmp = fmp or FMPClient()
    clusters: list[InsiderCluster] = []
    try:
        for ticker, bucket in buckets.items():
            bucket.sort(key=lambda t: t.filing_date)
            n = len(bucket)
            left = 0
            candidates: list[InsiderCluster] = []
            for right in range(n):
                while (bucket[right].filing_date - bucket[left].filing_date).days > window_days:
                    left += 1
                window = bucket[left : right + 1]
                members_by_name: dict[str, list[models.DisclosedTrade]] = defaultdict(list)
                for tr in window:
                    members_by_name[tr.person_name].append(tr)
                if len(members_by_name) < min_distinct_insiders:
                    continue

                members_payload, weighted_count, has_any_non_10b5_1 = _build_members(
                    members_by_name, check_edgar=check_edgar,
                )
                all_10b5_1 = (not has_any_non_10b5_1) and any(
                    m.get("ten_b5_1") is True for m in members_payload
                )

                piotroski = insider_scorer.fetch_piotroski(ticker, fmp=fmp)

                earliest = min(tr.filing_date for tr in window)
                latest = max(tr.filing_date for tr in window)
                days_since_newest = (date.today() - latest).days

                base = min(weighted_count, 10.0) / 10.0
                p_mult = insider_scorer.piotroski_multiplier(piotroski)
                r_mult = insider_scorer.recency_multiplier(days_since_newest)
                score = max(0.0, min(1.0, base * p_mult * r_mult))

                candidates.append(InsiderCluster(
                    ticker=ticker,
                    direction="long",
                    window_start=earliest,
                    window_end=latest,
                    members=members_payload,
                    weighted_count=weighted_count,
                    piotroski=piotroski,
                    score=score,
                    all_10b5_1=all_10b5_1,
                ))

            # Keep the strongest cluster per window_start for this ticker.
            dedup: dict[str, InsiderCluster] = {}
            for c in candidates:
                prev = dedup.get(c.key)
                if prev is None or c.score > prev.score:
                    dedup[c.key] = c
            clusters.extend(dedup.values())
    finally:
        if own_client:
            fmp.close()

    return clusters


def _build_members(
    members_by_name: dict[str, list[models.DisclosedTrade]],
    *,
    check_edgar: bool,
) -> tuple[list[dict[str, Any]], float, bool]:
    """Build the per-member payload + weighted count + any-non-10b5-1 flag."""
    out: list[dict[str, Any]] = []
    weighted_sum = 0.0
    any_non_10b5_1 = False

    for name, trs in members_by_name.items():
        first = trs[0]
        rw = insider_scorer.role_weight(first.person_role)
        ten_b5_1: bool | None = None
        edgar_detail = "not checked"
        if check_edgar:
            url = (first.raw_payload or {}).get("url") or ""
            if url:
                res = check_10b5_1(url)
                ten_b5_1 = res.has_10b5_1 if res.fetched else None
                edgar_detail = res.detail
        # Fail-open: if we couldn't confirm 10b5-1, treat as "not flagged".
        flagged = ten_b5_1 is True
        if not flagged:
            weighted_sum += rw.weight
            any_non_10b5_1 = True

        out.append({
            "name": name,
            "role_label": rw.label,
            "role_weight": rw.weight,
            "type_of_owner": first.person_role,
            "tx_date": first.transaction_date.isoformat(),
            "filing_date": first.filing_date.isoformat(),
            "shares": (first.raw_payload or {}).get("securitiesTransacted"),
            "price": (first.raw_payload or {}).get("price"),
            "transaction_type_raw": (first.raw_payload or {}).get("transactionType"),
            "edgar_url": (first.raw_payload or {}).get("url"),
            "ten_b5_1": ten_b5_1,
            "edgar_detail": edgar_detail,
        })

    return out, weighted_sum, any_non_10b5_1


def cluster_to_signal_kwargs(cluster: InsiderCluster) -> dict[str, Any]:
    """Materialize an :class:`InsiderCluster` as ``Signal`` kwargs."""
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
                "weighted_count": cluster.weighted_count,
                "piotroski": cluster.piotroski,
                "members": cluster.members,
                "all_10b5_1": cluster.all_10b5_1,
            },
            "computed_score": cluster.score,
        },
    }


def _existing_keys() -> set[str]:
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


def upsert_insider_signals(clusters: list[InsiderCluster]) -> int:
    """Persist new insider cluster signals; skip all-10b5-1 clusters entirely."""
    existing = _existing_keys()
    inserted = 0
    with session_scope() as s:
        for c in clusters:
            if c.all_10b5_1:
                log.info("insider cluster %s skipped: every member 10b5-1", c.ticker)
                continue
            if c.key in existing:
                continue
            kwargs = cluster_to_signal_kwargs(c)
            sig = models.Signal(**kwargs)
            s.add(sig)
            inserted += 1
    return inserted
