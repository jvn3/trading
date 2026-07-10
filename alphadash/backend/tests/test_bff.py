"""S1.9 tests: BFF endpoints end-to-end (register → trade → portfolio → performance),
plus the OpenAPI contract (money = string)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from alphadash.config import Settings
from alphadash.db.base import Base
from alphadash.main import create_app

CREDS = {"email": "bff@example.com", "password": "correct-horse-battery", "display_name": "BFF"}


@pytest.fixture()
def client(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path}/bff.db", providers="stub")
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as c:
        c.post("/auth/register", json=CREDS)
        yield c


def order_payload(**kw):
    payload = {
        "symbol": "AAPL",
        "asset_class": "equity",
        "side": "buy",
        "order_type": "market",
        "qty": "2",
    }
    payload.update(kw)
    return payload


def place(client, key="key-00000001", **kw):
    return client.post("/orders", json=order_payload(**kw), headers={"Idempotency-Key": key})


def test_endpoints_require_auth(tmp_path) -> None:
    settings = Settings(database_url=f"sqlite:///{tmp_path}/noauth.db", providers="stub")
    app = create_app(settings)
    Base.metadata.create_all(app.state.engine)
    with TestClient(app) as c:
        for path in ("/account", "/portfolio", "/portfolio/performance", "/orders"):
            assert c.get(path).status_code == 401, path


def test_account_reports_paper_mode_and_limits(client) -> None:
    account = client.get("/account").json()
    assert account["mode"] == "paper" and account["trading_mode"] == "paper"
    assert account["starting_equity"] == "10000.00000000"
    assert account["paused"] is False

    limits = client.get("/account/limits").json()
    assert limits["per_suggestion_max_pct"] == "5"  # S3.7: human-normalized, no Numeric(24,8) noise
    assert limits["max_asset_class_pct"]["crypto"] == "10"
    assert limits["max_trades_per_week"] == 5


def test_order_to_portfolio_flow(client) -> None:
    r = place(client)  # buy 2 AAPL, stub quote 210.50 → fill 210.61 (5bps, rounded)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["order"]["status"] == "filled"
    assert body["order"]["fill"]["price"] == "210.61"
    assert body["violations"] == []

    # Idempotent replay: same key returns the same order, no double fill
    again = place(client)
    assert again.json()["replayed"] is True
    assert again.json()["order"]["id"] == body["order"]["id"]

    portfolio = client.get("/portfolio").json()
    assert [p["symbol"] for p in portfolio["positions"]] == ["AAPL"]
    assert portfolio["positions"][0]["quantity"] == "2.00000000"
    assert isinstance(portfolio["equity"], str)  # Decimal-as-string contract

    orders = client.get("/orders").json()
    assert len(orders) == 1 and orders[0]["fill"] is not None


def test_risk_veto_surfaces_violations(client) -> None:
    r = place(client, key="veto-0000001", qty="10")  # 10 × 210.5 ≈ 21% > 5% per-trade cap
    assert r.status_code == 201
    body = r.json()
    assert body["order"]["status"] == "rejected"
    assert any(v["limit_type"] == "per_suggestion_max_pct" for v in body["violations"])
    assert client.get("/portfolio").json()["positions"] == []


def test_pause_blocks_buys_resume_unblocks(client) -> None:
    assert client.post("/account/pause").json()["paused"] is True
    r = place(client, key="paused-000001")
    assert r.json()["order"]["status"] == "rejected"
    assert "paused" in r.json()["order"]["rejected_reason"]

    assert client.post("/account/resume").json()["paused"] is False
    r2 = place(client, key="resumed-00001")
    assert r2.json()["order"]["status"] == "filled"


def test_performance_includes_benchmark_and_drawdown(client) -> None:
    place(client)
    perf = client.get("/portfolio/performance?days=30").json()
    assert perf["benchmark_symbol"] == "SPY"
    assert {
        "return_pct",
        "benchmark_return_pct",
        "max_drawdown_pct",
        "current_drawdown_pct",
    } <= set(perf)
    assert perf["points"], "stub bars should produce a curve"
    assert isinstance(perf["points"][0]["equity"], str)


def test_quote_endpoint_carries_provenance(client) -> None:
    q = client.get("/quotes/aapl").json()
    assert q == {
        "symbol": "AAPL",
        "price": "210.50",
        "as_of": "2026-07-01T14:30:00+00:00",
        "source": "stub",
        "is_stale": False,
    }


def test_openapi_contract_money_is_string(client) -> None:
    spec = client.get("/openapi.json").json()
    schemas = spec["components"]["schemas"]
    # The wire contract the frontend types are generated from:
    assert schemas["PortfolioOut"]["properties"]["equity"]["type"] == "string"
    assert schemas["PositionOut"]["properties"]["quantity"]["type"] == "string"
    assert schemas["OrderOut"]["properties"]["qty"]["type"] == "string"
    assert schemas["FillOut"]["properties"]["price"]["type"] == "string"
    for path in ("/portfolio", "/orders", "/account", "/portfolio/performance"):
        assert path in spec["paths"]
