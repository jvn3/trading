"""Onboarding endpoints (S3.1): interview status + apply answers → starter risk profile."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from alphadash.api.deps import get_current_user, get_tenant_db, now_utc
from alphadash.api.portfolio import get_account
from alphadash.api.schemas import (
    LimitsOut,
    OnboardingOut,
    OnboardingRequest,
    OnboardingStatusOut,
)
from alphadash.db.models import Account, User
from alphadash.services import onboarding as onboarding_service

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


def _preset_to_limits(preset: dict) -> LimitsOut:
    return LimitsOut(
        max_position_pct=str(preset["max_position_pct"]),
        max_asset_class_pct={
            k: str(Decimal(str(v))) for k, v in preset["max_asset_class_pct"].items()
        },
        max_trades_per_week=preset["max_trades_per_week"],
        cash_floor_pct=str(preset["cash_floor_pct"]),
        per_suggestion_max_pct=str(preset["per_suggestion_max_pct"]),
        drawdown_pause_pct=str(preset["drawdown_pause_pct"]),
    )


@router.get("", response_model=OnboardingStatusOut)
def onboarding_status(user: User = Depends(get_current_user)) -> OnboardingStatusOut:
    return OnboardingStatusOut(
        onboarded=user.onboarded_at is not None,
        profiles={
            name.value: _preset_to_limits(preset)
            for name, preset in onboarding_service.PROFILE_PRESETS.items()
        },
    )


@router.post("", response_model=OnboardingOut)
def complete_onboarding(
    body: OnboardingRequest,
    db: Session = Depends(get_tenant_db),
    account: Account = Depends(get_account),
    user: User = Depends(get_current_user),
) -> OnboardingOut:
    try:
        result = onboarding_service.apply_onboarding(
            db,
            user=user,
            account=account,
            experience=body.experience,
            drop_reaction=body.drop_reaction,
            goal=body.goal,
            now=now_utc(),
        )
    except onboarding_service.OnboardingError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    preset = onboarding_service.PROFILE_PRESETS[result.profile_name]
    return OnboardingOut(
        profile=result.profile_name.value,
        limits=_preset_to_limits(preset),
        onboarded=True,
    )
