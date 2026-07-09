"""Order endpoints (S1.9): the manual paper ticket path (S1.12) and order history."""

from __future__ import annotations

from datetime import UTC, timedelta
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from alphadash.api.deps import get_current_user, get_tenant_db, now_utc
from alphadash.api.portfolio import get_account
from alphadash.api.schemas import FillOut, OrderOut, OrderRequest, OrderResult, ViolationOut
from alphadash.db.models import Account, AssetClass, Fill, Order, OrderSide, OrderType, User
from alphadash.services import limits as limits_service
from alphadash.services import portfolio as portfolio_service
from alphadash.services.execution import place_order

router = APIRouter(tags=["orders"])


def _dec(value: str, field: str) -> Decimal:
    try:
        d = Decimal(value)
    except InvalidOperation:
        raise HTTPException(status_code=422, detail=f"{field} is not a valid decimal") from None
    return d


def _order_out(order: Order, fill: Fill | None) -> OrderOut:
    return OrderOut(
        id=order.id,
        symbol=order.symbol,
        asset_class=order.asset_class.value,
        side=order.side.value,
        order_type=order.order_type.value,
        qty=str(order.qty),
        limit_price=str(order.limit_price) if order.limit_price is not None else None,
        status=order.status.value,
        rejected_reason=order.rejected_reason,
        created_at=(
            order.created_at.replace(tzinfo=UTC)
            if order.created_at.tzinfo is None
            else order.created_at
        ).isoformat(),
        fill=FillOut(
            qty=str(fill.qty),
            price=str(fill.price),
            fee=str(fill.fee),
            filled_at=(
                fill.filled_at.replace(tzinfo=UTC)
                if fill.filled_at.tzinfo is None
                else fill.filled_at
            ).isoformat(),
        )
        if fill
        else None,
    )


@router.post("/orders", response_model=OrderResult, status_code=201)
def create_order(
    body: OrderRequest,
    request: Request,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
    db: Session = Depends(get_tenant_db),
    account: Account = Depends(get_account),
    user: User = Depends(get_current_user),
) -> OrderResult:
    bundle = request.app.state.providers
    symbol = body.symbol.upper()
    try:
        quote_price = bundle.market_data.get_quote(symbol).price
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"no quote for {symbol}: {e}") from None

    now = now_utc()
    # Current drawdown feeds the drawdown-pause gate; 90d window, benchmark irrelevant here.
    report = portfolio_service.performance_series(
        db, account, bundle.market_data, start=(now - timedelta(days=90)).date(), end=now.date()
    )

    result = place_order(
        db,
        account=account,
        symbol=symbol,
        asset_class=AssetClass(body.asset_class),
        side=OrderSide(body.side),
        order_type=OrderType(body.order_type),
        qty=_dec(body.qty, "qty"),
        quote_price=quote_price,
        limit_price=_dec(body.limit_price, "limit_price") if body.limit_price else None,
        limits=limits_service.effective_limits(db, user.id),
        idempotency_key=idempotency_key,
        now=now,
        drawdown_pct=report.current_drawdown_pct,
        paused=limits_service.is_paused(db, account),
    )
    violations = (
        [
            ViolationOut(limit_type=v.limit_type.value if v.limit_type else None, message=v.message)
            for v in result.decision.violations
        ]
        if result.decision
        else []
    )
    return OrderResult(
        order=_order_out(result.order, result.fill), violations=violations, replayed=result.replayed
    )


@router.get("/orders", response_model=list[OrderOut])
def list_orders(
    db: Session = Depends(get_tenant_db), account: Account = Depends(get_account)
) -> list[OrderOut]:
    orders = db.scalars(
        select(Order).where(Order.account_id == account.id).order_by(Order.created_at.desc())
    ).all()
    fills = {
        f.order_id: f
        for f in db.scalars(select(Fill).where(Fill.order_id.in_([o.id for o in orders])))
    }
    return [_order_out(o, fills.get(o.id)) for o in orders]
