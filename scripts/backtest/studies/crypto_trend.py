"""Study: crypto trend-following for the planned S3 sleeve.

Rules tested on BTCUSD and ETHUSD (FMP EOD, close-only, includes weekends —
crypto trades 7d/week):
  (a) Donchian 20/10  — enter when close > prior 20d high of closes,
                        exit when close < prior 10d low of closes
  (b) Donchian 55/20  — same with 55/20
  (c) SMA100          — long when close > 100d SMA, else cash

Each rule runs on BTC alone, ETH alone, and a 50/50 combo (each leg gets a
0.5 weight when its own signal is on; cash otherwise). Benchmarks: BTC B&H,
ETH B&H, 50/50 B&H (daily-rebalanced).

Costs: 10 bps and 25 bps per unit turnover (crypto spreads are wider).
Window: 2017-01-01..2026-07-01 evaluated; data fetched from 2016-01-01 so all
signals are warm on day one. Each run starts from cash (engine convention).

Sharpe here is annualized with 365 daily periods (NOT the harness's 252)
because the crypto series has ~365 rows/year; CAGR is calendar-based either
way. Benchmarks and strategies use the same convention, so comparisons hold.

Run (from repo root):
    uv run python scripts/backtest/studies/crypto_trend.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from scripts.backtest.data import fetch_daily  # noqa: E402
from scripts.backtest.engine import run_weights  # noqa: E402
from scripts.backtest.metrics import cagr, exposure, max_drawdown, turnover  # noqa: E402

FETCH_START = "2016-01-01"  # warmup so 100d SMA / 55d channel exist at eval start
EVAL_START = "2017-01-01"
EVAL_END = "2026-07-01"
DAYS_PER_YEAR = 365  # crypto trades every calendar day


def sharpe365(equity: pd.Series) -> float:
    rets = equity.pct_change().dropna()
    if len(rets) < 2:
        return 0.0
    sd = float(rets.std())
    if math.isnan(sd) or sd < 1e-12:
        return 0.0
    return float(rets.mean()) / sd * math.sqrt(DAYS_PER_YEAR)


def donchian_signal(close: pd.Series, entry_n: int, exit_n: int) -> pd.Series:
    """1.0 while in a Donchian breakout position, else 0.0 (close-only channels).

    Enter when close > max(close) of the PRIOR entry_n days; exit when
    close < min(close) of the PRIOR exit_n days. Stateful, so iterate.
    """
    hi = close.rolling(entry_n).max().shift(1)
    lo = close.rolling(exit_n).min().shift(1)
    c, h, l = close.to_numpy(), hi.to_numpy(), lo.to_numpy()
    sig = np.zeros(len(c))
    in_pos = False
    for i in range(len(c)):
        if not in_pos:
            if not np.isnan(h[i]) and c[i] > h[i]:
                in_pos = True
        else:
            if not np.isnan(l[i]) and c[i] < l[i]:
                in_pos = False
        sig[i] = 1.0 if in_pos else 0.0
    return pd.Series(sig, index=close.index)


def sma_signal(close: pd.Series, n: int = 100) -> pd.Series:
    sma = close.rolling(n).mean()
    return (close > sma).astype(float)


def window_stats(equity: pd.Series, start: str, end: str) -> tuple[float, float]:
    """(total return, max drawdown) of the curve restricted to [start, end]."""
    w = equity.loc[(equity.index >= pd.Timestamp(start)) & (equity.index <= pd.Timestamp(end))]
    if len(w) < 2:
        return 0.0, 0.0
    return float(w.iloc[-1] / w.iloc[0] - 1.0), max_drawdown(w)


def main() -> None:
    btc = fetch_daily("BTCUSD", FETCH_START, EVAL_END)["close"]
    eth = fetch_daily("ETHUSD", FETCH_START, EVAL_END)["close"]
    prices = pd.DataFrame({"BTC": btc, "ETH": eth}).dropna()
    print(f"data: {prices.index[0].date()}..{prices.index[-1].date()}, {len(prices)} rows "
          f"(rows/yr ~ {len(prices) / ((prices.index[-1] - prices.index[0]).days / 365.25):.0f})")

    signals: dict[str, pd.DataFrame] = {}
    for label, fn in [
        ("don20/10", lambda s: donchian_signal(s, 20, 10)),
        ("don55/20", lambda s: donchian_signal(s, 55, 20)),
        ("sma100", lambda s: sma_signal(s, 100)),
    ]:
        signals[label] = pd.DataFrame({a: fn(prices[a]) for a in prices.columns})

    # Build weight frames: single-asset (full weight) and 50/50 combo.
    runs: list[tuple[str, pd.DataFrame]] = []
    for label, sig in signals.items():
        for asset in ["BTC", "ETH"]:
            w = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
            w[asset] = sig[asset]
            runs.append((f"{label} {asset}", w))
        runs.append((f"{label} 50/50", sig * 0.5))

    # Benchmarks.
    for asset in ["BTC", "ETH"]:
        w = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
        w[asset] = 1.0
        runs.append((f"B&H {asset}", w))
    runs.append(("B&H 50/50", pd.DataFrame(0.5, index=prices.index, columns=prices.columns)))

    eval_mask = (prices.index >= pd.Timestamp(EVAL_START)) & (prices.index <= pd.Timestamp(EVAL_END))
    px_eval = prices.loc[eval_mask]

    header = (f"{'name':<16} {'cost':>4} {'CAGR':>8} {'Sharpe':>7} {'MaxDD':>8} {'Expo':>6} "
              f"{'Turn/yr':>8} {'2022ret':>8} {'2022DD':>8} {'H1-26ret':>9} {'H1-26DD':>8}")
    print(header)
    print("-" * len(header))
    for name, w in runs:
        w_eval = w.loc[eval_mask]
        for cost in (10.0, 25.0):
            eq = run_weights(px_eval, w_eval, cost_bps=cost)
            r22, dd22 = window_stats(eq, "2022-01-01", "2022-12-31")
            r26, dd26 = window_stats(eq, "2026-01-01", "2026-07-01")
            print(f"{name:<16} {cost:>4.0f} {cagr(eq) * 100:>7.1f}% {sharpe365(eq):>7.2f} "
                  f"{max_drawdown(eq) * 100:>7.1f}% {exposure(w_eval) * 100:>5.0f}% "
                  f"{turnover(w_eval):>8.2f} {r22 * 100:>7.1f}% {dd22 * 100:>7.1f}% "
                  f"{r26 * 100:>8.1f}% {dd26 * 100:>7.1f}%")

    # Sub-period table (10 bps) for regime robustness: bull 17-20, winter 21-22, recent 23-26.
    print()
    subs = [("2017-2020", "2017-01-01", "2020-12-31"),
            ("2021-2022", "2021-01-01", "2022-12-31"),
            ("2023-2026H1", "2023-01-01", "2026-07-01")]
    hdr2 = f"{'name':<16}" + "".join(f" {lbl + ' ret':>14} {lbl + ' DD':>13}" for lbl, _, _ in subs)
    print("sub-periods (each run standalone from cash, 10 bps):")
    print(hdr2)
    print("-" * len(hdr2))
    for name, w in runs:
        cells = []
        for _, s, e in subs:
            m = (prices.index >= pd.Timestamp(s)) & (prices.index <= pd.Timestamp(e))
            eq = run_weights(prices.loc[m], w.loc[m], cost_bps=10.0)
            cells.append(f" {(eq.iloc[-1] / eq.iloc[0] - 1) * 100:>13.1f}% {max_drawdown(eq) * 100:>12.1f}%")
        print(f"{name:<16}" + "".join(cells))


if __name__ == "__main__":
    main()
