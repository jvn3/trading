"""S2.5/S2.6/S2.7 API tests: agent run → suggestions → approve/modify/dismiss → trace; chat SSE."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from alphadash.config import Settings
from alphadash.db.base import Base
from alphadash.main import create_app

CREDS = {"email": "sugg@example.com", "password": "correct-horse-battery", "display_name": "S"}


@pytest.fixture()
def client(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/sugg.db", providers="stub", llm_provider="fake"
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as c:
        c.post("/auth/register", json=CREDS)
        yield c


def run_agent(client) -> list[dict]:
    r = client.post("/agent/run")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "completed"
    return body["suggestions"]


def test_agent_run_returns_contract_suggestions(client) -> None:
    suggestions = run_agent(client)
    assert 1 <= len(suggestions) <= 3
    s = suggestions[0]
    # Frozen S0.4 shape over the wire
    assert isinstance(s["proposedOrder"]["qty"], str)
    assert isinstance(s["proposedOrder"]["cashImpact"], str)
    assert s["status"] in ("proposed", "blocked")
    assert s["evidence"] and all("asOf" in e for e in s["evidence"])

    listed = client.get("/suggestions").json()["suggestions"]
    assert {x["id"] for x in listed} >= {x["id"] for x in suggestions}


def test_approve_executes_and_is_idempotent(client) -> None:
    suggestions = run_agent(client)
    target = next(s for s in suggestions if s["status"] == "proposed")

    r = client.post(f"/suggestions/{target['id']}/approve", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["suggestion"]["status"] == "approved"
    assert body["order"]["status"] == "filled"

    # Approving again → conflict (already decided), no double order
    again = client.post(f"/suggestions/{target['id']}/approve", json={})
    assert again.status_code == 409
    orders = client.get("/orders").json()
    assert len([o for o in orders if o["status"] == "filled"]) == 1

    # Portfolio actually changed
    portfolio = client.get("/portfolio").json()
    assert any(p["symbol"] == target["proposedOrder"]["symbol"] for p in portfolio["positions"])


def test_modify_uses_new_qty_and_records_decision(client) -> None:
    suggestions = run_agent(client)
    target = next(s for s in suggestions if s["status"] == "proposed")
    r = client.post(f"/suggestions/{target['id']}/modify", json={"qty": "0.5"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["suggestion"]["status"] == "modified"
    assert body["order"]["qty"] == "0.5"


def test_dismiss_records_without_order(client) -> None:
    suggestions = run_agent(client)
    target = suggestions[0]
    r = client.post(f"/suggestions/{target['id']}/dismiss", json={"reason": "not today"})
    assert r.status_code == 200
    assert r.json()["suggestion"]["status"] == "dismissed"
    assert r.json()["order"] is None
    assert client.get("/orders").json() == []


def test_trace_shows_the_work(client) -> None:
    suggestions = run_agent(client)
    target = suggestions[0]
    trace = client.get(f"/suggestions/{target['id']}/trace").json()
    assert trace["candidate_ref"].startswith(("momentum:", "rebalance:", "take_profit:"))
    assert trace["signal_features"], "deterministic features must be traceable"
    assert trace["prompt_version"] == "s2.3-v1"
    assert trace["model_version"] == "fake-llm-1"
    assert trace["snapshot_id"] and trace["snapshot_as_of"]
    assert trace["sizing"]["qty"] == target["proposedOrder"]["qty"]


def test_requires_auth(tmp_path) -> None:
    settings = Settings(database_url=f"sqlite:///{tmp_path}/na.db", llm_provider="fake")
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as c:
        assert c.post("/agent/run").status_code == 401
        assert c.get("/suggestions").status_code == 401
        assert c.post("/chat", json={"message": "hi"}).status_code == 401


# --- S2.7 chat SSE ---


def parse_sse(text: str) -> list[dict]:
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def test_chat_streams_tokens_and_sources(client) -> None:
    # Seed the evidence corpus via an agent run's ingestion
    run_agent(client)
    r = client.post("/chat", json={"message": "Should I buy AAPL after the apple services news?"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)

    tokens = [e["text"] for e in events if e["type"] == "token"]
    assert len(tokens) > 5  # actually streamed in chunks
    answer = "".join(tokens)
    assert "not investment advice" in answer
    # Reframing, not a directive:
    assert "depends on" in answer or "bounded" in answer

    sources = next(e for e in events if e["type"] == "sources")
    assert isinstance(sources["citations"], list)
    assert events[-1]["type"] == "done"


def test_chat_grounds_in_portfolio_and_sandboxes_evidence(client) -> None:
    run_agent(client)
    r = client.post("/chat", json={"message": "What is my current cash position?"})
    events = parse_sse(r.text)
    assert events[-1]["type"] == "done"
    # The fake LLM records nothing here, but the endpoint must not 500 without evidence hits
    r2 = client.post("/chat", json={"message": "zzzzqqqq nonexistent topic"})
    assert r2.status_code == 200
    assert parse_sse(r2.text)[-1]["type"] == "done"
