"""S1.7 tests: snapshot math vs hand-computed fixtures; performance with benchmark + drawdown."""

from __future__ import annotations

from datetime import UTC, date, datetime
from datetime import time as dt_time
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from alphadash.db.models import AssetClass, OrderSide, OrderType
from alphadash.domain.risk import RiskLimitSet
from alphadash.providers.dto import Bar, Provenance
from alphadash.services.execution import place_order
from alphadash.services.portfolio import performance_series, portfolio_snapshot
from tests.factories import funded_account, make_engine

D = Decimal
T0 = datetime(2026, 7, 6, 15, 0, tzinfo=UTC)  # Monday


@pytest.fixture()
def session():
    with Session(make_engine()) as s:
        yield s


def trade(
    session,
    account,
    *,
    symbol="AAPL",
    asset_class=AssetClass.equity,
    side=OrderSide.buy,
    qty="10",
    price="100",
    key="k",
    now=T0,
):
    return place_order(
        session,
        account=account,
        symbol=symbol,
        asset_class=asset_class,
        side=side,
        order_type=OrderType.market,
        qty=D(qty),
        quote_price=D(price),
        limits=RiskLimitSet(),
        idempotency_key=key,
        now=now,
    )


class FakeBars:
    """MarketDataProvider stand-in: fixed closes per symbol per day."""

    def __init__(self, closes: dict[str, dict[str, str]]):
        self._closes = closes

    def get_quote(self, symbol):  # pragma: no cover - unused
        raise NotImplementedError

    def get_bars(self, symbol, timeframe, start, end):
        out = []
        for day_iso, close in self._closes.get(symbol, {}).items():
            day = date.fromisoformat(day_iso)
            if start.date() <= day <= end.date():
                ts = datetime.combine(day, dt_time(0, 0), tzinfo=UTC)
                out.append(
                    Bar(
                        symbol=symbol,
                        timeframe="1D",
                        open=D(close),
                        high=D(close),
                        low=D(close),
                        close=D(close),
                        volume=D("1"),
                        ts=ts,
                        provenance=Provenance(source="fake", as_of=ts),
                    )
                )
        return sorted(out, key=lambda b: b.ts)


def test_snapshot_hand_computed(session) -> None:
    account = funded_account(session)  # 10000 cash
    trade(session, account, key="b1")  # buy 10 AAPL @100 → fills 100.05, cash 8999.50
    trade(
        session,
        account,
        symbol="BTCUSD",
        asset_class=AssetClass.crypto,
        qty="0.02",
        price="50000",
        key="b2",
    )  # fills 50025 → cost 1000.50, cash 7999.00
    session.commit()

    snap = portfolio_snapshot(session, account, prices={"AAPL": D("110"), "BTCUSD": D("52000")})

    assert snap.cash == D("7999.00")
    # AAPL: 10 × 110 = 1100; BTC: 0.02 × 52000 = 1040; equity = 7999 + 2140 = 10139
    assert snap.equity == D("10139.00")
    aapl = next(p for p in snap.positions if p.symbol == "AAPL")
    assert aapl.market_value == D("1100")
    assert aapl.unrealized_pl == D("1100") - D("10") * D("100.05")
    assert snap.allocation_pct["equity"] == (D("1100") / D("10139") * 100).quantize(D("0.01"))
    assert snap.allocation_pct["crypto"] == (D("1040") / D("10139") * 100).quantize(D("0.01"))
    assert snap.allocation_pct["cash"] == (D("7999") / D("10139") * 100).quantize(D("0.01"))
    assert sum(snap.allocation_pct.values()) == pytest.approx(D("100"), abs=D("0.03"))


def test_missing_price_falls_back_to_avg_cost(session) -> None:
    account = funded_account(session)
    trade(session, account, key="b1")
    snap = portfolio_snapshot(session, account, prices={})
    aapl = snap.positions[0]
    assert aapl.market_value == D("10") * D("100.05")
    assert aapl.unrealized_pl == D("0")


def test_performance_with_benchmark_and_drawdown(session) -> None:
    account = funded_account(session)  # starting equity 10000
    trade(session, account, key="b1", now=T0)  # Mon: 10 AAPL, cash 8999.50
    session.commit()

    bars = FakeBars(
        {
            "AAPL": {"2026-07-06": "100", "2026-07-07": "90", "2026-07-08": "120"},
            "SPY": {"2026-07-06": "500", "2026-07-07": "505", "2026-07-08": "510"},
        }
    )
    report = performance_series(
        session, account, bars, start=date(2026, 7, 6), end=date(2026, 7, 8)
    )

    # Equity: Mon 8999.50+1000=9999.50 · Tue 8999.50+900=9899.50 · Wed 8999.50+1200=10199.50
    assert [p.equity for p in report.points] == [D("9999.50"), D("9899.50"), D("10199.50")]
    # Benchmark: 10000 × 500/500, ×505/500, ×510/500
    assert [p.benchmark_equity for p in report.points] == [D("10000"), D("10100"), D("10200")]
    assert report.return_pct == D("2.00")  # 10199.50/10000
    assert report.benchmark_return_pct == D("2.00")
    # Max drawdown: peak 9999.50 → trough 9899.50 = 1.0001%
    assert report.max_drawdown_pct == D("1.00")
    assert report.current_drawdown_pct == D("0.00")  # ends at new peak
    assert report.benchmark_symbol == "SPY"


def test_performance_skips_missing_bar_days_no_interpolation(session) -> None:
    account = funded_account(session)
    trade(session, account, key="b1", now=T0)
    session.commit()

    bars = FakeBars(
        {
            "AAPL": {"2026-07-06": "100", "2026-07-08": "120"},  # no Tue bar
            "SPY": {"2026-07-06": "500", "2026-07-08": "510"},
        }
    )
    report = performance_series(
        session, account, bars, start=date(2026, 7, 6), end=date(2026, 7, 8)
    )
    # Tuesday emitted using Monday's carried-forward close (lookback), not dropped:
    assert [p.day.isoformat() for p in report.points] == ["2026-07-06", "2026-07-07", "2026-07-08"]
    assert report.points[1].equity == report.points[0].equity  # carried close, honest flat


def test_empty_history_returns_zeroes(session) -> None:
    account = funded_account(session)
    report = performance_series(
        session, account, FakeBars({}), start=date(2026, 7, 6), end=date(2026, 7, 8)
    )
    assert report.points == () and report.return_pct == 0
