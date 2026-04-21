"""Role-weight parser and per-insider quality helpers for Phase 4.

FMP's ``typeOfOwner`` field (stored in ``DisclosedTrade.person_role`` after
ingest) is free text: ``"officer: EVP, Chief Human Resources Off"``,
``"director"``, ``"10 percent owner"``, ``"officer: President, CEO"``.
This module maps it to a numeric weight used by the cluster detector.

Weights follow ``strategies/phase2_build_spec.md §1.2``. Highest match wins.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from jay_trading.data.fmp import FMPClient, FMPError

log = logging.getLogger(__name__)


#: Ordered list of ``(regex, weight, label)`` tuples. Order matters — highest
#: weight that matches wins. We return the first match of the *highest*
#: weight when multiple apply, so e.g. "officer: President, CEO" scores as
#: CEO (3.0) rather than generic officer (1.2).
_ROLE_RULES: list[tuple[re.Pattern[str], float, str]] = [
    (re.compile(r"\b(chief\s+executive|ceo)\b", re.I), 3.0, "CEO"),
    (re.compile(r"\b(chief\s+financial|cfo)\b", re.I), 2.5, "CFO"),
    (re.compile(r"\b(chief\s+operating|coo)\b", re.I), 2.0, "COO"),
    (re.compile(r"\b10\s*(percent|%)\s*owner\b", re.I), 1.5, "10% holder"),
    (re.compile(r"\bofficer\b", re.I), 1.2, "Officer"),
    (re.compile(r"\bdirector\b", re.I), 1.0, "Director"),
]

_DEFAULT_WEIGHT = 0.8
_DEFAULT_LABEL = "Other"


@dataclass(frozen=True)
class RoleWeight:
    weight: float
    label: str


def role_weight(raw: str | None) -> RoleWeight:
    """Parse ``typeOfOwner`` (or equivalent) into a :class:`RoleWeight`.

    Returns the default (0.8, "Other") if nothing matches, so an unparseable
    role still counts toward the cluster member count but less heavily.
    """
    if not raw:
        return RoleWeight(_DEFAULT_WEIGHT, _DEFAULT_LABEL)
    best: RoleWeight | None = None
    for pat, weight, label in _ROLE_RULES:
        if pat.search(raw) is not None:
            if best is None or weight > best.weight:
                best = RoleWeight(weight, label)
    return best or RoleWeight(_DEFAULT_WEIGHT, _DEFAULT_LABEL)


# -- Piotroski fundamental-quality gate ------------------------------------


def fetch_piotroski(ticker: str, *, fmp: FMPClient | None = None) -> int | None:
    """Return the current Piotroski F-score for ``ticker``, or ``None`` on error.

    Score is 0–9. A Piotroski ≥ 5 is the "healthy enough" gate in the spec;
    ≥ 7 is the "strong fundamentals" bonus. Callers apply the threshold; we
    just return the raw number.
    """
    own_client = fmp is None
    fmp = fmp or FMPClient()
    try:
        rows = fmp.request("financial_scores", params={"symbol": ticker.upper()})
    except FMPError as e:
        log.warning("piotroski fetch failed for %s: %s", ticker, e)
        return None
    except Exception as e:  # noqa: BLE001
        log.warning("piotroski fetch failed for %s: %s", ticker, e)
        return None
    finally:
        if own_client:
            fmp.close()
    if not isinstance(rows, list) or not rows:
        return None
    row = rows[0]
    score = row.get("piotroskiScore")
    try:
        return int(score) if score is not None else None
    except (TypeError, ValueError):
        return None


def piotroski_multiplier(score: int | None) -> float:
    """Map Piotroski F-score to the cluster-score multiplier in the spec.

    Per ``strategies/phase2_build_spec.md §1.5``:
      - score >= 7 → 1.2
      - 5 <= score < 7 → 1.0
      - score < 5 or None → 0.6
    """
    if score is None:
        return 0.6
    if score >= 7:
        return 1.2
    if score >= 5:
        return 1.0
    return 0.6


def recency_multiplier(days_since_newest_filing: int) -> float:
    """1.1 if newest filing within 5 days, else 1.0 — per spec §1.5."""
    return 1.1 if days_since_newest_filing <= 5 else 1.0
