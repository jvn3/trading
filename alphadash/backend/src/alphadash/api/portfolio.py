"""Portfolio + account endpoints (S1.9). Read paths for the S1.11 screen and app shell."""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from alphadash.api.deps import get_current_user, get_tenant_db, now_utc
from alphadash.api.schemas import (
    AccountOut,
    ClosedTradesOut,
    LimitsOut,
    LimitsUpdateOut,
    LimitsUpdateRequest,
    PerformanceOut,
    PerformancePointOut,
    PortfolioOut,
    PositionOut,
    QuoteOut,
    ReviewOut,
)
from alphadash.db.models import Account, Position, User
from alphadash.domain.risk import format_decimal
from alphadash.services import limits as limits_service
from alphadash.services import portfolio as portfolio_service
from alphadash.services import review as review_service

log = logging.getLogger(__name__)
router = APIRouter(tags=["portfolio"])


def get_account(
    db: Session = Depends(get_tenant_db), user: User = Depends(get_current_user)
) -> Account:
    account = db.scalar(
        select(Account).where(Account.user_id == user.id).order_by(Account.created_at)
    )
    if account is None:
        raise HTTPException(status_code=404, detail="no account provisioned")
    return account


def _current_prices(request: Request, db: Session, account: Account) -> dict[str, Decimal]:
    bundle = request.app.state.providers
    prices: dict[str, Decimal] = {}
    for p in db.scalars(select(Position).where(Position.account_id == account.id)):
        try:
            prices[p.symbol] = bundle.market_data.get_quote(p.symbol).price
        except Exception as e:  # missing quote → snapshot falls back to avg_cost
            log.warning("quote lookup failed for %s: %s", p.symbol, e)
    return prices


@router.get("/account", response_model=AccountOut)
def account_info(
    request: Request,
    db: Session = Depends(get_tenant_db),
    account: Account = Depends(get_account),
) -> AccountOut:
    return AccountOut(
        id=account.id,
        mode=account.mode.value,
        base_currency=account.base_currency,
        starting_equity=str(account.starting_equity),
        paused=limits_service.is_paused(db, account),
        trading_mode=request.app.state.settings.trading_mode,
    )


@router.get("/account/limits", response_model=LimitsOut)
def account_limits(
    db: Session = Depends(get_tenant_db), user: User = Depends(get_current_user)
) -> LimitsOut:
    limits = limits_service.effective_limits(db, user.id)
    # format_decimal: users see "10", not the Numeric(24,8) artifact "10.00000000" (S3.7).
    fmt = format_decimal
    return LimitsOut(
        max_position_pct=fmt(limits.max_position_pct)
        if limits.max_position_pct is not None
        else None,
        max_asset_class_pct={k: fmt(v) for k, v in limits.max_asset_class_pct.items()},
        max_trades_per_week=limits.max_trades_per_week,
        cash_floor_pct=fmt(limits.cash_floor_pct) if limits.cash_floor_pct is not None else None,
        per_suggestion_max_pct=fmt(limits.per_suggestion_max_pct)
        if limits.per_suggestion_max_pct is not None
        else None,
        drawdown_pause_pct=fmt(limits.drawdown_pause_pct)
        if limits.drawdown_pause_pct is not None
        else None,
    )


@router.put("/account/limits", response_model=LimitsUpdateOut)
def update_account_limits(
    body: LimitsUpdateRequest,
    db: Session = Depends(get_tenant_db),
    account: Account = Depends(get_account),
    user: User = Depends(get_current_user),
) -> LimitsUpdateOut:
    try:
        update = limits_service.LimitsUpdate(
            max_position_pct=Decimal(body.max_position_pct),
            max_asset_class_pct={k: Decimal(v) for k, v in body.max_asset_class_pct.items()},
            max_trades_per_week=body.max_trades_per_week,
            cash_floor_pct=Decimal(body.cash_floor_pct),
            per_suggestion_max_pct=Decimal(body.per_suggestion_max_pct),
            drawdown_pause_pct=Decimal(body.drawdown_pause_pct),
        )
    except (InvalidOperation, ValueError):
        raise HTTPException(
            status_code=422, detail="limits must be valid decimal numbers"
        ) from None
    try:
        profile, loosened = limits_service.update_limits(
            db, user_id=user.id, account=account, update=update, now=now_utc()
        )
    except limits_service.LimitsError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    return LimitsUpdateOut(
        limits=account_limits(db, user), profile=profile.name.value, loosened=loosened
    )


@router.post("/account/pause", response_model=AccountOut)
def pause_account(
    request: Request,
    db: Session = Depends(get_tenant_db),
    account: Account = Depends(get_account),
    user: User = Depends(get_current_user),
) -> AccountOut:
    limits_service.set_paused(db, account, paused=True, by=user.id)
    return account_info(request, db, account)


@router.post("/account/resume", response_model=AccountOut)
def resume_account(
    request: Request,
    db: Session = Depends(get_tenant_db),
    account: Account = Depends(get_account),
    user: User = Depends(get_current_user),
) -> AccountOut:
    limits_service.set_paused(db, account, paused=False, by=user.id)
    return account_info(request, db, account)


@router.get("/portfolio", response_model=PortfolioOut)
def portfolio(
    request: Request,
    db: Session = Depends(get_tenant_db),
    account: Account = Depends(get_account),
) -> PortfolioOut:
    snap = portfolio_service.portfolio_snapshot(
        db, account, prices=_current_prices(request, db, account)
    )
    return PortfolioOut(
        equity=str(snap.equity),
        cash=str(snap.cash),
        positions=[
            PositionOut(
                symbol=p.symbol,
                asset_class=p.asset_class,
                quantity=str(p.quantity),
                avg_cost=str(p.avg_cost),
                market_value=str(p.market_value),
                unrealized_pl=str(p.unrealized_pl),
                allocation_pct=float(p.allocation_pct),
            )
            for p in snap.positions
        ],
        allocation_pct={k: float(v) for k, v in snap.allocation_pct.items()},
    )


@router.get("/portfolio/performance", response_model=PerformanceOut)
def performance(
    request: Request,
    days: int = Query(default=90, ge=7, le=365),
    db: Session = Depends(get_tenant_db),
    account: Account = Depends(get_account),
) -> PerformanceOut:
    now = now_utc()
    report = portfolio_service.performance_series(
        db,
        account,
        request.app.state.providers.market_data,
        start=(now - timedelta(days=days)).date(),
        end=now.date(),
    )
    return PerformanceOut(
        points=[
            PerformancePointOut(
                day=p.day.isoformat(),
                equity=str(p.equity),
                benchmark_equity=str(p.benchmark_equity),
            )
            for p in report.points
        ],
        return_pct=float(report.return_pct),
        benchmark_return_pct=float(report.benchmark_return_pct),
        max_drawdown_pct=float(report.max_drawdown_pct),
        current_drawdown_pct=float(report.current_drawdown_pct),
        benchmark_symbol=report.benchmark_symbol,
    )


@router.get("/portfolio/review", response_model=ReviewOut)
def performance_review(
    request: Request,
    days: int = Query(default=90, ge=7, le=365),
    db: Session = Depends(get_tenant_db),
    account: Account = Depends(get_account),
) -> ReviewOut:
    """S3.5 honest review: return is never served without benchmark + drawdown beside it."""
    now = now_utc()
    result = review_service.honest_review(
        db,
        account,
        request.app.state.providers.market_data,
        start=(now - timedelta(days=days)).date(),
        end=now.date(),
    )
    report = result.performance
    return ReviewOut(
        performance=PerformanceOut(
            points=[
                PerformancePointOut(
                    day=p.day.isoformat(),
                    equity=str(p.equity),
                    benchmark_equity=str(p.benchmark_equity),
                )
                for p in report.points
            ],
            return_pct=float(report.return_pct),
            benchmark_return_pct=float(report.benchmark_return_pct),
            max_drawdown_pct=float(report.max_drawdown_pct),
            current_drawdown_pct=float(report.current_drawdown_pct),
            benchmark_symbol=report.benchmark_symbol,
        ),
        trades=ClosedTradesOut(
            closed_trades=result.trades.closed_trades,
            wins=result.trades.wins,
            losses=result.trades.losses,
            win_rate_pct=float(result.trades.win_rate_pct)
            if result.trades.win_rate_pct is not None
            else None,
            small_sample=result.trades.small_sample,
        ),
        verdict=result.verdict,
        disclaimers=list(result.disclaimers),
    )


@router.get("/quotes/{symbol}", response_model=QuoteOut)
def quote(symbol: str, request: Request, _user: User = Depends(get_current_user)) -> QuoteOut:
    try:
        q = request.app.state.providers.market_data.get_quote(symbol.upper())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"quote unavailable: {e}") from None
    return QuoteOut(
        symbol=q.symbol,
        price=str(q.price),
        as_of=q.provenance.as_of.isoformat(),
        source=q.provenance.source,
        is_stale=q.provenance.is_stale,
    )
