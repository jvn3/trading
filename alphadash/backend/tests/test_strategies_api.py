"""S4.2/S4.3 API tests: draft → backtest → activate → agent candidates; what-if endpoints."""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from alphadash.config import Settings
from alphadash.db.base import Base
from alphadash.main import create_app

CREDS = {"email": "lab@example.com", "password": "correct-horse-battery", "display_name": "Lab"}


@pytest.fixture()
def client(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/lab.db", providers="stub", llm_provider="fake"
    )
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as c:
        c.post("/auth/register", json=CREDS)
        yield c


def draft(
    client, text="Buy AAPL when price is above its 20 day average, sell at 10% profit or 5% loss"
):
    r = client.post("/strategies/draft", json={"text": text})
    assert r.status_code == 201, r.text
    return r.json()


# --- S4.2 lifecycle ---


def test_draft_compiles_text_into_described_rules(client) -> None:
    body = draft(client)
    assert body["status"] == "draft"
    assert body["params"]["symbol"] == "AAPL"
    assert body["params"]["entry"]["kind"] == "price_above_sma"
    assert body["params"]["entry"]["window"] == 20
    assert body["params"]["take_profit_pct"] == "10"
    assert body["params"]["stop_loss_pct"] == "5"
    # Faithfulness: plain-language description of what the CODE will do
    assert "Buy AAPL" in body["description"]
    assert "20-day average" in body["description"]
    assert "safety limits" in body["description"]
    assert body["last_backtest"] is None

    listed = client.get("/strategies").json()
    assert [s["id"] for s in listed] == [body["id"]]


def test_cannot_activate_without_backtest(client) -> None:
    body = draft(client)
    r = client.post(f"/strategies/{body['id']}/activate")
    assert r.status_code == 409
    assert "backtest" in r.json()["detail"]


def test_backtest_then_activate_then_archive(client) -> None:
    body = draft(client)
    bt = client.post(f"/strategies/{body['id']}/backtest")
    assert bt.status_code == 200, bt.text
    results = bt.json()
    # Honesty invariants: windows + buy-and-hold + benchmark + caveats always present
    assert len(results["windows"]) >= 1
    assert all("buy_hold_return_pct" in w for w in results["windows"])
    assert "benchmark_return_pct" in results
    assert results["caveats"], "caveats are part of the payload, not optional decoration"
    assert any("does not predict" in c for c in results["caveats"])

    active = client.post(f"/strategies/{body['id']}/activate")
    assert active.status_code == 200
    assert active.json()["status"] == "active"
    assert active.json()["last_backtest"] is not None

    archived = client.post(f"/strategies/{body['id']}/archive")
    assert archived.json()["status"] == "archived"
    assert client.get("/strategies").json() == []  # archived hidden from the list


def test_draft_validation_errors_are_422(client) -> None:
    assert client.post("/strategies/draft", json={"text": "hi"}).status_code == 422
    assert client.post("/strategies/zzz/backtest").status_code == 404


def test_active_strategy_feeds_agent_suggestions(client) -> None:
    """The S4.2 loop closed: authored strategy → agent candidate → normal approve pipeline."""
    body = draft(client, "Buy MSFT when price is above its 5 day average, sell at 8% profit")
    client.post(f"/strategies/{body['id']}/backtest")
    client.post(f"/strategies/{body['id']}/activate")

    run = client.post("/agent/run").json()
    assert run["status"] == "completed"
    strategy_suggestions = [
        s
        for s in run["suggestions"]
        if client.get(f"/suggestions/{s['id']}/trace")
        .json()["candidate_ref"]
        .startswith("user_strategy:")
    ]
    # Stub bars drift upward, so price sits above its 5-day average → the strategy fires.
    assert strategy_suggestions, "active strategy should produce a suggestion on rising stub data"
    target = strategy_suggestions[0]
    assert target["proposedOrder"]["symbol"] == "MSFT"
    assert target["proposedOrder"]["side"] == "buy"

    # Approving executes through the same risk-gated paper engine
    if target["status"] == "proposed":
        approved = client.post(f"/suggestions/{target['id']}/approve", json={})
        assert approved.status_code == 200
        assert approved.json()["order"]["status"] in ("filled", "rejected")


def test_paused_account_gets_no_strategy_buy_candidates(client) -> None:
    body = draft(client, "Buy MSFT when price is above its 5 day average, sell at 8% profit")
    client.post(f"/strategies/{body['id']}/backtest")
    client.post(f"/strategies/{body['id']}/activate")
    client.post("/account/pause")

    run = client.post("/agent/run").json()
    assert all(s["proposedOrder"]["side"] != "buy" for s in run["suggestions"])


def test_strategies_require_auth(tmp_path) -> None:
    settings = Settings(database_url=f"sqlite:///{tmp_path}/na.db", llm_provider="fake")
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as c:
        assert c.get("/strategies").status_code == 401
        assert c.post("/strategies/draft", json={"text": "buy the dip"}).status_code == 401
        assert c.post("/whatif/shock", json={}).status_code == 401
        assert (
            c.post(
                "/whatif/trade",
                json={"symbol": "AAPL", "asset_class": "equity", "side": "buy", "qty": "1"},
            ).status_code
            == 401
        )


# --- S4.3 what-if ---


def test_shock_on_real_positions(client) -> None:
    # Build a position first: buy 2 AAPL at stub 210.50 (fills 210.61)
    r = client.post(
        "/orders",
        json={
            "symbol": "AAPL",
            "asset_class": "equity",
            "side": "buy",
            "order_type": "market",
            "qty": "2",
        },
        headers={"Idempotency-Key": "whatif-setup-1"},
    )
    assert r.json()["order"]["status"] == "filled"

    impact = client.post("/whatif/shock", json={"equity_pct": "-50"}).json()
    assert Decimal(impact["equity_before"]) > 0
    aapl = next(p for p in impact["positions"] if p["symbol"] == "AAPL")
    assert Decimal(aapl["value_after"]) == (Decimal(aapl["value_before"]) / 2).quantize(
        Decimal("0.01")
    )
    # Portfolio barely moves (position is ~4% of the book) → no pause trip
    assert impact["would_trip_drawdown_pause"] is False
    assert Decimal(impact["equity_change_pct"]) < 0

    bad = client.post("/whatif/shock", json={"equity_pct": "-99"})
    assert bad.status_code == 422


def test_trade_preview_agrees_with_order_endpoint(client) -> None:
    # A 10-share AAPL buy (~2105) breaches the 5% per-trade cap on a 10k account.
    preview = client.post(
        "/whatif/trade",
        json={"symbol": "AAPL", "asset_class": "equity", "side": "buy", "qty": "10"},
    ).json()
    assert preview["allowed"] is False
    assert any(v["limit_type"] == "per_suggestion_max_pct" for v in preview["violations"])

    # The real order path must reach the same verdict
    order = client.post(
        "/orders",
        json={
            "symbol": "AAPL",
            "asset_class": "equity",
            "side": "buy",
            "order_type": "market",
            "qty": "10",
        },
        headers={"Idempotency-Key": "parity-check-1"},
    ).json()
    assert order["order"]["status"] == "rejected"
    assert {v["limit_type"] for v in order["violations"]} == {
        v["limit_type"] for v in preview["violations"]
    }

    # And nothing was placed by the preview itself
    assert client.get("/orders").json()[0]["status"] == "rejected"  # only the parity order exists
    assert len(client.get("/orders").json()) == 1


def test_trade_preview_allowed_path_shows_shape(client) -> None:
    preview = client.post(
        "/whatif/trade",
        json={"symbol": "AAPL", "asset_class": "equity", "side": "buy", "qty": "1"},
    ).json()
    assert preview["allowed"] is True
    assert preview["violations"] == []
    assert Decimal(preview["cash_after"]) < Decimal("10000")
    assert preview["position_allocation_after_pct"] > 0
