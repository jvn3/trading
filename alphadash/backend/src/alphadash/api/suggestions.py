"""Suggestions + agent endpoints (S2.5) and the L3 explanation trace (S2.6).

Approve/modify execute through the S1.5 paper engine (which re-runs the risk gate); dismiss just
records the decision. Every human decision lands in ``decisions`` and the journal.
"""

from __future__ import annotations

from datetime import UTC
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from alphadash.api.deps import get_current_user, get_tenant_db, now_utc
from alphadash.api.orders import _order_out
from alphadash.api.portfolio import get_account
from alphadash.api.schemas import OrderOut, ViolationOut
from alphadash.db.models import (
    Account,
    AgentRun,
    AssetClass,
    DataSnapshot,
    DecidedBy,
    Decision,
    DecisionAction,
    JournalEntryType,
    OrderSide,
    OrderType,
    RiskEvent,
    Suggestion,
    SuggestionStatus,
    User,
)
from alphadash.services import journal
from alphadash.services import limits as limits_service
from alphadash.services.agent import run_agent, suggestion_to_view
from alphadash.services.execution import place_order

router = APIRouter(tags=["suggestions"])


class SuggestionListOut(BaseModel):
    suggestions: list[dict[str, Any]]


class AgentRunOut(BaseModel):
    run_id: str
    status: str
    suggestions: list[dict[str, Any]]


class DecisionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)
    qty: str | None = None  # modify only — Decimal string


class DecisionResult(BaseModel):
    suggestion: dict[str, Any]
    order: OrderOut | None = None
    violations: list[ViolationOut] = []


def _get_suggestion(db: Session, account: Account, suggestion_id: str) -> Suggestion:
    suggestion = db.scalar(
        select(Suggestion).where(
            Suggestion.id == suggestion_id, Suggestion.account_id == account.id
        )
    )
    if suggestion is None:
        raise HTTPException(status_code=404, detail="suggestion not found")
    return suggestion


def _expire_stale(db: Session, account: Account, now) -> None:
    stale = db.scalars(
        select(Suggestion).where(
            Suggestion.account_id == account.id,
            Suggestion.status == SuggestionStatus.proposed,
            Suggestion.expires_at.is_not(None),
        )
    )
    for s in stale:
        expires = s.expires_at if s.expires_at.tzinfo else s.expires_at.replace(tzinfo=UTC)
        if expires <= now:
            s.status = SuggestionStatus.expired


@router.post("/agent/run", response_model=AgentRunOut, status_code=201)
def trigger_agent_run(
    request: Request,
    db: Session = Depends(get_tenant_db),
    account: Account = Depends(get_account),
    user: User = Depends(get_current_user),
) -> AgentRunOut:
    result = run_agent(
        db,
        account=account,
        user=user,
        bundle=request.app.state.providers,
        llm=request.app.state.llm,
        now=now_utc(),
    )
    return AgentRunOut(
        run_id=result.run.id,
        status=result.run.status.value,
        suggestions=[suggestion_to_view(s) for s in result.suggestions],
    )


@router.get("/suggestions", response_model=SuggestionListOut)
def list_suggestions(
    db: Session = Depends(get_tenant_db),
    account: Account = Depends(get_account),
) -> SuggestionListOut:
    _expire_stale(db, account, now_utc())
    rows = db.scalars(
        select(Suggestion)
        .where(Suggestion.account_id == account.id)
        .order_by(Suggestion.created_at.desc())
        .limit(20)
    ).all()
    return SuggestionListOut(suggestions=[suggestion_to_view(s) for s in rows])


def _record_decision(
    db: Session,
    account: Account,
    suggestion: Suggestion,
    action: DecisionAction,
    *,
    reason: str | None = None,
    modified_sizing: dict | None = None,
) -> Decision:
    decision = Decision(
        suggestion_id=suggestion.id,
        action=action,
        reason=reason,
        modified_sizing=modified_sizing,
        decided_by=DecidedBy.user,
    )
    db.add(decision)
    db.flush()
    journal.record(
        db,
        account_id=account.id,
        entry_type=JournalEntryType.decision,
        ref_id=decision.id,
        payload={
            "suggestion_id": suggestion.id,
            "action": action.value,
            "reason": reason,
            "modified_sizing": modified_sizing,
        },
    )
    return decision


def _execute_suggestion(
    request: Request,
    db: Session,
    account: Account,
    user: User,
    suggestion: Suggestion,
    qty: Decimal,
):
    sizing = suggestion.sizing
    symbol = sizing["symbol"]
    try:
        quote_price = request.app.state.providers.market_data.get_quote(symbol).price
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"no quote for {symbol}: {e}") from None
    return place_order(
        db,
        account=account,
        symbol=symbol,
        asset_class=AssetClass(sizing["asset_class"]),
        side=OrderSide(sizing["side"]),
        order_type=OrderType(sizing["order_type"]),
        qty=qty,
        quote_price=quote_price,
        limits=limits_service.effective_limits(db, user.id),
        idempotency_key=f"suggestion:{suggestion.id}",
        now=now_utc(),
        suggestion_id=suggestion.id,
        paused=limits_service.is_paused(db, account),
    )


def _decide_and_maybe_execute(
    request: Request,
    db: Session,
    account: Account,
    user: User,
    suggestion: Suggestion,
    action: DecisionAction,
    body: DecisionRequest,
) -> DecisionResult:
    if suggestion.status is SuggestionStatus.blocked and action is not DecisionAction.dismiss:
        raise HTTPException(
            status_code=409,
            detail="this suggestion was blocked by your risk limits and cannot be approved",
        )
    if suggestion.status not in (SuggestionStatus.proposed, SuggestionStatus.blocked):
        raise HTTPException(status_code=409, detail=f"already {suggestion.status.value}")

    order_out = None
    violations: list[ViolationOut] = []
    if action is DecisionAction.dismiss:
        _record_decision(db, account, suggestion, action, reason=body.reason)
        suggestion.status = SuggestionStatus.dismissed
    else:
        qty = Decimal(suggestion.sizing["qty"])
        modified_sizing = None
        if action is DecisionAction.modify:
            if not body.qty:
                raise HTTPException(status_code=422, detail="modify requires qty")
            try:
                qty = Decimal(body.qty)
            except InvalidOperation:
                raise HTTPException(status_code=422, detail="qty is not a valid decimal") from None
            if qty <= 0:
                raise HTTPException(status_code=422, detail="qty must be positive")
            modified_sizing = {**suggestion.sizing, "qty": str(qty)}
        _record_decision(
            db, account, suggestion, action, reason=body.reason, modified_sizing=modified_sizing
        )
        result = _execute_suggestion(request, db, account, user, suggestion, qty)
        order_out = _order_out(result.order, result.fill)
        if result.decision and not result.decision.allow:
            violations = [
                ViolationOut(
                    limit_type=v.limit_type.value if v.limit_type else None, message=v.message
                )
                for v in result.decision.violations
            ]
            # Execution veto at approval time: keep it honest — mark blocked with the reason.
            suggestion.status = SuggestionStatus.blocked
            suggestion.blocked_reason = (result.decision.reason or "")[:500]
        else:
            suggestion.status = (
                SuggestionStatus.approved
                if action is DecisionAction.approve
                else SuggestionStatus.modified
            )
    db.flush()
    return DecisionResult(
        suggestion=suggestion_to_view(suggestion), order=order_out, violations=violations
    )


@router.post("/suggestions/{suggestion_id}/approve", response_model=DecisionResult)
def approve(
    suggestion_id: str,
    body: DecisionRequest,
    request: Request,
    db: Session = Depends(get_tenant_db),
    account: Account = Depends(get_account),
    user: User = Depends(get_current_user),
) -> DecisionResult:
    suggestion = _get_suggestion(db, account, suggestion_id)
    return _decide_and_maybe_execute(
        request, db, account, user, suggestion, DecisionAction.approve, body
    )


@router.post("/suggestions/{suggestion_id}/modify", response_model=DecisionResult)
def modify(
    suggestion_id: str,
    body: DecisionRequest,
    request: Request,
    db: Session = Depends(get_tenant_db),
    account: Account = Depends(get_account),
    user: User = Depends(get_current_user),
) -> DecisionResult:
    suggestion = _get_suggestion(db, account, suggestion_id)
    return _decide_and_maybe_execute(
        request, db, account, user, suggestion, DecisionAction.modify, body
    )


@router.post("/suggestions/{suggestion_id}/dismiss", response_model=DecisionResult)
def dismiss(
    suggestion_id: str,
    body: DecisionRequest,
    request: Request,
    db: Session = Depends(get_tenant_db),
    account: Account = Depends(get_account),
    user: User = Depends(get_current_user),
) -> DecisionResult:
    suggestion = _get_suggestion(db, account, suggestion_id)
    return _decide_and_maybe_execute(
        request, db, account, user, suggestion, DecisionAction.dismiss, body
    )


class TraceOut(BaseModel):
    """S2.6 — the full 'show your work' trail: candidate logic → source data → model metadata."""

    suggestion_id: str
    candidate_ref: str
    signal_features: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    sizing: dict[str, Any]
    prompt_version: str
    model_version: str
    agent_run_id: str | None
    snapshot_id: str | None
    snapshot_as_of: str | None
    risk_events: list[dict[str, Any]]


@router.get("/suggestions/{suggestion_id}/trace", response_model=TraceOut)
def trace(
    suggestion_id: str,
    db: Session = Depends(get_tenant_db),
    account: Account = Depends(get_account),
) -> TraceOut:
    s = _get_suggestion(db, account, suggestion_id)
    run = db.scalar(
        select(AgentRun)
        .where(
            AgentRun.account_id == account.id,
            AgentRun.prompt_version == s.prompt_version,
        )
        .order_by(AgentRun.started_at.desc())
    )
    snapshot = (
        db.get(DataSnapshot, run.input_snapshot_id) if run and run.input_snapshot_id else None
    )
    events = db.scalars(select(RiskEvent).where(RiskEvent.suggestion_id == s.id)).all()
    evidence = s.evidence or []
    return TraceOut(
        suggestion_id=s.id,
        candidate_ref=s.candidate_ref,
        signal_features=[e for e in evidence if str(e.get("source", "")).startswith("signal:")],
        evidence=[e for e in evidence if not str(e.get("source", "")).startswith("signal:")],
        sizing=s.sizing or {},
        prompt_version=s.prompt_version,
        model_version=s.model_version,
        agent_run_id=run.id if run else None,
        snapshot_id=snapshot.id if snapshot else None,
        snapshot_as_of=(snapshot.payload or {}).get("as_of") if snapshot else None,
        risk_events=[{"event_type": e.event_type.value, "detail": e.detail} for e in events],
    )
