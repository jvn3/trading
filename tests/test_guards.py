"""Tests for :mod:`jay_trading.risk.guards`."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pytest

from jay_trading.data import store
from jay_trading.data.db import create_all
from jay_trading.risk import api_health, guards
from jay_trading.strategies.base import PortfolioSnapshot, PositionView, TradeIntent


# -- Fakes ------------------------------------------------------------------


@dataclass
class _FakeAccount:
    equity: float
    last_equity: float
    cash: float


class _FakeAlpaca:
    def __init__(self, equity: float = 10_000.0, last_equity: float | None = None,
                 cash: float | None = None) -> None:
        self._acct = _FakeAccount(
            equity=equity,
            last_equity=last_equity if last_equity is not None else equity,
            cash=cash if cash is not None else equity,
        )

    def get_account(self) -> Any:
        return self._acct


class _FakeFMP:
    """Minimal stub that returns canned responses by endpoint key."""

    def __init__(self, *, spy_price: float = 500.0, spy_ma200: float = 480.0,
                 profile_sector: str | None = "Technology") -> None:
        self.spy_price = spy_price
        self.spy_ma200 = spy_ma200
        self.profile_sector = profile_sector

    def request(self, endpoint_key: str, params: dict[str, Any] | None = None,
                **_: Any) -> Any:
        if endpoint_key == "quote":
            return [{"symbol": params["symbol"], "price": self.spy_price,
                     "priceAvg200": self.spy_ma200}]
        if endpoint_key == "profile":
            return [{"symbol": params["symbol"], "sector": self.profile_sector,
                     "industry": "Software", "marketCap": 1.0e12}]
        raise KeyError(endpoint_key)


def _snapshot(equity: float = 10_000.0, positions: list[PositionView] | None = None) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        equity=equity, cash=equity, buying_power=equity * 2,
        positions=positions or [],
        taken_at=datetime.now(timezone.utc),
    )


def _intent(ticker: str = "MSFT", action: str = "open", notional: float = 500) -> TradeIntent:
    return TradeIntent(
        strategy_name="smart_copy", ticker=ticker, side="buy",
        notional=notional, action=action,
    )


@pytest.fixture(autouse=True)
def _fresh_cache() -> Any:
    """Reset the api_health TTL cache between tests (market-regime cached there)."""
    api_health.cache().clear()
    yield
    api_health.cache().clear()


# -- Daily loss breaker ----------------------------------------------------


def test_daily_loss_passes_on_small_move() -> None:
    create_all()
    res = guards.check_daily_loss(alpaca=_FakeAlpaca(equity=9_950.0, last_equity=10_000.0))
    assert res.passed is True  # -0.5% doesn't breach -2%


def test_daily_loss_trips_past_threshold() -> None:
    create_all()
    res = guards.check_daily_loss(alpaca=_FakeAlpaca(equity=9_700.0, last_equity=10_000.0))
    assert res.passed is False
    assert "daily DD" in res.reason
    assert res.details["change"] == pytest.approx(-0.03)


# -- Drawdown breaker ------------------------------------------------------


def test_drawdown_trips_past_hwm_threshold() -> None:
    create_all()
    # Seed HWM at 10k.
    store.record_equity_snapshot(equity=10_000.0, cash=10_000.0)
    res = guards.check_drawdown(alpaca=_FakeAlpaca(equity=9_400.0))  # -6%
    assert res.passed is False
    assert "HWM" in res.reason


def test_drawdown_passes_when_at_hwm() -> None:
    create_all()
    store.record_equity_snapshot(equity=10_000.0, cash=10_000.0)
    res = guards.check_drawdown(alpaca=_FakeAlpaca(equity=10_100.0))  # new high
    assert res.passed is True


# -- API health breaker ----------------------------------------------------


def test_api_health_passes_with_insufficient_data() -> None:
    create_all()
    for _ in range(5):  # below MIN_CALLS
        store.record_api_call("fmp", "/x", "fail", 100.0, "http_500")
    res = guards.check_api_health()
    assert res.passed is True  # not enough data to trip


def test_api_health_trips_on_high_fail_rate() -> None:
    create_all()
    # 6 fails + 4 oks = 60% fail rate, 10 total — tripping.
    for _ in range(6):
        store.record_api_call("fmp", "/x", "fail", 100.0, "http_500")
    for _ in range(4):
        store.record_api_call("fmp", "/x", "ok", 80.0)
    res = guards.check_api_health()
    assert res.passed is False
    assert "fmp" in res.reason
    assert res.details["fails"] == 6


# -- Market regime gate ----------------------------------------------------


def test_market_regime_passes_when_spy_above_ma200() -> None:
    create_all()
    res = guards.check_market_regime(fmp=_FakeFMP(spy_price=500.0, spy_ma200=480.0))
    assert res.passed is True


def test_market_regime_trips_when_spy_below_ma200() -> None:
    create_all()
    res = guards.check_market_regime(fmp=_FakeFMP(spy_price=470.0, spy_ma200=480.0))
    assert res.passed is False
    assert "SPY" in res.reason


def test_market_regime_is_cached_between_calls() -> None:
    create_all()
    fmp = _FakeFMP(spy_price=500.0, spy_ma200=480.0)
    guards.check_market_regime(fmp=fmp)
    # Mutate the fake to simulate a changed market; cache should hide the change.
    fmp.spy_price = 400.0
    res = guards.check_market_regime(fmp=fmp)
    assert res.passed is True  # returned cached result


# -- Sector correlation cap ------------------------------------------------


def test_correlation_cap_passes_below_cap() -> None:
    create_all()
    store.upsert_ticker_profile("MSFT", sector="Technology")
    store.upsert_ticker_profile("NVDA", sector="Technology")
    # No positions yet → cap=3, count=0, pass.
    res = guards.check_correlation_cap(_intent("NVDA"), _snapshot(), fmp=_FakeFMP())
    assert res.passed is True


def test_correlation_cap_trips_at_cap() -> None:
    from jay_trading.data import models
    from jay_trading.data.db import session_scope

    create_all()
    # 3 existing tech positions → intent on a 4th should be vetoed.
    with session_scope() as s:
        for sym in ("MSFT", "NVDA", "GOOG"):
            s.add(models.Position(ticker=sym, strategy_name="smart_copy",
                                   qty=1.0, avg_entry_price=100.0))
    for sym in ("MSFT", "NVDA", "GOOG", "AMD"):
        store.upsert_ticker_profile(sym, sector="Technology")

    res = guards.check_correlation_cap(_intent("AMD"), _snapshot(), fmp=_FakeFMP())
    assert res.passed is False
    assert "Technology" in res.reason


def test_correlation_cap_passes_close_intents() -> None:
    create_all()
    res = guards.check_correlation_cap(_intent("AMD", action="close"), _snapshot(), fmp=_FakeFMP())
    assert res.passed is True


def test_correlation_cap_fails_open_when_sector_unknown() -> None:
    create_all()
    fmp = _FakeFMP(profile_sector=None)  # FMP returns null sector
    res = guards.check_correlation_cap(_intent("XYZ"), _snapshot(), fmp=fmp)
    assert res.passed is True  # fail-open, not fail-closed


# -- Orchestration ---------------------------------------------------------


def test_evaluate_pipeline_gates_collects_all_trips() -> None:
    create_all()
    # Seed conditions for both daily-loss AND drawdown to trip.
    store.record_equity_snapshot(equity=10_000.0, cash=10_000.0)
    alpaca = _FakeAlpaca(equity=9_400.0, last_equity=10_000.0)  # -6% both ways
    fmp = _FakeFMP(spy_price=500.0, spy_ma200=480.0)

    dec = guards.evaluate_pipeline_gates(alpaca=alpaca, fmp=fmp, portfolio=_snapshot())
    assert dec.allow_entries is False
    trip_names = [n for n, _ in dec.trips]
    assert "daily_loss" in trip_names
    assert "drawdown" in trip_names


def test_evaluate_pipeline_gates_allows_on_all_pass() -> None:
    create_all()
    alpaca = _FakeAlpaca(equity=10_000.0)
    fmp = _FakeFMP(spy_price=500.0, spy_ma200=480.0)
    dec = guards.evaluate_pipeline_gates(alpaca=alpaca, fmp=fmp, portfolio=_snapshot())
    assert dec.allow_entries is True
    assert dec.trips == []
