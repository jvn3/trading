"""S2.3/S2.4 tests: pipeline end-to-end on fakes, schema retry, risk-after-LLM, faithfulness,
and the frozen S0.4 view contract."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from alphadash.db.models import (
    AgentRun,
    AgentRunStatus,
    DataSnapshot,
    JournalEntry,
    JournalEntryType,
    RiskEvent,
    RiskEventType,
    RiskProfile,
    SuggestionStatus,
    User,
)
from alphadash.llm.base import LLMError
from alphadash.llm.fake import FakeLLM
from alphadash.providers.factory import build_stub_bundle
from alphadash.services import auth as auth_service
from alphadash.services.agent import run_agent, suggestion_to_view
from tests.factories import make_engine

NOW = datetime(2026, 7, 9, 15, 0, tzinfo=UTC)
D = Decimal


@pytest.fixture()
def session():
    with Session(make_engine()) as s:
        yield s


@pytest.fixture()
def setup(session):
    reg = auth_service.register_user(
        session, email="agent@example.com", password="long-enough-pw", display_name="A"
    )
    session.commit()
    user = session.get(User, reg.user.id)
    return user, reg.account


def run(session, setup, llm=None):
    user, account = setup
    return run_agent(
        session,
        account=account,
        user=user,
        bundle=build_stub_bundle(),
        llm=llm or FakeLLM(),
        now=NOW,
    )


def test_full_pipeline_produces_bounded_suggestions(session, setup) -> None:
    result = run(session, setup)
    session.commit()

    assert result.run.status is AgentRunStatus.completed
    assert 1 <= len(result.suggestions) <= 3  # cadence cap
    s = result.suggestions[0]
    assert s.prompt_version == "s2.3-v1" and s.model_version == "fake-llm-1"
    assert s.status in (SuggestionStatus.proposed, SuggestionStatus.blocked)
    assert Decimal("0") <= s.confidence <= Decimal("1")
    # snapshot linked (no-lookahead trail)
    assert result.run.input_snapshot_id is not None
    assert session.get(DataSnapshot, result.run.input_snapshot_id).agent_run_id == result.run.id
    # journaled
    journal_rows = session.scalars(
        select(JournalEntry).where(JournalEntry.entry_type == JournalEntryType.suggestion)
    ).all()
    assert {j.ref_id for j in journal_rows} == {x.id for x in result.suggestions}


def test_sizing_is_deterministic_and_within_caps(session, setup) -> None:
    result = run(session, setup)
    for s in result.suggestions:
        sizing = s.sizing
        notional = D(sizing["qty"]) * D(sizing["est_price"])
        # per-suggestion cap is 5% of 10k = 500 (+rounding cent)
        assert notional <= D("500.01"), sizing
        assert sizing["order_type"] == "market"


def test_malformed_llm_output_retried_then_ok(session, setup) -> None:
    good = None  # captured from rule-based run in a scratch pass
    scratch = FakeLLM()
    run(session, setup, scratch)
    session.rollback()
    # regenerate account state after rollback
    reg = auth_service.register_user(
        session, email="retry@example.com", password="long-enough-pw", display_name="R"
    )
    session.commit()
    user = session.get(User, reg.user.id)

    # Build a valid response by letting rule-based fake see the same prompt shape:
    prompt = scratch.calls[-1].messages[0]["content"]
    good = FakeLLM()._rule_based([{"role": "user", "content": prompt}])

    llm = FakeLLM(scripted=["not json at all", good])
    result = run_agent(
        session, account=reg.account, user=user, bundle=build_stub_bundle(), llm=llm, now=NOW
    )
    assert result.suggestions  # second attempt succeeded
    assert len(llm.calls) == 2  # retry happened with feedback


def test_llm_inventing_trades_is_rejected(session, setup) -> None:
    invented = json.dumps(
        [
            {
                "candidate_ref": "momentum:GME",  # not a provided candidate
                "headline": "YOLO GME",
                "rationale": "One. Two. Three.",
                "confidence": 0.9,
                "confidence_basis": "vibes",
                "evidence_ids": [],
                "worst_case": "loss",
                "falsifier": "none",
                "reversibility": "high",
            }
        ]
    )
    llm = FakeLLM(scripted=[invented, invented, invented])
    with pytest.raises(LLMError, match="invalid output"):
        run(session, setup, llm)
    # run marked failed
    assert session.scalar(select(AgentRun)).status is AgentRunStatus.failed


def test_risk_gate_runs_after_llm_and_blocks(session, setup) -> None:
    user, account = setup
    # Oversized crypto position → rebalance SELL candidate (sells are sized regardless of the
    # weekly cap), then max_trades_per_week=0 makes the post-LLM risk gate veto it.
    from alphadash.db.models import AssetClass, Position

    session.add(
        Position(
            account_id=account.id,
            symbol="BTCUSD",
            asset_class=AssetClass.crypto,
            quantity=D("0.05"),
            avg_cost=D("60000"),
        )
    )
    profile = session.scalar(select(RiskProfile).where(RiskProfile.user_id == user.id))
    profile.max_trades_per_week = 0
    session.commit()

    result = run(session, setup)
    blocked = [s for s in result.suggestions if s.status is SuggestionStatus.blocked]
    assert blocked, "expected at least one veto-blocked suggestion"
    assert all("week" in s.blocked_reason for s in blocked)
    veto = session.scalars(
        select(RiskEvent).where(RiskEvent.event_type == RiskEventType.veto)
    ).all()
    assert {v.suggestion_id for v in veto} >= {s.id for s in blocked}


def test_view_matches_frozen_s04_contract(session, setup) -> None:
    result = run(session, setup)
    view = suggestion_to_view(result.suggestions[0])

    required = {
        "id",
        "headline",
        "rationale",
        "confidence",
        "confidenceBasis",
        "evidence",
        "proposedOrder",
        "worstCase",
        "falsifier",
        "reversibility",
        "status",
    }
    assert required <= set(view)
    order = view["proposedOrder"]
    assert isinstance(order["qty"], str) and isinstance(order["cashImpact"], str)
    assert isinstance(order["allocationAfterPct"], (int, float))
    assert order["side"] in ("buy", "sell") and order["orderType"] in ("market", "limit")
    assert 0 <= view["confidence"] <= 1
    # evidence carries provenance and includes deterministic signal features (faithfulness)
    assert view["evidence"], "evidence must not be empty"
    assert any(e["source"].startswith("signal:") for e in view["evidence"])
    for e in view["evidence"]:
        assert e["claim"] and e["source"] and e["asOf"]
    if view["status"] == "blocked":
        assert view["blockedReason"]


def test_untrusted_evidence_cannot_steer_prompt_structure(session, setup) -> None:
    llm = FakeLLM()
    run(session, setup, llm)
    prompt = llm.calls[-1].messages[0]["content"]
    assert "untrusted third-party text" in prompt
    system = llm.calls[-1].system
    assert "never instructions" in system or "never" in system.lower()
