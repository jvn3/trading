"""Walk-forward backtest for user-authored strategies (S4.2). Pure, injected closes.

Honesty rules baked in:
- **No lookahead**: a signal computed on day t's close executes at day t+1's close.
- **Same friction as paper trading**: 5 bps adverse slippage on every fill (matches S1.5).
- **Walk-forward, no fitting**: the user's params are fixed, so the windows are successive
  out-of-sample consistency checks — a strategy that only worked in one regime shows it here.
- **Benchmark always attached**: every window and the aggregate carry buy-and-hold-the-symbol
  and the account benchmark comparison; a naked return never leaves this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from alphadash.domain.strategy_rules import StrategyParams, evaluate

ZERO = Decimal("0")
HUNDRED = Decimal("100")
TWO_DP = Decimal("0.01")
SLIPPAGE = Decimal("0.0005")  # 5 bps, matches the S1.5 paper engine
STARTING_EQUITY = Decimal("10000")
DEFAULT_WINDOWS = 4
MIN_BARS = 30
SMALL_SAMPLE_TRADES = 10


@dataclass(frozen=True)
class ClosedTrade:
    entry_day: date
    exit_day: date
    entry_price: Decimal
    exit_price: Decimal
    return_pct: Decimal


@dataclass(frozen=True)
class WindowResult:
    start: date
    end: date
    strategy_return_pct: Decimal
    buy_hold_return_pct: Decimal
    trades: int


@dataclass(frozen=True)
class BacktestResult:
    windows: tuple[WindowResult, ...]
    total_return_pct: Decimal
    buy_hold_return_pct: Decimal
    benchmark_return_pct: Decimal  # account benchmark (e.g. SPY) over the same span
    max_drawdown_pct: Decimal
    closed_trades: tuple[ClosedTrade, ...]
    win_rate_pct: Decimal | None
    windows_beating_buy_hold: int
    small_sample: bool
    days: int
    caveats: tuple[str, ...]


class BacktestError(ValueError):
    """Not enough data / invalid inputs. Message is safe to show the user."""


def _pct(last: Decimal, first: Decimal) -> Decimal:
    if first <= 0:
        return ZERO
    return ((last / first - 1) * HUNDRED).quantize(TWO_DP)


def _simulate(
    days: list[date], closes: list[Decimal], params: StrategyParams
) -> tuple[list[Decimal], list[ClosedTrade]]:
    """Replay the rules over the series. Returns (daily equity curve, closed trades).

    Decision on day t uses closes[: t+1]; the resulting fill happens at closes[t+1]
    (next-close execution — the strictest honest assumption available with EOD data).
    """
    cash = STARTING_EQUITY
    qty = ZERO
    entry_price: Decimal | None = None
    entry_day: date | None = None
    pending: str | None = None  # decision made yesterday, fills today
    equity_curve: list[Decimal] = []
    trades: list[ClosedTrade] = []

    for t, (day, close) in enumerate(zip(days, closes, strict=True)):
        # 1) Fill yesterday's decision at today's close (with adverse slippage)
        if pending == "enter" and qty == ZERO:
            fill = close * (1 + SLIPPAGE)
            budget = (cash + qty * close) * params.size_pct / HUNDRED
            if fill > 0 and budget > 0:
                qty = budget / fill
                cash -= qty * fill
                entry_price = fill
                entry_day = day
        elif pending == "exit" and qty > ZERO:
            fill = close * (1 - SLIPPAGE)
            cash += qty * fill
            trades.append(
                ClosedTrade(
                    entry_day=entry_day,
                    exit_day=day,
                    entry_price=entry_price,
                    exit_price=fill,
                    return_pct=_pct(fill, entry_price),
                )
            )
            qty = ZERO
            entry_price = None
            entry_day = None
        pending = None

        # 2) Mark equity at today's close
        equity_curve.append(cash + qty * close)

        # 3) Decide from history up to and including today — fills tomorrow
        if t < len(closes) - 1:
            action = evaluate(closes[: t + 1], params, entry_price)
            if action in ("enter", "exit"):
                pending = action

    return equity_curve, trades


def run_backtest(
    *,
    days: list[date],
    closes: list[Decimal],
    benchmark_closes: list[Decimal],
    params: StrategyParams,
    n_windows: int = DEFAULT_WINDOWS,
) -> BacktestResult:
    if len(days) != len(closes):
        raise BacktestError("days and closes must align")
    if len(closes) < MIN_BARS:
        raise BacktestError(
            f"not enough price history to backtest honestly ({len(closes)} bars, need {MIN_BARS})"
        )
    if len(benchmark_closes) != len(closes):
        raise BacktestError("benchmark series must align with the symbol series")

    equity_curve, trades = _simulate(days, closes, params)

    # Max drawdown over the full curve
    peak = ZERO
    max_dd = ZERO
    for eq in equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak * HUNDRED)

    # Walk-forward windows: contiguous equal slices of the SAME replay (state carries over,
    # exactly like live trading would; each window reports its own segment return).
    n_windows = max(1, min(n_windows, len(closes) // (MIN_BARS // 2)))
    size = len(closes) // n_windows
    windows: list[WindowResult] = []
    for w in range(n_windows):
        lo = w * size
        hi = (w + 1) * size - 1 if w < n_windows - 1 else len(closes) - 1
        windows.append(
            WindowResult(
                start=days[lo],
                end=days[hi],
                strategy_return_pct=_pct(equity_curve[hi], equity_curve[lo]),
                buy_hold_return_pct=_pct(closes[hi], closes[lo]),
                trades=sum(1 for tr in trades if days[lo] <= tr.exit_day <= days[hi]),
            )
        )

    wins = sum(1 for tr in trades if tr.return_pct > 0)
    win_rate = (Decimal(wins) / Decimal(len(trades)) * HUNDRED).quantize(TWO_DP) if trades else None
    beating = sum(1 for w in windows if w.strategy_return_pct > w.buy_hold_return_pct)

    caveats = [
        "Simulated on end-of-day closes with next-close fills and modeled slippage — real "
        "intraday behavior differs.",
        "Your parameters were not fitted to this data, but you may still have chosen them "
        "because they look good recently. Walk-forward windows show consistency, not proof.",
        "Past performance (simulated or real) does not predict future results.",
    ]
    if len(trades) < SMALL_SAMPLE_TRADES:
        caveats.insert(
            0,
            f"Only {len(trades)} closed trade(s) — far too few to distinguish luck from edge.",
        )

    return BacktestResult(
        windows=tuple(windows),
        total_return_pct=_pct(equity_curve[-1], equity_curve[0]),
        buy_hold_return_pct=_pct(closes[-1], closes[0]),
        benchmark_return_pct=_pct(benchmark_closes[-1], benchmark_closes[0]),
        max_drawdown_pct=max_dd.quantize(TWO_DP),
        closed_trades=tuple(trades),
        win_rate_pct=win_rate,
        windows_beating_buy_hold=beating,
        small_sample=len(trades) < SMALL_SAMPLE_TRADES,
        days=len(closes),
        caveats=tuple(caveats),
    )


def result_to_json(result: BacktestResult) -> dict:
    return {
        "windows": [
            {
                "start": w.start.isoformat(),
                "end": w.end.isoformat(),
                "strategy_return_pct": float(w.strategy_return_pct),
                "buy_hold_return_pct": float(w.buy_hold_return_pct),
                "trades": w.trades,
            }
            for w in result.windows
        ],
        "total_return_pct": float(result.total_return_pct),
        "buy_hold_return_pct": float(result.buy_hold_return_pct),
        "benchmark_return_pct": float(result.benchmark_return_pct),
        "max_drawdown_pct": float(result.max_drawdown_pct),
        "closed_trades": len(result.closed_trades),
        "win_rate_pct": float(result.win_rate_pct) if result.win_rate_pct is not None else None,
        "windows_beating_buy_hold": result.windows_beating_buy_hold,
        "small_sample": result.small_sample,
        "days": result.days,
        "caveats": list(result.caveats),
    }
