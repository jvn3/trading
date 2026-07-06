"""STUDY: volatility-targeted sizing overlay on the S1-TQQQ rotation.

Idea: keep S1's regime gate (QQQ > 200d SMA -> hold TQQQ, else cash) but scale
the daily TQQQ weight by

    mult_t = clamp(target_vol / realized_vol_t, 0.3, 1.5)

where realized_vol_t is the 20d annualized vol of TQQQ daily returns computed
from closes up to and including day t. NO LOOKAHEAD: the engine's next-day
convention (weights.shift(1)) means the weight formed on day t's close — and
therefore the vol estimate through day t — is only held DURING day t+1, i.e.
the vol input is effectively shifted 1 day relative to the return it scales,
exactly like S1's own SMA signal.

Targets tested: 0.25, 0.35, 0.45 annualized.

LEVERAGE NOTE: the 1.5 upper clamp allows gross weight up to 1.5x TQQQ, which
the shared engine rejects (long-only, gross <= 1). This study includes a
minimal replica of engine.run_weights with the gross cap raised to 1.5;
leverage above 1.0 is financed at 0% (optimistic — flagged as caveat). A
"cap 1.0" variant of each target is also reported (multiplier clipped to
[0.3, 1.0]) since that is what the current long-only allocator could actually
hold without margin. The replica is asserted to match engine.run_weights
exactly on the unscaled path.

Costs: daily vol scaling adds turnover, so results are shown at BOTH 10 and
25 bps per unit turnover.

Run (from repo root, WSL):
    uv run python scripts/backtest/studies/vol_target_s1.py
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from scripts.backtest.data import extend_tqqq, fetch_daily  # noqa: E402
from scripts.backtest.engine import run_weights  # noqa: E402
from scripts.backtest.metrics import cagr, max_drawdown, sharpe, turnover  # noqa: E402
from scripts.backtest.strategies.s1_rotation import signal_weights  # noqa: E402

START = pd.Timestamp("2015-01-01")
END = pd.Timestamp("2026-07-01")
MA_LEN = 200
VOL_WIN = 20
TARGETS = (0.25, 0.35, 0.45)
CLAMP_LO, CLAMP_HI = 0.3, 1.5
COST_LEVELS = (10.0, 25.0)
ANNUALIZE = math.sqrt(252.0)


def run_weights_gross(
    prices: pd.DataFrame,
    weights: pd.DataFrame,
    cost_bps: float = 0.0,
    max_gross: float = CLAMP_HI,
) -> pd.Series:
    """engine.run_weights replica with the gross-weight cap raised to max_gross.

    Identical math otherwise (next-day shift, cost on |delta held|, cash at 0).
    Weight above 1.0 is implicitly financed at 0% interest.
    """
    if prices.empty:
        raise ValueError("prices is empty")
    prices = prices.sort_index()
    weights = weights.reindex(index=prices.index, columns=prices.columns).fillna(0.0)
    if (weights < -1e-12).any().any():
        raise ValueError("negative weights not supported")
    if (weights.sum(axis=1) > max_gross + 1e-9).any():
        raise ValueError(f"gross weight exceeds {max_gross}")

    held = weights.shift(1).fillna(0.0)
    asset_rets = prices.pct_change().fillna(0.0)
    gross_ret = (held * asset_rets).sum(axis=1)
    deltas = held.diff()
    deltas.iloc[0] = held.iloc[0]
    costs = deltas.abs().sum(axis=1) * (cost_bps / 10_000.0)
    equity = (1.0 + gross_ret - costs).cumprod()
    equity.name = "equity"
    return equity


def window(prices: pd.DataFrame, weights: pd.DataFrame,
           start: pd.Timestamp, end: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    p = prices.loc[(prices.index >= start) & (prices.index <= end)]
    w = weights.reindex(p.index).fillna(0.0)
    return p, w


def dd_in_year(equity: pd.Series, year: str) -> float:
    """Worst drawdown observed during `year`, measured vs the full-curve peak."""
    dd = equity / equity.cummax() - 1.0
    sel = dd.loc[dd.index.year == int(year)]
    return float(sel.min()) if len(sel) else 0.0


def fmt_row(name: str, eq: pd.Series, w: pd.DataFrame) -> list[str]:
    return [
        name,
        f"{cagr(eq) * 100:8.2f}%",
        f"{sharpe(eq):6.2f}",
        f"{max_drawdown(eq) * 100:8.2f}%",
        f"{dd_in_year(eq, '2020') * 100:8.2f}%",
        f"{dd_in_year(eq, '2022') * 100:8.2f}%",
        f"{turnover(w):7.2f}",
    ]


def render(header: list[str], rows: list[list[str]]) -> str:
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) for i in range(len(header))]
    lines = [
        "  ".join(h.ljust(w) for h, w in zip(header, widths, strict=False)),
        "  ".join("-" * w for w in widths),
    ]
    lines += ["  ".join(c.ljust(w) for c, w in zip(r, widths, strict=False)) for r in rows]
    return "\n".join(lines)


def main() -> None:
    warmup_start = START - pd.Timedelta(days=MA_LEN * 2 + 60)
    qqq = fetch_daily("QQQ", warmup_start, END)["close"]
    tqqq_raw = fetch_daily("TQQQ", warmup_start, END)["close"]
    tqqq, synth_mask = extend_tqqq(qqq, tqqq_raw)
    prices = pd.DataFrame({"TQQQ": tqqq, "QQQ": qqq}).dropna()
    n_synth = int(synth_mask.reindex(prices.index).fillna(False).sum())

    # --- signals (day-t close info; engine shifts +1d) ---------------------
    base = signal_weights(prices["QQQ"], ma_len=MA_LEN, variant="tqqq")
    rvol = prices["TQQQ"].pct_change().rolling(VOL_WIN).std() * ANNUALIZE

    def scaled(target: float, cap: float = CLAMP_HI) -> pd.DataFrame:
        mult = (target / rvol).clip(lower=CLAMP_LO, upper=min(cap, CLAMP_HI))
        mult = mult.fillna(CLAMP_LO)  # warmup rows only; sliced off before START
        w = base.copy()
        w["TQQQ"] = w["TQQQ"] * mult
        return w

    qqq_bh = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    qqq_bh["QQQ"] = 1.0

    # --- sanity: replica engine == shared engine on the unscaled path ------
    p_chk, w_chk = window(prices, base, START, END)
    eq_a = run_weights(p_chk, w_chk, cost_bps=10.0)
    eq_b = run_weights_gross(p_chk, w_chk, cost_bps=10.0)
    assert np.allclose(eq_a.values, eq_b.values), "engine replica mismatch"

    # --- multiplier diagnostics (risk-on days inside the study window) -----
    p_win, base_win = window(prices, base, START, END)
    rvol_win = rvol.reindex(p_win.index)
    risk_on = base_win["TQQQ"] > 0
    print("STUDY: vol-targeted sizing overlay on S1-TQQQ")
    print(f"window {p_win.index[0].date()}..{p_win.index[-1].date()} | MA{MA_LEN} gate | "
          f"{VOL_WIN}d TQQQ vol | clamp [{CLAMP_LO},{CLAMP_HI}] | synth TQQQ rows in window: {n_synth}")
    print(f"TQQQ 20d ann. vol over window: median {rvol_win.median():.2f}, "
          f"p10 {rvol_win.quantile(0.10):.2f}, p90 {rvol_win.quantile(0.90):.2f}")
    for t in TARGETS:
        m = (t / rvol_win).clip(CLAMP_LO, CLAMP_HI)[risk_on]
        print(f"  target {t:.2f}: mean mult {m.mean():.2f} | at lo-clamp {(m <= CLAMP_LO + 1e-9).mean() * 100:5.1f}% "
              f"| at hi-clamp {(m >= CLAMP_HI - 1e-9).mean() * 100:5.1f}% | mult>1 {(m > 1.0).mean() * 100:5.1f}% of risk-on days")
    print()

    # --- main comparison at each cost level ---------------------------------
    header = ["Name", "CAGR", "Sharpe", "MaxDD", "DD-2020", "DD-2022", "TO/yr"]
    curves_10bps: dict[str, pd.Series] = {}
    for cost in COST_LEVELS:
        rows: list[list[str]] = []

        p, w = window(prices, qqq_bh, START, END)
        eq = run_weights_gross(p, w, cost_bps=cost)
        rows.append(fmt_row("QQQ buy&hold", eq, w))
        if cost == 10.0:
            curves_10bps["QQQ B&H"] = eq

        p, w = window(prices, base, START, END)
        eq = run_weights_gross(p, w, cost_bps=cost)
        rows.append(fmt_row("S1-TQQQ unscaled", eq, w))
        if cost == 10.0:
            curves_10bps["S1 unscaled"] = eq

        for t in TARGETS:
            p, w = window(prices, scaled(t), START, END)
            eq = run_weights_gross(p, w, cost_bps=cost)
            rows.append(fmt_row(f"S1-VT {t:.2f} (clamp<=1.5)", eq, w))
            if cost == 10.0:
                curves_10bps[f"VT {t:.2f}"] = eq

        for t in TARGETS:
            p, w = window(prices, scaled(t, cap=1.0), START, END)
            eq = run_weights_gross(p, w, cost_bps=cost)
            rows.append(fmt_row(f"S1-VT {t:.2f} (cap 1.0)", eq, w))
            if cost == 10.0:
                curves_10bps[f"VT {t:.2f} cap1"] = eq

        print(f"=== full period, cost = {cost:.0f} bps/turnover ===")
        print(render(header, rows))
        print()

    # --- COVID question ------------------------------------------------------
    print("=== 2020 COVID drawdown vs CAGR cost (10 bps) ===")
    base_eq = curves_10bps["S1 unscaled"]
    base_cagr, base_dd20 = cagr(base_eq), dd_in_year(base_eq, "2020")
    print(f"S1 unscaled: CAGR {base_cagr * 100:.2f}%, 2020 DD {base_dd20 * 100:.2f}%")
    for label in [f"VT {t:.2f}" for t in TARGETS] + [f"VT {t:.2f} cap1" for t in TARGETS]:
        eq = curves_10bps[label]
        print(f"  {label:13s}: 2020 DD {dd_in_year(eq, '2020') * 100:7.2f}% "
              f"(cut {abs(base_dd20 - dd_in_year(eq, '2020')) * 100:5.1f} pts) | "
              f"CAGR {cagr(eq) * 100:6.2f}% (delta {(cagr(eq) - base_cagr) * 100:+.2f} pts)")
    print()

    # --- walk-forward split (10 bps) ----------------------------------------
    print("=== walk-forward CAGR / MaxDD (10 bps) ===")
    wf = [
        ("train 2015-2022", START, pd.Timestamp("2022-12-31")),
        ("validate 2023-2025", pd.Timestamp("2023-01-01"), pd.Timestamp("2025-12-31")),
        ("holdout 2026 YTD", pd.Timestamp("2026-01-01"), END),
    ]
    wf_header = ["Window", "S1 unscaled", "VT 0.25", "VT 0.35", "VT 0.45", "QQQ B&H"]
    wf_rows = []
    strategies = [("S1 unscaled", base)] + [(f"VT {t:.2f}", scaled(t)) for t in TARGETS] + [("QQQ B&H", qqq_bh)]
    for label, ws, we in wf:
        cells = [label]
        for _, wts in strategies:
            p, w = window(prices, wts, ws, we)
            eq = run_weights_gross(p, w, cost_bps=10.0)
            cells.append(f"{cagr(eq) * 100:6.1f}% / {max_drawdown(eq) * 100:6.1f}%")
        wf_rows.append(cells)
    print(render(wf_header, wf_rows))


if __name__ == "__main__":
    main()
