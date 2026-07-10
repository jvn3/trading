"""Strategy Lab endpoints (S4.2): draft → backtest → activate/archive → list.

Activation is gated on having at least one backtest — you cannot switch on a strategy you have
never seen tested. Active strategies feed candidates into the normal agent pipeline; they never
place orders themselves.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from alphadash.api.deps import get_current_user, get_tenant_db, now_utc
from alphadash.api.portfolio import get_account
from alphadash.api.schemas import (
    BacktestOut,
    BacktestWindowOut,
    StrategyDraftRequest,
    StrategyOut,
)
from alphadash.db.models import Account, Strategy, StrategyStatus, User
from alphadash.domain.strategy_backtest import BacktestError
from alphadash.domain.strategy_rules import StrategyParams, describe
from alphadash.services import strategy_author

router = APIRouter(prefix="/strategies", tags=["strategies"])


def _strategy_out(session: Session, strategy: Strategy) -> StrategyOut:
    latest = strategy_author.latest_backtest(session, strategy)
    return StrategyOut(
        id=strategy.id,
        name=strategy.name,
        source_text=strategy.source_text,
        status=strategy.status.value,
        params=strategy.params,
        description=describe(StrategyParams.model_validate(strategy.params)),
        created_at=strategy.created_at.isoformat(),
        last_backtest=latest.results if latest else None,
    )


def _get_strategy(db: Session, user: User, strategy_id: str) -> Strategy:
    strategy = db.scalar(
        select(Strategy).where(Strategy.id == strategy_id, Strategy.user_id == user.id)
    )
    if strategy is None:
        raise HTTPException(status_code=404, detail="strategy not found")
    return strategy


@router.get("", response_model=list[StrategyOut])
def list_strategies(
    db: Session = Depends(get_tenant_db), user: User = Depends(get_current_user)
) -> list[StrategyOut]:
    rows = db.scalars(
        select(Strategy)
        .where(Strategy.user_id == user.id, Strategy.status != StrategyStatus.archived)
        .order_by(Strategy.created_at.desc())
    ).all()
    return [_strategy_out(db, s) for s in rows]


@router.post("/draft", response_model=StrategyOut, status_code=201)
def draft(
    body: StrategyDraftRequest,
    request: Request,
    db: Session = Depends(get_tenant_db),
    account: Account = Depends(get_account),
    user: User = Depends(get_current_user),
) -> StrategyOut:
    try:
        result = strategy_author.draft_strategy(
            db,
            user=user,
            account=account,
            llm=request.app.state.llm,
            text=body.text,
            now=now_utc(),
        )
    except strategy_author.StrategyAuthorError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    return _strategy_out(db, result.strategy)


@router.post("/{strategy_id}/backtest", response_model=BacktestOut)
def backtest(
    strategy_id: str,
    request: Request,
    db: Session = Depends(get_tenant_db),
    account: Account = Depends(get_account),
    user: User = Depends(get_current_user),
) -> BacktestOut:
    strategy = _get_strategy(db, user, strategy_id)
    try:
        _, result = strategy_author.backtest_strategy(
            db,
            strategy=strategy,
            account=account,
            bundle=request.app.state.providers,
            now=now_utc(),
        )
    except BacktestError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    return BacktestOut(
        strategy_id=strategy.id,
        windows=[
            BacktestWindowOut(
                start=w.start.isoformat(),
                end=w.end.isoformat(),
                strategy_return_pct=float(w.strategy_return_pct),
                buy_hold_return_pct=float(w.buy_hold_return_pct),
                trades=w.trades,
            )
            for w in result.windows
        ],
        total_return_pct=float(result.total_return_pct),
        buy_hold_return_pct=float(result.buy_hold_return_pct),
        benchmark_return_pct=float(result.benchmark_return_pct),
        max_drawdown_pct=float(result.max_drawdown_pct),
        closed_trades=len(result.closed_trades),
        win_rate_pct=float(result.win_rate_pct) if result.win_rate_pct is not None else None,
        windows_beating_buy_hold=result.windows_beating_buy_hold,
        small_sample=result.small_sample,
        days=result.days,
        caveats=list(result.caveats),
    )


def _set_status(
    db: Session, user: User, account: Account, strategy_id: str, status: StrategyStatus
) -> StrategyOut:
    strategy = _get_strategy(db, user, strategy_id)
    try:
        strategy_author.set_status(db, strategy=strategy, account=account, status=status)
    except strategy_author.StrategyAuthorError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    return _strategy_out(db, strategy)


@router.post("/{strategy_id}/activate", response_model=StrategyOut)
def activate(
    strategy_id: str,
    db: Session = Depends(get_tenant_db),
    account: Account = Depends(get_account),
    user: User = Depends(get_current_user),
) -> StrategyOut:
    return _set_status(db, user, account, strategy_id, StrategyStatus.active)


@router.post("/{strategy_id}/archive", response_model=StrategyOut)
def archive(
    strategy_id: str,
    db: Session = Depends(get_tenant_db),
    account: Account = Depends(get_account),
    user: User = Depends(get_current_user),
) -> StrategyOut:
    return _set_status(db, user, account, strategy_id, StrategyStatus.archived)
