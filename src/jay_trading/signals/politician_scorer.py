"""Compute a trailing-6-month "what-if-held" return score per politician.

Per the plan, this is a cheap quality gate, not a real backtest.  We take
every buy a politician filed in the trailing 6 months, look up the close on
``transaction_date`` (or nearest earlier trading day), and measure the
unrealized return to today.  Sells subtract.  Average across trades.

The score is cached per-politician in-memory for the lifetime of a single
process; price lookups are cached persistently in ``price_bars``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from typing import Iterable

from sqlalchemy import select

from jay_trading.data import models
from jay_trading.data.db import session_scope
from jay_trading.data.fmp import FMPClient
from jay_trading.data.price_cache import ensure_history, get_close_on_or_before

log = logging.getLogger(__name__)


@dataclass
class PoliticianScore:
    name: str
    trailing_6mo_return: float  # e.g. 0.08 = +8%
    n_trades: int
    quality_flag: bool  # True if return > 0


def _politicians_with_recent_trades(lookback_days: int) -> list[str]:
    since = date.today() - timedelta(days=lookback_days)
    with session_scope() as s:
        stmt = (
            select(models.DisclosedTrade.person_name)
            .where(models.DisclosedTrade.source.in_(("senate", "house")))
            .where(models.DisclosedTrade.filing_date >= since)
            .distinct()
        )
        return list(s.scalars(stmt))


def _trades_for(person_name: str, lookback_days: int) -> list[tuple[str, str, date]]:
    since = date.today() - timedelta(days=lookback_days)
    with session_scope() as s:
        stmt = (
            select(
                models.DisclosedTrade.ticker,
                models.DisclosedTrade.transaction_type,
                models.DisclosedTrade.transaction_date,
            )
            .where(models.DisclosedTrade.person_name == person_name)
            .where(models.DisclosedTrade.source.in_(("senate", "house")))
            .where(models.DisclosedTrade.transaction_date >= since)
        )
        return [(t, s_, d) for t, s_, d in s.execute(stmt).all()]


def score_politician(
    name: str,
    fmp: FMPClient | None = None,
    lookback_days: int = 180,
) -> PoliticianScore:
    """Compute one politician's trailing-6-month hypothetical return."""
    trades = _trades_for(name, lookback_days)
    if not trades:
        return PoliticianScore(name=name, trailing_6mo_return=0.0, n_trades=0, quality_flag=False)

    # Batch: ensure price history per unique ticker, once.
    tickers = {t for t, _, _ in trades}
    if fmp is None:
        fmp = FMPClient()
        own_client = True
    else:
        own_client = False
    try:
        oldest = min(d for _, _, d in trades)
        for t in tickers:
            ensure_history(fmp, t, start=oldest - timedelta(days=5))
    finally:
        if own_client:
            fmp.close()

    today = date.today()
    returns: list[float] = []
    for ticker, side, tx_date in trades:
        entry = get_close_on_or_before(ticker, tx_date)
        current = get_close_on_or_before(ticker, today)
        if entry is None or current is None or entry <= 0:
            continue
        ret = (current - entry) / entry
        if side == "sell":
            ret = -ret  # sells are bearish bets -- profit if price dropped
        returns.append(ret)

    if not returns:
        return PoliticianScore(name=name, trailing_6mo_return=0.0, n_trades=0, quality_flag=False)
    avg = sum(returns) / len(returns)
    return PoliticianScore(
        name=name,
        trailing_6mo_return=avg,
        n_trades=len(returns),
        quality_flag=avg > 0,
    )


def score_all(
    names: Iterable[str] | None = None,
    fmp: FMPClient | None = None,
    lookback_days: int = 180,
) -> dict[str, PoliticianScore]:
    """Return {name: PoliticianScore} for every politician with recent trades."""
    names_list = list(names) if names is not None else _politicians_with_recent_trades(
        lookback_days
    )
    own_client = fmp is None
    fmp = fmp or FMPClient()
    out: dict[str, PoliticianScore] = {}
    try:
        for n in names_list:
            try:
                out[n] = score_politician(n, fmp=fmp, lookback_days=lookback_days)
            except Exception as e:  # noqa: BLE001
                log.warning("scoring %s failed: %s", n, e)
                out[n] = PoliticianScore(n, 0.0, 0, False)
    finally:
        if own_client:
            fmp.close()
    return out


@lru_cache(maxsize=1)
def _committee_relevance_map() -> dict[str, frozenset[str]]:
    """Coarse committee → relevant-sector mapping. Hand-tuned; iterate later."""
    return {
        "armed services": frozenset({"LMT", "RTX", "NOC", "GD", "BA", "HII", "LHX", "TDY"}),
        "defense": frozenset({"LMT", "RTX", "NOC", "GD", "BA", "HII", "LHX", "TDY"}),
        "finance": frozenset({"JPM", "BAC", "GS", "MS", "WFC", "C", "USB", "PNC"}),
        "banking": frozenset({"JPM", "BAC", "GS", "MS", "WFC", "C", "USB", "PNC"}),
        "energy": frozenset({"XOM", "CVX", "COP", "EOG", "OXY", "MPC", "PSX", "VLO"}),
        "natural resources": frozenset({"XOM", "CVX", "COP", "EOG", "OXY"}),
        "agriculture": frozenset({"ADM", "DE", "CF", "MOS", "NTR"}),
        "health": frozenset({"UNH", "JNJ", "PFE", "LLY", "MRK", "ABBV", "BMY", "AMGN"}),
        "technology": frozenset({"MSFT", "AAPL", "GOOGL", "META", "NVDA", "AMZN", "ORCL"}),
        "transportation": frozenset({"UPS", "FDX", "UAL", "DAL", "AAL", "CSX", "UNP"}),
    }


def committee_is_relevant(committee: str | None, ticker: str) -> bool:
    """Fuzzy membership check of a ticker in a committee's relevant set."""
    if not committee:
        return False
    c = committee.lower()
    for key, tickers in _committee_relevance_map().items():
        if key in c and ticker.upper() in tickers:
            return True
    return False
