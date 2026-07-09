"""morning_check: settlement-tolerant position/performance checks.

Pins the 2026-07-07 fix — a mid-fill snapshot must not raise a spurious WARN,
and equity read while orders are still settling must be flagged transient
rather than reported as a real drawdown.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from jay_trading.data import models
from jay_trading.data.db import create_all, session_scope
from scripts import morning_check as mc


def _pos(symbol: str) -> SimpleNamespace:
    return SimpleNamespace(symbol=symbol)


def _open_db_position(ticker: str) -> None:
    with session_scope() as s:
        s.add(
            models.Position(
                ticker=ticker,
                strategy_name="smart_copy",
                qty=1.0,
                avg_entry_price=100.0,
                opened_at=datetime.now(timezone.utc),
            )
        )


class _Alpaca:
    def __init__(self, positions=None, account=None, orders=None) -> None:
        self._positions = positions or []
        self._account = account
        self._orders = orders or []

    def get_positions(self):
        return self._positions

    def get_account(self):
        return self._account

    def get_orders(self, status: str = "all", after: str | None = None):
        if status == "open":
            return [o for o in self._orders if getattr(o, "status", "") == "open"]
        return self._orders


def test_positions_mismatch_explained_by_in_flight_is_pass() -> None:
    create_all()
    _open_db_position("GOOGL")  # db_open = {GOOGL}
    # AXP + TQQQ are live-only, but both have orders in flight → mid-settlement.
    alpaca = _Alpaca(positions=[_pos("GOOGL"), _pos("AXP"), _pos("TQQQ")])
    status, detail = mc.check_positions_reconciled(alpaca, {"AXP", "TQQQ"})
    assert status == mc.PASS
    assert "mid-settlement" in detail


def test_positions_unexplained_drift_warns() -> None:
    create_all()
    _open_db_position("GOOGL")
    alpaca = _Alpaca(positions=[_pos("GOOGL"), _pos("AXP")])
    status, detail = mc.check_positions_reconciled(alpaca, set())  # nothing settling
    assert status == mc.WARN
    assert "AXP" in detail


def test_positions_exact_match_is_pass() -> None:
    create_all()
    _open_db_position("GOOGL")
    alpaca = _Alpaca(positions=[_pos("GOOGL")])
    status, _ = mc.check_positions_reconciled(alpaca, set())
    assert status == mc.PASS


def test_performance_flags_transient_equity_while_settling() -> None:
    # The 2026-07-07 numbers: a transient $5,490 read mid-fill.
    acct = SimpleNamespace(equity="5490.18", cash="5185.07", last_equity="10343.76")
    alpaca = _Alpaca(account=acct)
    status, detail = mc.check_performance(alpaca, {"AXP", "TQQQ"})
    assert status == mc.PASS
    assert "transient" in detail
    assert "10,343.76" in detail  # last settled close shown as the anchor


def test_performance_clean_when_settled() -> None:
    acct = SimpleNamespace(equity="10308.36", cash="5185.07", last_equity="10343.76")
    alpaca = _Alpaca(account=acct)
    status, detail = mc.check_performance(alpaca, set())
    assert status == mc.PASS
    assert "transient" not in detail


def test_in_flight_symbols_collects_open_and_recent_fills() -> None:
    now = datetime.now(timezone.utc)
    orders = [
        SimpleNamespace(symbol="AXP", status="open", filled_at=None),
        SimpleNamespace(symbol="TQQQ", status="filled",
                        filled_at=now - timedelta(minutes=5)),
        SimpleNamespace(symbol="OLD", status="filled",
                        filled_at=now - timedelta(hours=3)),
    ]
    alpaca = _Alpaca(orders=orders)
    syms = mc._in_flight_symbols(alpaca)
    assert syms == {"AXP", "TQQQ"}  # OLD filled outside the window → excluded
