"""What-if simulator endpoints (S4.3). Read-only teaching math — nothing is ever placed."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from alphadash.api.deps import get_current_user, get_tenant_db, now_utc
from alphadash.api.portfolio import _current_prices, get_account
from alphadash.api.schemas import (
    PositionImpactOut,
    ShockImpactOut,
    ShockRequest,
    TradePreviewOut,
    TradePreviewRequest,
    ViolationOut,
)
from alphadash.db.models import Account, AssetClass, OrderSide, User
from alphadash.domain.scenario import ScenarioError, ShockScenario, apply_shock, preview_trade
from alphadash.services import limits as limits_service
from alphadash.services.execution import build_account_state

router = APIRouter(prefix="/whatif", tags=["whatif"])


def _dec(value: str, name: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation:
        raise HTTPException(status_code=422, detail=f"{name} is not a valid number") from None


def _state(request: Request, db: Session, account: Account, user: User):
    prices = _current_prices(request, db, account)
    limits = limits_service.effective_limits(db, user.id)
    paused = limits_service.is_paused(db, account)
    state = build_account_state(db, account, prices, now=now_utc(), paused=paused)
    return state, limits


@router.post("/shock", response_model=ShockImpactOut)
def shock(
    body: ShockRequest,
    request: Request,
    db: Session = Depends(get_tenant_db),
    account: Account = Depends(get_account),
    user: User = Depends(get_current_user),
) -> ShockImpactOut:
    state, limits = _state(request, db, account, user)
    scenario = ShockScenario(
        equity_pct=_dec(body.equity_pct, "equity_pct"),
        crypto_pct=_dec(body.crypto_pct, "crypto_pct"),
        symbol_overrides={
            k: _dec(v, f"override {k}") for k, v in (body.symbol_overrides or {}).items()
        },
    )
    try:
        impact = apply_shock(state, scenario, limits)
    except ScenarioError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    return ShockImpactOut(
        equity_before=str(impact.equity_before),
        equity_after=str(impact.equity_after),
        equity_change_pct=str(impact.equity_change_pct),
        cash=str(impact.cash),
        positions=[
            PositionImpactOut(
                symbol=p.symbol,
                asset_class=p.asset_class,
                value_before=str(p.value_before),
                value_after=str(p.value_after),
                applied_pct=str(p.applied_pct),
            )
            for p in impact.positions
        ],
        allocation_after_pct={k: float(v) for k, v in impact.allocation_after_pct.items()},
        would_trip_drawdown_pause=impact.would_trip_drawdown_pause,
        drawdown_pause_pct=(
            str(impact.drawdown_pause_pct) if impact.drawdown_pause_pct is not None else None
        ),
    )


@router.post("/trade", response_model=TradePreviewOut)
def trade_preview(
    body: TradePreviewRequest,
    request: Request,
    db: Session = Depends(get_tenant_db),
    account: Account = Depends(get_account),
    user: User = Depends(get_current_user),
) -> TradePreviewOut:
    qty = _dec(body.qty, "qty")
    symbol = body.symbol.strip().upper()
    try:
        price = request.app.state.providers.market_data.get_quote(symbol).price
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"no quote for {symbol}: {e}") from None

    state, limits = _state(request, db, account, user)
    preview = preview_trade(
        state,
        limits,
        symbol=symbol,
        asset_class=AssetClass(body.asset_class),
        side=OrderSide(body.side),
        qty=qty,
        price=price,
    )
    return TradePreviewOut(
        allowed=preview.decision.allow,
        violations=[
            ViolationOut(limit_type=v.limit_type.value if v.limit_type else None, message=v.message)
            for v in preview.decision.violations
        ],
        est_price=str(price),
        cash_after=str(preview.cash_after),
        position_value_after=str(preview.position_value_after),
        position_allocation_after_pct=float(preview.position_allocation_after_pct),
        cash_allocation_after_pct=float(preview.cash_allocation_after_pct),
    )
