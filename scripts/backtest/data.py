"""EOD price data for the backtest harness: FMP fetch + local file cache.

DATA SOURCE / ADJUSTMENT CHOICE: we use FMP's
``/stable/historical-price-eod/dividend-adjusted`` endpoint and its
``adjClose`` field, which is split- AND dividend-adjusted — the right series
for total-return backtests. (The plain ``/full`` endpoint on this plan returns
only a split-adjusted ``close`` with no ``adjClose`` field, verified
empirically 2026-07-06; we fall back to it only if the dividend-adjusted
endpoint returns nothing for a symbol.)

CACHE: one CSV per symbol under ``data/backtest_cache/`` — CSV, not parquet,
because pyarrow is not installed in this venv (pandas 3.0.2 without pyarrow).
Cache policy is deliberately simple: if the cached date range does not cover
the requested range (with a few days of slack for weekends/holidays at the
edges), the WHOLE range is refetched and the cache overwritten.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "data" / "backtest_cache"
FMP_BASE = "https://financialmodelingprep.com/stable/historical-price-eod"

# Requested edges rarely fall on trading days; allow this much slack when
# deciding whether the cache covers a requested range.
_EDGE_SLACK = pd.Timedelta(days=7)


def _api_key() -> str:
    load_dotenv(REPO_ROOT / ".env")
    key = os.environ.get("FMP_API_KEY", "")
    if not key:
        raise RuntimeError("FMP_API_KEY not set (expected in K:/trading/.env)")
    return key


def _rows_to_frame(rows: list[dict], price_field: str) -> pd.DataFrame:
    df = pd.DataFrame([{"date": r["date"], "close": r[price_field]} for r in rows])
    df["date"] = pd.to_datetime(df["date"])
    df = df.drop_duplicates("date").set_index("date").sort_index()
    df["close"] = df["close"].astype(float)
    return df


def _fetch_fmp(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Fetch [start, end] daily closes from FMP; adjClose preferred (see module doc)."""
    params = {
        "symbol": symbol,
        "from": start.strftime("%Y-%m-%d"),
        "to": end.strftime("%Y-%m-%d"),
        "apikey": _api_key(),
    }
    resp = requests.get(f"{FMP_BASE}/dividend-adjusted", params=params, timeout=60)
    resp.raise_for_status()
    rows = resp.json()
    if rows:
        return _rows_to_frame(rows, "adjClose")
    # Fallback: split-adjusted close only (no dividend adjustment available).
    resp = requests.get(f"{FMP_BASE}/full", params=params, timeout=60)
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        raise RuntimeError(f"FMP returned no data for {symbol} {params['from']}..{params['to']}")
    return _rows_to_frame(rows, "close")


def fetch_daily(symbol: str, start: str | pd.Timestamp, end: str | pd.Timestamp) -> pd.DataFrame:
    """Daily closes for ``symbol`` over [start, end], date-indexed, cached locally.

    Returns a DataFrame indexed by date with a single ``close`` column
    (dividend-adjusted when FMP provides it — see module docstring).
    """
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    if start_ts > end_ts:
        raise ValueError(f"start {start_ts.date()} is after end {end_ts.date()}")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{symbol}.csv"

    df: pd.DataFrame | None = None
    if cache_path.exists():
        cached = pd.read_csv(cache_path, parse_dates=["date"], index_col="date")
        if (
            not cached.empty
            and cached.index.min() <= start_ts + _EDGE_SLACK
            and cached.index.max() >= end_ts - _EDGE_SLACK
        ):
            df = cached

    if df is None:
        df = _fetch_fmp(symbol, start_ts, end_ts)
        df.to_csv(cache_path)

    return df.loc[(df.index >= start_ts) & (df.index <= end_ts)].copy()


def extend_tqqq(
    qqq_close: pd.Series,
    tqqq_close: pd.Series,
    expense_ratio: float = 0.0095,
) -> tuple[pd.Series, pd.Series]:
    """Extend TQQQ history backwards with synthetic prices derived from QQQ.

    TQQQ launched 2010-02; for QQQ dates before the first real TQQQ print we
    APPROXIMATE its daily return as ``3 x QQQ daily return - expense_ratio/252``
    (perfect 3x daily rebalance minus expense drag; ignores borrow/swap costs
    and tracking error, so synthetic TQQQ is slightly optimistic). Synthetic
    price levels are chained backwards from the first real TQQQ close so the
    two segments join without a jump.

    Returns ``(combined_close, synthetic_mask)`` where ``synthetic_mask`` is a
    boolean Series marking the synthesized rows.
    """
    if tqqq_close.empty:
        raise ValueError("need at least one real TQQQ price to anchor synthesis")
    tqqq_close = tqqq_close.sort_index()
    qqq_close = qqq_close.sort_index()
    first_real = tqqq_close.index[0]

    if not (qqq_close.index < first_real).any():
        combined = tqqq_close.copy()
        return combined, pd.Series(False, index=combined.index)

    daily_drag = expense_ratio / 252.0
    synth_rets = 3.0 * qqq_close.pct_change() - daily_drag

    # Growth path over QQQ dates up to and including the anchor date, scaled
    # so the value AT the anchor equals the first real TQQQ close.
    pre_dates = qqq_close.index[qqq_close.index <= first_real]
    growth = (1.0 + synth_rets.reindex(pre_dates).fillna(0.0)).cumprod()
    synth = float(tqqq_close.iloc[0]) * growth / float(growth.iloc[-1])
    synth = synth.loc[synth.index < first_real]

    combined = pd.concat([synth, tqqq_close])
    combined.name = tqqq_close.name
    mask = pd.Series(combined.index < first_real, index=combined.index)
    return combined, mask
