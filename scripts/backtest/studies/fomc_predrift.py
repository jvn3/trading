"""Study: pre-FOMC announcement drift in SPY, 2015-2026.

HYPOTHESIS (Lucca & Moench 2015): SPY earns outsized returns in the ~24h
before scheduled FOMC announcements. Reported to have decayed post-2015.

TEST: hold SPY from the close of T-2 to the close of T-0, where T-0 is the
scheduled announcement day (day 2 of each meeting); cash otherwise.
- Per-window (2-trading-day) returns vs same-length random windows
  (bootstrap over sample means, period-matched).
- Engine run (next-day convention, scripts.backtest.engine) vs SPY B&H.
- Subsamples: 2015-2019 / 2020-2026H1 / 2021-2026H1 (strict: ex-COVID).
- Costs are pivotal (round trip every ~6 weeks, thin expected edge), so the
  engine is run at 2 bps and 10 bps.

FOMC ANNOUNCEMENT DATES: scheduled meetings only, day 2 of each meeting,
collected 2026-07-06 from federalreserve.gov:
  - https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm (2021-2026)
  - https://www.federalreserve.gov/monetarypolicy/fomchistorical{2015..2020}.htm
Exclusions: 2019-10-04 unscheduled call; 2020-03-02/03-15 emergency actions
(the scheduled 2020-03-17/18 meeting was cancelled); 2020/2025 notation votes.

Usage (from repo root):
    uv run python scripts/backtest/studies/fomc_predrift.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from scripts.backtest.data import fetch_daily  # noqa: E402
from scripts.backtest.engine import run_weights  # noqa: E402
from scripts.backtest.metrics import cagr, max_drawdown, sharpe  # noqa: E402

START, END = "2015-01-01", "2026-07-01"
N_BOOT = 20_000
SEED = 42

# Scheduled FOMC announcement days (day 2 of each scheduled meeting).
FOMC_ANNOUNCEMENTS = [
    # 2015
    "2015-01-28", "2015-03-18", "2015-04-29", "2015-06-17",
    "2015-07-29", "2015-09-17", "2015-10-28", "2015-12-16",
    # 2016
    "2016-01-27", "2016-03-16", "2016-04-27", "2016-06-15",
    "2016-07-27", "2016-09-21", "2016-11-02", "2016-12-14",
    # 2017
    "2017-02-01", "2017-03-15", "2017-05-03", "2017-06-14",
    "2017-07-26", "2017-09-20", "2017-11-01", "2017-12-13",
    # 2018
    "2018-01-31", "2018-03-21", "2018-05-02", "2018-06-13",
    "2018-08-01", "2018-09-26", "2018-11-08", "2018-12-19",
    # 2019
    "2019-01-30", "2019-03-20", "2019-05-01", "2019-06-19",
    "2019-07-31", "2019-09-18", "2019-10-30", "2019-12-11",
    # 2020 (7 scheduled; March meeting cancelled, emergency actions excluded)
    "2020-01-29", "2020-04-29", "2020-06-10", "2020-07-29",
    "2020-09-16", "2020-11-05", "2020-12-16",
    # 2021
    "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16",
    "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15",
    # 2022
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15",
    "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
    # 2023
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14",
    "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    # 2024
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
    "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    # 2025 (Aug 22 notation vote excluded)
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    # 2026 through study end
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
]

PERIODS = {
    "full 2015-2026H1": ("2015-01-01", "2026-07-01"),
    "pre-2020 (2015-2019)": ("2015-01-01", "2019-12-31"),
    "post-2020 (2020-2026H1)": ("2020-01-01", "2026-07-01"),
    "strict post-COVID (2021-2026H1)": ("2021-01-01", "2026-07-01"),
}


def per_window_stats(close: pd.Series, fomc_pos: np.ndarray, lo: pd.Timestamp,
                     hi: pd.Timestamp, rng: np.random.Generator) -> dict:
    """FOMC 2-day window returns vs random same-length windows, one period."""
    idx = close.index
    c = close.to_numpy()

    in_period = [p for p in fomc_pos if lo <= idx[p] <= hi]
    fomc_ret = np.array([c[p] / c[p - 2] - 1.0 for p in in_period])

    # All overlapping 2-day windows ENDING inside the same period.
    all_pos = np.array([t for t in range(2, len(c)) if lo <= idx[t] <= hi])
    all_ret = c[all_pos] / c[all_pos - 2] - 1.0
    non_fomc = np.setdiff1d(all_pos, np.array(in_period, dtype=int))
    non_ret = c[non_fomc] / c[non_fomc - 2] - 1.0

    n = len(fomc_ret)
    boot_means = all_ret[rng.integers(0, len(all_ret), size=(N_BOOT, n))].mean(axis=1)
    p_boot = float((boot_means >= fomc_ret.mean()).mean())
    tstat = (fomc_ret.mean() - non_ret.mean()) / (fomc_ret.std(ddof=1) / np.sqrt(n))

    return {
        "n": n,
        "mean_bps": fomc_ret.mean() * 1e4,
        "median_bps": float(np.median(fomc_ret)) * 1e4,
        "hit": float((fomc_ret > 0).mean()),
        "rand_mean_bps": all_ret.mean() * 1e4,
        "edge_bps": (fomc_ret.mean() - all_ret.mean()) * 1e4,
        "tstat": float(tstat),
        "p_boot": p_boot,
    }


def main() -> None:
    close = fetch_daily("SPY", START, END)["close"]
    idx = close.index

    # Map announcement dates to positions; every scheduled announcement day
    # should be a trading day — fail loudly if not.
    stamps = pd.to_datetime(FOMC_ANNOUNCEMENTS)
    missing = [d.date() for d in stamps if d not in idx]
    if missing:
        raise RuntimeError(f"FOMC dates not in SPY index: {missing}")
    fomc_pos = np.array(sorted(idx.get_loc(d) for d in stamps))
    if (fomc_pos < 2).any():
        raise RuntimeError("a meeting falls too early in the price window")

    print(f"SPY daily closes: {idx[0].date()}..{idx[-1].date()} ({len(idx)} days), "
          f"{len(fomc_pos)} scheduled FOMC announcements\n")

    # ---- per-window stats vs random windows ----
    rng = np.random.default_rng(SEED)
    hdr = (f"{'period':32s} {'N':>3s} {'mean':>8s} {'median':>8s} {'hit%':>6s} "
           f"{'rand2d':>8s} {'edge':>8s} {'t':>6s} {'p_boot':>7s}")
    print("Per-window 2-day returns (close T-2 -> close T-0), GROSS of costs, bps:")
    print(hdr)
    for name, (lo, hi) in PERIODS.items():
        s = per_window_stats(close, fomc_pos, pd.Timestamp(lo), pd.Timestamp(hi), rng)
        print(f"{name:32s} {s['n']:3d} {s['mean_bps']:8.1f} {s['median_bps']:8.1f} "
              f"{s['hit'] * 100:5.1f}% {s['rand_mean_bps']:8.1f} {s['edge_bps']:8.1f} "
              f"{s['tstat']:6.2f} {s['p_boot']:7.3f}")

    # Day-level decomposition: T-1 (pre-announcement day) vs T-0 (announcement).
    day_ret = close.pct_change().to_numpy()
    tm1 = day_ret[fomc_pos - 1]
    t0 = day_ret[fomc_pos]
    uncond = np.nanmean(day_ret)
    print(f"\nDay decomposition (bps/day): T-1 mean {np.mean(tm1) * 1e4:6.1f}, "
          f"T-0 mean {np.mean(t0) * 1e4:6.1f}, all-days mean {uncond * 1e4:6.1f}")

    # ---- engine run: hold during T-1 and T-0 -> set weight at T-2 and T-1 ----
    prices = close.to_frame(name="SPY")
    w = pd.DataFrame(0.0, index=idx, columns=["SPY"])
    for p in fomc_pos:
        w.iloc[[p - 2, p - 1], 0] = 1.0
    w_bh = pd.DataFrame(1.0, index=idx, columns=["SPY"])

    curves = {
        "FOMC drift @2bps": run_weights(prices, w, cost_bps=2.0),
        "FOMC drift @10bps": run_weights(prices, w, cost_bps=10.0),
        "SPY buy&hold @2bps": run_weights(prices, w_bh, cost_bps=2.0),
    }
    n_meet_yr = len(fomc_pos) / ((idx[-1] - idx[0]).days / 365.25)
    print(f"\nEngine (next-day convention; exposure ~{2 * len(fomc_pos) / len(idx):.1%} "
          f"of days, ~{n_meet_yr:.1f} round trips/yr):")
    print(f"{'strategy':22s} {'period':32s} {'CAGR':>8s} {'Sharpe':>7s} {'MaxDD':>8s}")
    for sname, eq in curves.items():
        for pname, (lo, hi) in PERIODS.items():
            seg = eq.loc[lo:hi]
            seg = seg / seg.iloc[0]
            print(f"{sname:22s} {pname:32s} {cagr(seg) * 100:7.2f}% "
                  f"{sharpe(seg):7.2f} {max_drawdown(seg) * 100:7.2f}%")
        print()

    # Sharpe measured on in-market days only (does the time IN market beat
    # an average 2 days of SPY, risk-adjusted?)
    held = w.shift(1).fillna(0.0)["SPY"].to_numpy() > 0
    in_rets = pd.Series(day_ret[held])
    all_rets = pd.Series(day_ret[1:])
    ann = np.sqrt(252)
    print(f"In-market days only: ann.Sharpe {in_rets.mean() / in_rets.std() * ann:5.2f} "
          f"(n={held.sum()}) vs all SPY days {all_rets.mean() / all_rets.std() * ann:5.2f}")


if __name__ == "__main__":
    main()
