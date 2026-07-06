"""STUDY: cross-sectional sector momentum (SPDR sector ETFs).

Universe: XLK XLF XLV XLE XLI XLY XLP XLB XLU XLRE XLC
  (XLRE inception 2015-10, XLC inception 2018-06 — a sector is only eligible
  once it has enough history to compute the lookback return).

Rule: on the FIRST TRADING DAY of each month, rank sectors by trailing
total return (dividend-adjusted closes), hold the top 3 equal-weight until the
next rebalance. Weights are written on rebalance dates and forward-filled
daily; the engine's next-day-shift convention means a signal computed at the
first trading day's close is held from the second trading day on (no lookahead).

Variants:
  (i)   mom6 plain          — 6-month (126 trading day) lookback
  (ii)  mom6 + SPY>200dSMA  — same, but 100% cash on any day SPY closed at or
                              below its 200-day SMA (gate applied DAILY, not
                              just at rebalance, for faster crash exit)
  (iii) mom3 plain          — 3-month (63 trading day) lookback
  (iv)  mom3 + gate         — bonus combination

Benchmarks: SPY buy-and-hold; equal-weight of all AVAILABLE sectors,
rebalanced monthly.

Walk-forward: train 2015-2022 / validate 2023-2025 / holdout 2026 YTD.
Each window is run standalone (enters from cash on day 1 — identical handling
for strategies and benchmarks). Signals use warmup data fetched from 2014 so
momentum and the 200d SMA are defined from the first window day.

Costs: 10 bps on turnover (default); a 25 bps sensitivity table is printed
because the gated variants trade more.

Run (from repo root):
    uv run python scripts/backtest/studies/sector_momentum.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from scripts.backtest.data import fetch_daily  # noqa: E402
from scripts.backtest.engine import run_weights  # noqa: E402
from scripts.backtest.metrics import summary  # noqa: E402

SECTORS = ["XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLB", "XLU", "XLRE", "XLC"]

# Later-inception symbols: request from inception so data.py's cache-coverage
# check passes and we don't refetch on every run. fetch_daily simply returns
# whatever exists; eligibility below handles the shorter history.
INCEPTION_FLOOR = {"XLRE": "2015-10-08", "XLC": "2018-06-19"}

FETCH_START = "2014-01-01"  # warmup: >200 trading days before 2015-01-01
END = "2026-07-01"

LOOKBACK_6M = 126  # trading days
LOOKBACK_3M = 63
TOP_N = 3
SMA_DAYS = 200
COST_BPS_MAIN = 10.0
COST_BPS_ALT = 25.0

WINDOWS = [
    ("FULL   2015-01..2026-07", "2015-01-01", "2026-07-01"),
    ("TRAIN  2015-01..2022-12", "2015-01-01", "2022-12-31"),
    ("VALID  2023-01..2025-12", "2023-01-01", "2025-12-31"),
    ("HOLD   2026-01..2026-07", "2026-01-01", "2026-07-01"),
]


def load_panel() -> pd.DataFrame:
    """Wide close panel (SPY + sectors), on SPY's trading calendar."""
    cols = []
    for sym in ["SPY"] + SECTORS:
        start = max(pd.Timestamp(FETCH_START), pd.Timestamp(INCEPTION_FLOOR.get(sym, FETCH_START)))
        s = fetch_daily(sym, start, END)["close"].rename(sym)
        cols.append(s)
    panel = pd.concat(cols, axis=1).sort_index()
    return panel[panel["SPY"].notna()]


def first_trading_days(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(index.to_series().groupby(index.to_period("M")).first())


def momentum_weights(sector_prices: pd.DataFrame, lookback: int, top_n: int = TOP_N) -> pd.DataFrame:
    """Daily target weights: top-N by trailing return, set monthly, ffilled."""
    mom = sector_prices / sector_prices.shift(lookback) - 1.0
    rows: dict[pd.Timestamp, pd.Series] = {}
    for t in first_trading_days(sector_prices.index):
        m = mom.loc[t].dropna()
        w = pd.Series(0.0, index=sector_prices.columns)
        if not m.empty:
            top = m.sort_values(ascending=False).head(top_n)
            w[top.index] = 1.0 / len(top)
        rows[t] = w
    monthly = pd.DataFrame(rows).T
    return monthly.reindex(sector_prices.index).ffill().fillna(0.0)


def equal_weight_weights(sector_prices: pd.DataFrame) -> pd.DataFrame:
    """Equal weight across sectors with a price on the rebalance date."""
    rows: dict[pd.Timestamp, pd.Series] = {}
    for t in first_trading_days(sector_prices.index):
        avail = sector_prices.loc[t].dropna().index
        w = pd.Series(0.0, index=sector_prices.columns)
        if len(avail):
            w[avail] = 1.0 / len(avail)
        rows[t] = w
    monthly = pd.DataFrame(rows).T
    return monthly.reindex(sector_prices.index).ffill().fillna(0.0)


def render(header: list[str], rows: list[list[str]]) -> str:
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) for i in range(len(header))]
    out = [
        "  ".join(h.ljust(w) for h, w in zip(header, widths, strict=False)),
        "  ".join("-" * w for w in widths),
    ]
    out += ["  ".join(c.ljust(w) for c, w in zip(r, widths, strict=False)) for r in rows]
    return "\n".join(out)


def fmt(s: dict) -> list[str]:
    return [
        s["name"],
        f"{s['cagr'] * 100:7.2f}%",
        f"{s['sharpe']:5.2f}",
        f"{s['max_drawdown'] * 100:7.2f}%",
        f"{s['exposure'] * 100:6.1f}%",
        f"{s['turnover']:6.2f}",
    ]


def main() -> None:
    panel = load_panel()
    sectors = panel[SECTORS]
    spy = panel["SPY"]

    print(f"Panel: {panel.index[0].date()} .. {panel.index[-1].date()}  ({len(panel)} trading days)")
    for sym in SECTORS:
        first = sectors[sym].first_valid_index()
        if first is not None and first > panel.index[0]:
            print(f"  note: {sym} history starts {first.date()} (later inception, handled via eligibility)")

    gate = (spy > spy.rolling(SMA_DAYS).mean()).fillna(False)

    w_mom6 = momentum_weights(sectors, LOOKBACK_6M)
    w_mom3 = momentum_weights(sectors, LOOKBACK_3M)
    w_mom6_gated = w_mom6.mul(gate.astype(float), axis=0)
    w_mom3_gated = w_mom3.mul(gate.astype(float), axis=0)
    w_ew = equal_weight_weights(sectors)
    w_spy = pd.DataFrame({"SPY": 1.0}, index=panel.index).reindex(columns=panel.columns).fillna(0.0)

    strategies = [
        ("mom6 top3 (i)", w_mom6),
        ("mom6 top3 +gate (ii)", w_mom6_gated),
        ("mom3 top3 (iii)", w_mom3),
        ("mom3 top3 +gate (iv)", w_mom3_gated),
        ("EW all sectors [bench]", w_ew),
        ("SPY B&H [bench]", w_spy),
    ]

    header = ["Name", "CAGR", "Sharpe", "MaxDD", "Expos", "Turn/yr"]

    for label, a, b in WINDOWS:
        a_ts, b_ts = pd.Timestamp(a), pd.Timestamp(b)
        px = panel.loc[(panel.index >= a_ts) & (panel.index <= b_ts)]
        rows = []
        for name, w in strategies:
            ww = w.loc[px.index]
            eq = run_weights(px, ww, cost_bps=COST_BPS_MAIN)
            rows.append(fmt(summary(eq, name, ww)))
        print(f"\n=== {label}  (cost {COST_BPS_MAIN:.0f} bps) ===")
        print(render(header, rows))

    # Cost sensitivity on the full window (gated variants trade the most).
    label, a, b = WINDOWS[0]
    px = panel.loc[(panel.index >= pd.Timestamp(a)) & (panel.index <= pd.Timestamp(b))]
    rows = []
    for name, w in strategies:
        ww = w.loc[px.index]
        eq = run_weights(px, ww, cost_bps=COST_BPS_ALT)
        rows.append(fmt(summary(eq, name, ww)))
    print(f"\n=== COST SENSITIVITY: {label} at {COST_BPS_ALT:.0f} bps ===")
    print(render(header, rows))


if __name__ == "__main__":
    main()
