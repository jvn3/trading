"""Confidence-calibration tracking (S2.9).

A calibrated agent's 0.7-confidence ideas should work out more often than its 0.4 ones. We track
this by joining suggestions → decisions → fills and marking an executed suggestion a "win" when
the current price has moved in the suggested direction since the fill. Buckets: low (<0.4),
medium (<0.7), high (≥0.7) — same bands the UI shows (S0.4 ConfidenceBadge).

Early on, samples are tiny — the report says so instead of pretending statistical power.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from alphadash.db.models import Account, Fill, Order, OrderSide, Suggestion, SuggestionStatus

BANDS = (
    ("low", Decimal("0"), Decimal("0.4")),
    ("medium", Decimal("0.4"), Decimal("0.7")),
    ("high", Decimal("0.7"), Decimal("1.000001")),
)


@dataclass(frozen=True)
class BandStats:
    band: str
    total_suggested: int
    executed: int
    wins: int
    losses: int
    unresolved: int  # executed but no price available to judge yet

    @property
    def hit_rate(self) -> float | None:
        judged = self.wins + self.losses
        return round(self.wins / judged, 3) if judged else None


@dataclass(frozen=True)
class CalibrationReport:
    bands: list[BandStats]
    sample_note: str


def calibration_report(
    session: Session, account: Account, prices: dict[str, Decimal]
) -> CalibrationReport:
    suggestions = session.scalars(
        select(Suggestion).where(Suggestion.account_id == account.id)
    ).all()
    orders = {
        o.suggestion_id: o
        for o in session.scalars(
            select(Order).where(Order.account_id == account.id, Order.suggestion_id.is_not(None))
        )
    }
    fills = {
        f.order_id: f
        for f in session.scalars(
            select(Fill).where(Fill.order_id.in_([o.id for o in orders.values()]))
        )
    }

    stats: list[BandStats] = []
    for band, lo, hi in BANDS:
        in_band = [s for s in suggestions if lo <= s.confidence < hi]
        executed = wins = losses = unresolved = 0
        for s in in_band:
            if s.status not in (SuggestionStatus.approved, SuggestionStatus.modified):
                continue
            order = orders.get(s.id)
            fill = fills.get(order.id) if order else None
            if fill is None:
                continue
            executed += 1
            price = prices.get(order.symbol)
            if price is None:
                unresolved += 1
                continue
            moved = price - fill.price
            favorable = moved > 0 if order.side is OrderSide.buy else moved < 0
            if moved == 0:
                unresolved += 1
            elif favorable:
                wins += 1
            else:
                losses += 1
        stats.append(
            BandStats(
                band=band,
                total_suggested=len(in_band),
                executed=executed,
                wins=wins,
                losses=losses,
                unresolved=unresolved,
            )
        )

    judged = sum(b.wins + b.losses for b in stats)
    note = (
        f"{judged} judged outcome(s) — too few for statistical claims; directional only."
        if judged < 30
        else f"{judged} judged outcomes."
    )
    return CalibrationReport(bands=stats, sample_note=note)
