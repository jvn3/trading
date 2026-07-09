"""Freshness policy (S0.3 frozen contract).

``stamp`` sets ``provenance.is_stale`` from the feed's max age. Downstream rule (declared here,
enforced in S2.x): stale data must lower confidence or block suggestions — never silently feed
decisions. ``is_stale=True`` is how that signal travels.

``now`` is always passed in — no wall-clock reads inside logic (repo convention: inject time).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypeVar

from alphadash.providers.dto import Bar, FundamentalSnapshot, MacroPoint, Quote

DtoT = TypeVar("DtoT", Quote, Bar, FundamentalSnapshot, MacroPoint)


@dataclass(frozen=True)
class FreshnessPolicy:
    """Max tolerated age per feed, keyed by feed name: "quote","bar","news","fundamentals","macro"."""

    max_age: dict[str, timedelta]

    def stamp(self, feed: str, dto: DtoT, *, now: datetime) -> DtoT:
        """Set ``provenance.is_stale = (now - as_of) > max_age[feed]`` and return the DTO."""
        limit = self.max_age[feed]
        dto.provenance.is_stale = (now - dto.provenance.as_of) > limit
        return dto
