"""Run the S1 regime-gated rotation backtest and compare against buy-and-hold.

Usage (from repo root):
    uv run python scripts/backtest/run_s1.py \
        --start 2015-01-01 --end 2026-07-01 --ma 200 --cost-bps 10

Prints a comparison table (S1 variants vs SPY/QQQ buy-and-hold) plus a
walk-forward split (train 2015-2022 / validate 2023-2025 / holdout 2026 YTD),
and writes the same report as markdown to data/backtest_reports/.

Note on windows: each window (and the full period) is run standalone — the
portfolio enters the window from cash, so the first day is flat. QQQ is
fetched with extra pre-``start`` warmup so the SMA is defined from day one.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402

from scripts.backtest.data import extend_tqqq, fetch_daily  # noqa: E402
from scripts.backtest.engine import run_weights  # noqa: E402
from scripts.backtest.metrics import cagr, max_drawdown, summary  # noqa: E402
from scripts.backtest.strategies.s1_rotation import VARIANTS, signal_weights  # noqa: E402

REPORT_DIR = REPO_ROOT / "data" / "backtest_reports"

COLUMNS = ["Name", "CAGR", "Sharpe", "MaxDD", "Exposure", "Turnover/yr"]


def _fmt_row(s: dict) -> list[str]:
    return [
        s["name"],
        f"{s['cagr'] * 100:8.2f}%",
        f"{s['sharpe']:6.2f}",
        f"{s['max_drawdown'] * 100:8.2f}%",
        f"{s['exposure'] * 100:7.1f}%",
        f"{s['turnover']:8.2f}",
    ]


def _render_table(header: list[str], rows: list[list[str]], markdown: bool) -> str:
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) for i in range(len(header))]
    if markdown:
        lines = [
            "| " + " | ".join(h.ljust(w) for h, w in zip(header, widths, strict=False)) + " |",
            "|" + "|".join("-" * (w + 2) for w in widths) + "|",
        ]
        lines += ["| " + " | ".join(c.ljust(w) for c, w in zip(r, widths, strict=False)) + " |" for r in rows]
    else:
        lines = [
            "  ".join(h.ljust(w) for h, w in zip(header, widths, strict=False)),
            "  ".join("-" * w for w in widths),
        ]
        lines += ["  ".join(c.ljust(w) for c, w in zip(r, widths, strict=False)) for r in rows]
    return "\n".join(lines)


def _bh_weights(prices: pd.DataFrame, col: str) -> pd.DataFrame:
    w = pd.DataFrame(0.0, index=prices.index, columns=prices.columns)
    w[col] = 1.0
    return w


def _run_window(
    prices: pd.DataFrame, weights: pd.DataFrame, cost_bps: float,
    start: pd.Timestamp, end: pd.Timestamp,
) -> tuple[pd.Series, pd.DataFrame]:
    p = prices.loc[(prices.index >= start) & (prices.index <= end)]
    w = weights.reindex(p.index).fillna(0.0)
    return run_weights(p, w, cost_bps=cost_bps), w


def main() -> None:
    ap = argparse.ArgumentParser(description="S1 rotation backtest vs buy-and-hold")
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--end", default="2026-07-01")
    ap.add_argument("--ma", type=int, default=200, help="SMA length in trading days")
    ap.add_argument("--cost-bps", type=float, default=10.0, help="cost in bps per unit turnover")
    ap.add_argument("--variant", default="tqqq", choices=VARIANTS,
                    help="variant reported in the walk-forward section")
    args = ap.parse_args()

    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)
    # ~2 calendar days per trading day of SMA warmup, plus slack.
    warmup_start = start - pd.Timedelta(days=args.ma * 2 + 40)

    qqq = fetch_daily("QQQ", warmup_start, end)["close"]
    spy = fetch_daily("SPY", start, end)["close"]
    tqqq_raw = fetch_daily("TQQQ", warmup_start, end)["close"]
    tqqq, synth_mask = extend_tqqq(qqq, tqqq_raw)

    prices = pd.DataFrame({"TQQQ": tqqq, "QQQ": qqq}).dropna()
    spy_prices = spy.to_frame("SPY")
    n_synth = int(synth_mask.sum())

    # --- Full-period comparison ------------------------------------------
    rows: list[dict] = []
    variant_weights: dict[str, pd.DataFrame] = {}
    for variant in VARIANTS:
        w_full = signal_weights(prices["QQQ"], ma_len=args.ma, variant=variant)
        equity, w = _run_window(prices, w_full, args.cost_bps, start, end)
        variant_weights[variant] = w_full
        rows.append(summary(equity, f"S1 {variant} (MA{args.ma})", w))

    qqq_bh_eq, qqq_bh_w = _run_window(
        prices, _bh_weights(prices, "QQQ"), args.cost_bps, start, end)
    spy_bh_eq, spy_bh_w = _run_window(
        spy_prices, _bh_weights(spy_prices, "SPY"), args.cost_bps, start, end)
    rows.append(summary(qqq_bh_eq, "QQQ buy&hold", qqq_bh_w))
    rows.append(summary(spy_bh_eq, "SPY buy&hold", spy_bh_w))

    main_table = [_fmt_row(s) for s in rows]

    # --- Walk-forward split ----------------------------------------------
    windows = [
        ("train 2015-2022", start, pd.Timestamp("2022-12-31")),
        ("validate 2023-2025", pd.Timestamp("2023-01-01"), pd.Timestamp("2025-12-31")),
        ("holdout 2026 YTD", pd.Timestamp("2026-01-01"), end),
    ]
    wf_header = ["Window", f"S1 {args.variant} CAGR", "S1 MaxDD", "QQQ B&H CAGR", "QQQ MaxDD"]
    wf_rows: list[list[str]] = []
    chosen_w = variant_weights[args.variant]
    for label, w_start, w_end in windows:
        w_start, w_end = max(w_start, start), min(w_end, end)
        if w_start >= w_end:
            continue
        s1_eq, _ = _run_window(prices, chosen_w, args.cost_bps, w_start, w_end)
        bh_eq, _ = _run_window(prices, _bh_weights(prices, "QQQ"), args.cost_bps, w_start, w_end)
        wf_rows.append([
            label,
            f"{cagr(s1_eq) * 100:8.2f}%",
            f"{max_drawdown(s1_eq) * 100:8.2f}%",
            f"{cagr(bh_eq) * 100:8.2f}%",
            f"{max_drawdown(bh_eq) * 100:8.2f}%",
        ])

    # --- Render ------------------------------------------------------------
    period = f"{prices.index[0].date()} .. {prices.loc[start:end].index[-1].date()}"
    notes = (
        f"Period: {start.date()} .. {end.date()} (data {period}) | MA: {args.ma}d | "
        f"cost: {args.cost_bps:.0f} bps/turnover | next-day fill convention | "
        f"synthetic TQQQ rows (3x QQQ - drag): {n_synth}"
    )
    txt = "\n".join([
        "S1 rotation backtest",
        notes,
        "",
        _render_table(COLUMNS, main_table, markdown=False),
        "",
        f"Walk-forward (variant: {args.variant})",
        _render_table(wf_header, wf_rows, markdown=False),
    ])
    print(txt)

    md = "\n".join([
        "# S1 rotation backtest",
        "",
        notes,
        "",
        "## Full period",
        "",
        _render_table(COLUMNS, main_table, markdown=True),
        "",
        f"## Walk-forward (variant: {args.variant})",
        "",
        _render_table(wf_header, wf_rows, markdown=True),
        "",
    ])
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"s1_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    report_path.write_text(md, encoding="utf-8")
    print(f"\nreport written: {report_path}")


if __name__ == "__main__":
    main()
