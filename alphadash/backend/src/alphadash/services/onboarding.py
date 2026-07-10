"""Guided onboarding (S3.1): risk/goals interview → starter risk profile.

Three multiple-choice answers map deterministically to one of the three named presets.
The mapping is a plain additive score — no LLM, fully unit-testable. Applying onboarding
rewrites the user's (registration-provisioned) risk profile in place, stamps
``users.onboarded_at``, and journals the change so the audit trail shows how the account's
safety rules came to be.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from alphadash.db.models import (
    Account,
    JournalEntryType,
    RiskProfile,
    RiskProfileName,
    User,
)
from alphadash.services import journal

EXPERIENCE = ("new", "some", "confident")
DROP_REACTION = ("sell", "wait", "buy_more")
GOAL = ("preserve", "learn", "grow")

# Named presets. Conservative is deliberately strict; curious still keeps hard rails —
# "loosest" here is nowhere near unconstrained.
PROFILE_PRESETS: dict[RiskProfileName, dict] = {
    RiskProfileName.conservative: {
        "max_position_pct": Decimal("5"),
        "max_asset_class_pct": {"equity": 60, "crypto": 0},
        "max_trades_per_week": 2,
        "cash_floor_pct": Decimal("30"),
        "per_suggestion_max_pct": Decimal("2"),
        "drawdown_pause_pct": Decimal("10"),
    },
    RiskProfileName.balanced: {
        "max_position_pct": Decimal("10"),
        "max_asset_class_pct": {"equity": 80, "crypto": 10},
        "max_trades_per_week": 5,
        "cash_floor_pct": Decimal("10"),
        "per_suggestion_max_pct": Decimal("5"),
        "drawdown_pause_pct": Decimal("15"),
    },
    RiskProfileName.curious: {
        "max_position_pct": Decimal("15"),
        "max_asset_class_pct": {"equity": 90, "crypto": 20},
        "max_trades_per_week": 10,
        "cash_floor_pct": Decimal("5"),
        "per_suggestion_max_pct": Decimal("8"),
        "drawdown_pause_pct": Decimal("20"),
    },
}


class OnboardingError(ValueError):
    """Invalid interview answer. Message is safe to show the user."""


@dataclass(frozen=True)
class OnboardingResult:
    profile: RiskProfile
    profile_name: RiskProfileName
    score: int


def recommend_profile(experience: str, drop_reaction: str, goal: str) -> RiskProfileName:
    """Deterministic answers → preset mapping. Each answer contributes 0–2 points."""
    for value, allowed, label in (
        (experience, EXPERIENCE, "experience"),
        (drop_reaction, DROP_REACTION, "drop_reaction"),
        (goal, GOAL, "goal"),
    ):
        if value not in allowed:
            raise OnboardingError(f"{label} must be one of {', '.join(allowed)}")
    score = EXPERIENCE.index(experience) + DROP_REACTION.index(drop_reaction) + GOAL.index(goal)
    if score <= 1:
        return RiskProfileName.conservative
    if score <= 4:
        return RiskProfileName.balanced
    return RiskProfileName.curious


def apply_onboarding(
    session: Session,
    *,
    user: User,
    account: Account,
    experience: str,
    drop_reaction: str,
    goal: str,
    now: datetime,
) -> OnboardingResult:
    """Apply the recommended preset to the user's risk profile and mark onboarding done.

    Re-running is allowed (the wizard can be repeated from Settings); it simply re-applies
    the newly recommended preset and journals again.
    """
    name = recommend_profile(experience, drop_reaction, goal)
    score = EXPERIENCE.index(experience) + DROP_REACTION.index(drop_reaction) + GOAL.index(goal)
    preset = PROFILE_PRESETS[name]

    profile = session.scalar(
        select(RiskProfile)
        .where(RiskProfile.user_id == user.id)
        .order_by(RiskProfile.created_at.desc())
    )
    if profile is None:  # defensive: registration always provisions one
        profile = RiskProfile(user_id=user.id, name=name, **preset)
        session.add(profile)
    else:
        profile.name = name
        for key, value in preset.items():
            setattr(profile, key, value)
    user.onboarded_at = now
    session.flush()

    journal.record(
        session,
        account_id=account.id,
        entry_type=JournalEntryType.note,
        ref_id=profile.id,
        payload={
            "event": "onboarding",
            "answers": {"experience": experience, "drop_reaction": drop_reaction, "goal": goal},
            "profile": name.value,
            "limits": {k: str(v) for k, v in preset.items()},
        },
    )
    return OnboardingResult(profile=profile, profile_name=name, score=score)
