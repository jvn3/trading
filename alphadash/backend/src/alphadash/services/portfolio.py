"""Portfolio & accounting (S1.7).

Two views, both derived from the fill history (the journaled truth) + injected prices:

- ``portfolio_snapshot``: current holdings, cash, allocation, unrealized P/L.
- ``performance_series``: daily equity curve replayed from fills and priced with EOD bars,
  ALWAYS reported next to a benchmark (default SPY) and drawdown — naked returns are
  a product no-no (§blueprint honesty rules).

No provider calls happen here except through the injected ``MarketDataProvider``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as dt_time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from alphadash.db.models import Account, CashBalance, Fill, Order, OrderSide, Position
from alphadash.providers.base import MarketDataProvider

ZERO = Decimal("0")
HUNDRED = Decimal("100")
TWO_DP = Decimal("0.01")


@dataclass(frozen=True)
class PositionView:
    symbol: str
    asset_class: str
    quantity: Decimal
    avg_cost: Decimal
    market_value: Decimal
    unrealized_pl: Decimal
    allocation_pct: Decimal


@dataclass(frozen=True)
class PortfolioSnapshot:
    equity: Decimal
    cash: Decimal
    positions: tuple[PositionView, ...]
    allocation_pct: dict[str, Decimal]  # by asset class + "cash"


@dataclass(frozen=True)
class PerformancePoint:
    day: date
    equity: Decimal
    benchmark_equity: Decimal


@dataclass(frozen=True)
class PerformanceReport:
    points: tuple[PerformancePoint, ...]
    return_pct: Decimal
    benchmark_return_pct: Decimal
    max_drawdown_pct: Decimal
    current_drawdown_pct: Decimal
    benchmark_symbol: str


def portfolio_snapshot(
    session: Session, account: Account, prices: dict[str, Decimal]
) -> PortfolioSnapshot:
    """Current holdings valued at ``prices`` (falls back to avg_cost when a price is missing)."""
    rows = session.scalars(select(Position).where(Position.account_id == account.id)).all()
    cash_row = session.scalar(
        select(CashBalance).where(
            CashBalance.account_id == account.id, CashBalance.currency == account.base_currency
        )
    )
    cash = cash_row.amount if cash_row else ZERO

    valued: list[tuple[Position, Decimal]] = []
    for p in rows:
        price = prices.get(p.symbol, p.avg_cost)
        valued.append((p, p.quantity * price))
    equity = cash + sum((mv for _, mv in valued), ZERO)

    views: list[PositionView] = []
    class_alloc: dict[str, Decimal] = {}
    for p, market_value in valued:
        alloc = (market_value / equity * HUNDRED).quantize(TWO_DP) if equity > 0 else ZERO
        views.append(
            PositionView(
                symbol=p.symbol,
                asset_class=p.asset_class.value,
                quantity=p.quantity,
                avg_cost=p.avg_cost,
                market_value=market_value,
                unrealized_pl=market_value - p.quantity * p.avg_cost,
                allocation_pct=alloc,
            )
        )
        class_alloc[p.asset_class.value] = class_alloc.get(p.asset_class.value, ZERO) + market_value

    allocation_pct = {
        cls: (mv / equity * HUNDRED).quantize(TWO_DP) if equity > 0 else ZERO
        for cls, mv in class_alloc.items()
    }
    allocation_pct["cash"] = (cash / equity * HUNDRED).quantize(TWO_DP) if equity > 0 else ZERO

    views.sort(key=lambda v: v.market_value, reverse=True)
    return PortfolioSnapshot(
        equity=equity, cash=cash, positions=tuple(views), allocation_pct=allocation_pct
    )


def _daily_closes(
    market_data: MarketDataProvider, symbol: str, start: date, end: date
) -> dict[date, Decimal]:
    bars = market_data.get_bars(
        symbol,
        "1D",
        datetime.combine(start, dt_time(0, 0), tzinfo=UTC),
        datetime.combine(end, dt_time(0, 0), tzinfo=UTC),
    )
    return {b.ts.date(): b.close for b in bars}


def _price_on(closes: dict[date, Decimal], day: date, lookback_days: int = 7) -> Decimal | None:
    """Close on ``day`` or the most recent close within ``lookback_days`` (weekends/holidays)."""
    for offset in range(lookback_days + 1):
        price = closes.get(day - timedelta(days=offset))
        if price is not None:
            return price
    return None


def performance_series(
    session: Session,
    account: Account,
    market_data: MarketDataProvider,
    *,
    start: date,
    end: date,
    benchmark_symbol: str = "SPY",
) -> PerformanceReport:
    """Daily equity curve vs benchmark, with max + current drawdown. Fills replayed in order."""
    fills = session.execute(
        select(Fill, Order)
        .join(Order, Fill.order_id == Order.id)
        .where(Order.account_id == account.id)
        .order_by(Fill.filled_at, Fill.id)
    ).all()

    symbols = sorted({order.symbol for _, order in fills})
    closes = {s: _daily_closes(market_data, s, start, end) for s in symbols}
    bench_closes = _daily_closes(market_data, benchmark_symbol, start, end)

    points: list[PerformancePoint] = []
    peak = ZERO
    max_dd = ZERO
    bench_base: Decimal | None = None

    fill_idx = 0
    cash = account.starting_equity
    qty: dict[str, Decimal] = {}

    def _as_utc(dt: datetime) -> datetime:
        # sqlite round-trips tz-aware datetimes as naive; stored values are UTC by contract.
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)

    day = start
    while day <= end:
        cutoff = datetime.combine(day, dt_time(23, 59, 59), tzinfo=UTC)
        while fill_idx < len(fills) and _as_utc(fills[fill_idx][0].filled_at) <= cutoff:
            fill, order = fills[fill_idx]
            notional = fill.qty * fill.price
            if order.side is OrderSide.buy:
                cash -= notional + fill.fee
                qty[order.symbol] = qty.get(order.symbol, ZERO) + fill.qty
            else:
                cash += notional - fill.fee
                qty[order.symbol] = qty.get(order.symbol, ZERO) - fill.qty
            fill_idx += 1

        equity = cash
        missing_price = False
        for symbol, q in qty.items():
            if q == ZERO:
                continue
            price = _price_on(closes[symbol], day)
            if price is None:
                missing_price = True
                break
            equity += q * price

        bench_price = _price_on(bench_closes, day)
        if missing_price or bench_price is None:
            day += timedelta(days=1)
            continue  # market holiday / missing bar: no point emitted, no interpolation lies

        if bench_base is None:
            bench_base = bench_price
        bench_equity = account.starting_equity * bench_price / bench_base

        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * HUNDRED)
        points.append(PerformancePoint(day=day, equity=equity, benchmark_equity=bench_equity))
        day += timedelta(days=1)

    if not points:
        return PerformanceReport(
            points=(),
            return_pct=ZERO,
            benchmark_return_pct=ZERO,
            max_drawdown_pct=ZERO,
            current_drawdown_pct=ZERO,
            benchmark_symbol=benchmark_symbol,
        )

    last = points[-1]
    return_pct = (last.equity / account.starting_equity - 1) * HUNDRED
    benchmark_return_pct = (last.benchmark_equity / account.starting_equity - 1) * HUNDRED
    current_dd = (peak - last.equity) / peak * HUNDRED if peak > 0 else ZERO
    return PerformanceReport(
        points=tuple(points),
        return_pct=return_pct.quantize(TWO_DP),
        benchmark_return_pct=benchmark_return_pct.quantize(TWO_DP),
        max_drawdown_pct=max_dd.quantize(TWO_DP),
        current_drawdown_pct=current_dd.quantize(TWO_DP),
        benchmark_symbol=benchmark_symbol,
    )
