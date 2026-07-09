"""S0.1 acceptance: the app boots and /health reports the paper-only invariant."""

from fastapi.testclient import TestClient

from alphadash import __version__
from alphadash.config import Settings
from alphadash.main import create_app


def _client() -> TestClient:
    # Hermetic settings — no dependence on the ambient environment or a local .env file.
    return TestClient(create_app(Settings(trading_mode="paper")))


def test_health_ok() -> None:
    resp = _client().get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__


def test_health_reports_paper_mode() -> None:
    # Guards the hard invariant: the scaffold must never default to real-money trading.
    body = _client().get("/health").json()
    assert body["trading_mode"] == "paper"
