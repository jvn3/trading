"""Study: the overnight effect on SPY and QQQ (2015-01-01 .. 2026-07-01).

Decomposes daily total return into the overnight leg (close -> next open) and
the intraday leg (open -> close) using FMP's ``/stable/historical-price-eod/full``
endpoint (split-adjusted open/close; SPY and QQQ have no splits in-window, so
these are raw traded prices).

DIVIDEND HANDLING (the caveat done properly): the ex-dividend price drop
happens OVERNIGHT, so the close->open holder is the one who earns the
dividend. We fetch ex-dates/amounts from ``/stable/dividends`` and credit the
cash dividend to (a) the overnight leg and (c) buy & hold on the ex-date.
The intraday (open->close) leg gets no dividends. This makes every
comparison total-return-correct instead of silently docking the overnight
strategy ~1.2%/yr (SPY) / ~0.6%/yr (QQQ).

Strategies (all long-only, 100% or flat):
  (a) overnight-only : buy at close t-1, sell at open t, every day
  (b) intraday-only  : buy at open t, sell at close t, every day
  (c) buy & hold     : total return, one entry
  (d) gated overnight: (a) but only when QQQ close > its 200d SMA at the
      entry close (signal at close t-1 gates the night into t; no lookahead)

Costs: overnight/intraday trade 2 sides EVERY active day (~250 round trips a
year), so costs are pivotal -> reported at 0, 1, and 5 bps PER SIDE.
B&H is charged one entry side.

Run:
  wsl.exe -- bash -lc 'cd /mnt/k/trading && uv run python -m scripts.backtest.studies.overnight_effect'
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import requests

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from scripts.backtest import metrics  # noqa: E402
from scripts.backtest.data import _api_key  # noqa: E402

FMP = "https://financialmodelingprep.com/stable"
CACHE_DIR = Path(__file__).resolve().parent / "_cache"

FETCH_START = "2014-01-02"  # burn-in so the 200d SMA is live by EVAL_START
EVAL_START = "2015-01-01"
EVAL_END = "2026-07-01"
COST_LEVELS_BPS = [0.0, 1.0, 5.0]  # per SIDE
SUB_PERIODS = [
    ("2015-2019", "2015-01-01", "2019-12-31"),
    ("2020-2022", "2020-01-01", "2022-12-31"),
    ("2023-2026", "2023-01-01", "2026-07-01"),
]


# ---------------------------------------------------------------- data ------

def fetch_ohlc(symbol: str) -> pd.DataFrame:
    """Daily open/close from FMP /full, cached under studies/_cache/."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{symbol}_ohlc.csv"
    if path.exists():
        df = pd.read_csv(path, parse_dates=["date"], index_col="date")
        if (
            not df.empty
            and df.index.min() <= pd.Timestamp(FETCH_START) + pd.Timedelta(days=7)
            and df.index.max() >= pd.Timestamp(EVAL_END) - pd.Timedelta(days=7)
        ):
            return df
    resp = requests.get(
        f"{FMP}/historical-price-eod/full",
        params={"symbol": symbol, "from": FETCH_START, "to": EVAL_END, "apikey": _api_key()},
        timeout=60,
    )
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        raise RuntimeError(f"no OHLC rows for {symbol}")
    df = pd.DataFrame(
        [{"date": r["date"], "open": float(r["open"]), "close": float(r["close"])} for r in rows]
    )
    df["date"] = pd.to_datetime(df["date"])
    df = df.drop_duplicates("date").set_index("date").sort_index()
    df.to_csv(path)
    return df


def fetch_dividends(symbol: str) -> pd.Series:
    """Per-share cash dividend keyed by EX-DATE (FMP 'date' field)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"{symbol}_divs.csv"
    if path.exists():
        s = pd.read_csv(path, parse_dates=["date"], index_col="date")["dividend"]
        if not s.empty and s.index.max() >= pd.Timestamp(EVAL_END) - pd.Timedelta(days=120):
            return s
    resp = requests.get(f"{FMP}/dividends", params={"symbol": symbol, "apikey": _api_key()}, timeout=60)
    resp.raise_for_status()
    rows = resp.json()
    s = pd.Series(
        {pd.Timestamp(r["date"]): float(r["dividend"]) for r in rows}, name="dividend"
    ).sort_index()
    s.index.name = "date"
    s.to_frame().to_csv(path)
    return s


# ---------------------------------------------------------- return legs -----

def build_legs(symbol: str) -> pd.DataFrame:
    """Daily overnight / intraday / buy&hold gross return legs (dividend-aware)."""
    px = fetch_ohlc(symbol)
    div = fetch_dividends(symbol).reindex(px.index).fillna(0.0)
    prev_close = px["close"].shift(1)
    out = pd.DataFrame(index=px.index)
    # holder over the night from close t-1 to open t receives the ex-date-t dividend
    out["overnight"] = (px["open"] + div) / prev_close - 1.0
    out["intraday"] = px["close"] / px["open"] - 1.0
    out["bh"] = (px["close"] + div) / prev_close - 1.0
    return out.dropna()


def qqq_gate(index: pd.Index) -> pd.Series:
    """True where QQQ close at t-1 (the entry close) is above its 200d SMA."""
    qqq = fetch_ohlc("QQQ")["close"]
    sma = qqq.rolling(200, min_periods=200).mean()
    raw = (qqq > sma)
    # signal formed at close t-1 gates the overnight return realized on row t
    return raw.shift(1).reindex(index).fillna(False).astype(bool)


# ------------------------------------------------------------- backtest -----

def run_strategy(
    gross: pd.Series,
    active: pd.Series,
    per_side_bps: float,
    entry_only: bool = False,
) -> tuple[pd.Series, pd.Series]:
    """Net daily returns + equity for a leg traded on ``active`` days."""
    c = per_side_bps / 10_000.0
    net = gross.where(active, 0.0)
    if entry_only:
        cost = pd.Series(0.0, index=gross.index)
        if len(cost):
            cost.iloc[0] = c
    else:
        cost = active.astype(float) * 2.0 * c  # buy + sell each active day
    net = net - cost
    equity = (1.0 + net).cumprod()
    return net, equity


def run_gated_bh(bh: pd.Series, gate: pd.Series, per_side_bps: float) -> tuple[pd.Series, pd.Series]:
    """Counterfactual: hold close-to-close while gated in; trade only on gate flips.

    Isolates how much of gated-overnight's edge is just the SMA trend filter.
    Costs: one side per flip day (enter = buy, exit = sell), not per day.
    """
    c = per_side_bps / 10_000.0
    net = bh.where(gate, 0.0)
    flips = gate.astype(float).diff().abs()
    if len(flips):
        flips.iloc[0] = float(gate.iloc[0])  # initial entry from cash
    net = net - flips * c
    equity = (1.0 + net).cumprod()
    return net, equity


def row(name: str, net: pd.Series, equity: pd.Series, active: pd.Series) -> dict:
    years = metrics._years(equity.index)
    g = net.where(active)
    return {
        "strategy": name,
        "CAGR": metrics.cagr(equity),
        "Sharpe": metrics.sharpe(equity),
        "MaxDD": metrics.max_drawdown(equity),
        "expo": float(active.mean()),
        "rt/yr": float(active.sum()) / years,
        "hit%": float((g.dropna() > 0).mean()),
    }


def fmt(df: pd.DataFrame) -> str:
    d = df.copy()
    for c in ("CAGR", "MaxDD", "hit%"):
        d[c] = (d[c] * 100).map("{:+.1f}%".format if c != "hit%" else "{:.1f}%".format)
    d["Sharpe"] = d["Sharpe"].map("{:.2f}".format)
    d["expo"] = (d["expo"] * 100).map("{:.0f}%".format)
    d["rt/yr"] = d["rt/yr"].map("{:.0f}".format)
    return d.to_string(index=False)


def sub_period_table(sym: str, legs: pd.DataFrame, gate: pd.Series) -> pd.DataFrame:
    recs = []
    always = pd.Series(True, index=legs.index)
    for label, s, e in SUB_PERIODS:
        sl = legs.loc[s:e]
        ga = gate.loc[sl.index]
        al = always.loc[sl.index]
        for name, leg, act, bps, eo in [
            ("B&H", sl["bh"], al, 1.0, True),
            ("overnight@1bps", sl["overnight"], al, 1.0, False),
            ("overnight@5bps", sl["overnight"], al, 5.0, False),
            ("gated-ON@1bps", sl["overnight"], ga, 1.0, False),
        ]:
            net, eq = run_strategy(leg, act, bps, entry_only=eo)
            recs.append(
                {"period": label, "strategy": name,
                 "CAGR": metrics.cagr(eq), "Sharpe": metrics.sharpe(eq),
                 "MaxDD": metrics.max_drawdown(eq)}
            )
    df = pd.DataFrame(recs)
    for c in ("CAGR", "MaxDD"):
        df[c] = (df[c] * 100).map("{:+.1f}%".format)
    df["Sharpe"] = df["Sharpe"].map("{:.2f}".format)
    return df


def main() -> None:
    pd.set_option("display.width", 160)
    for sym in ("SPY", "QQQ"):
        legs = build_legs(sym).loc[EVAL_START:EVAL_END]
        gate = qqq_gate(legs.index)
        always = pd.Series(True, index=legs.index)

        # sanity: overnight and intraday legs must compound back to buy & hold
        recon = (1 + legs["overnight"]) * (1 + legs["intraday"]) - 1
        max_gap = float((recon - legs["bh"]).abs().max())

        ann_on = float(legs["overnight"].mean()) * 252 * 1e4
        ann_id = float(legs["intraday"].mean()) * 252 * 1e4

        print("=" * 92)
        print(f"{sym}  {legs.index[0].date()} .. {legs.index[-1].date()}  "
              f"({len(legs)} days)   leg-recombine max gap {max_gap:.2e}")
        print(f"gross mean daily: overnight {ann_on/252:+.2f} bps/day "
              f"({ann_on/100:+.1f}%/yr simple)  |  intraday {ann_id/252:+.2f} bps/day "
              f"({ann_id/100:+.1f}%/yr simple)")
        print("-" * 92)

        rows = []
        for bps in COST_LEVELS_BPS:
            tag = f"@{bps:g}bps/side"
            net, eq = run_strategy(legs["bh"], always, bps, entry_only=True)
            if bps == COST_LEVELS_BPS[0]:
                rows.append(row("buy&hold (total ret)", net, eq, always))
            net, eq = run_strategy(legs["overnight"], always, bps)
            rows.append(row(f"overnight-only {tag}", net, eq, always))
            net, eq = run_strategy(legs["intraday"], always, bps)
            rows.append(row(f"intraday-only {tag}", net, eq, always))
            net, eq = run_strategy(legs["overnight"], gate, bps)
            rows.append(row(f"gated overnight {tag}", net, eq, gate))
            net, eq = run_gated_bh(legs["bh"], gate, bps)
            r = row(f"gated B&H (ctrl) {tag}", net, eq, gate)
            flips = gate.astype(float).diff().abs()
            r["rt/yr"] = float(flips.sum()) / 2.0 / metrics._years(eq.index)
            rows.append(r)
        print(fmt(pd.DataFrame(rows)))
        print()
        print(f"{sym} sub-periods:")
        print(sub_period_table(sym, legs, gate).to_string(index=False))
        print()


if __name__ == "__main__":
    main()
