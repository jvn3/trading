"""S1: regime-gated leveraged-ETF rotation (redesign-2026-07-05 §M3).

Rules — deliberately IDENTICAL to the backtested variant in
``scripts/backtest/strategies/s1_rotation.py`` (tqqq variant), which beat
QQQ buy-and-hold on CAGR in every walk-forward window (train 21.9% vs
13.6%, validate 63.1% vs 33.3%, 2026-YTD holdout 77.5% vs 41.0%; MaxDD
−56% vs −35%, 10 bps costs):

- QQQ close > 200-day SMA  → hold TQQQ (one position, sleeve-sized).
- QQQ close <= 200-day SMA → hold cash (close TQQQ).

No other exits. The −8%-style stop of the cluster strategies is
intentionally absent — the MA cross IS the exit, per the backtest. Sizing
is delegated to risk/allocator.py (45% sleeve budget × vol targeting ×
regime gross-leverage cap); the notional this strategy proposes is only
the sleeve budget upper bound.

Signal data: FMP EOD closes via the price_bars cache, refreshed at intent
time. Stale/missing data (> MAX_SIGNAL_AGE_DAYS old) → do nothing, loudly.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from jay_trading.strategies.base import (
    PortfolioSnapshot,
    PositionView,
    SignalView,
    Strategy,
    TradeIntent,
)

log = logging.getLogger(__name__)

SIGNAL_TICKER = "QQQ"
TRADE_TICKER = "TQQQ"
MA_LEN = 200
SLEEVE_PCT = 0.45  # upper bound only; allocator applies the binding caps
MAX_SIGNAL_AGE_DAYS = 7


class S1RotationStrategy(Strategy):
    name = "s1_rotation"
    enabled = True
    shadow_mode = False
    max_concurrent_positions = 1

    # ------------------------------------------------------------------ data

    def _refresh_history(self) -> None:
        """Best-effort refresh of QQQ/TQQQ closes into the price cache."""
        from jay_trading.data.fmp import FMPClient
        from jay_trading.data.price_cache import ensure_history

        start = date.today() - timedelta(days=int(MA_LEN * 1.7) + 30)
        fmp = FMPClient()
        try:
            ensure_history(fmp, SIGNAL_TICKER, start)
            ensure_history(fmp, TRADE_TICKER, start)
        finally:
            try:
                fmp.close()
            except Exception:  # noqa: BLE001
                pass

    def _above_ma(self) -> bool | None:
        """True/False for QQQ vs its 200d SMA; None when data is unusable."""
        from jay_trading.data.price_cache import get_closes

        closes = get_closes(
            SIGNAL_TICKER, date.today() - timedelta(days=int(MA_LEN * 1.7) + 30)
        )
        if len(closes) < MA_LEN:
            log.warning(
                "s1_rotation: only %d cached %s closes (< %d) — no signal",
                len(closes), SIGNAL_TICKER, MA_LEN,
            )
            return None
        last_date, last_close = closes[-1]
        if (date.today() - last_date).days > MAX_SIGNAL_AGE_DAYS:
            log.warning(
                "s1_rotation: last %s close is %s (stale) — no signal",
                SIGNAL_TICKER, last_date,
            )
            return None
        window = [c for _, c in closes[-MA_LEN:]]
        sma = sum(window) / len(window)
        return last_close > sma

    # -------------------------------------------------------------- contract

    def generate_intents(
        self, signals: list[SignalView], portfolio: PortfolioSnapshot
    ) -> list[TradeIntent]:
        # Price-driven: ignores the signals table entirely.
        try:
            self._refresh_history()
        except Exception as e:  # noqa: BLE001
            log.warning("s1_rotation: history refresh failed: %s", e)
        above = self._above_ma()
        if above is None or not above:
            return []
        if portfolio.holds(TRADE_TICKER):
            return []
        notional = round(portfolio.equity * SLEEVE_PCT, 2)
        return [
            TradeIntent(
                strategy_name=self.name,
                ticker=TRADE_TICKER,
                side="buy",
                notional=notional,
                rationale={
                    "rule": f"{SIGNAL_TICKER} close > {MA_LEN}d SMA",
                    "sleeve_pct": SLEEVE_PCT,
                },
                action="open",
            )
        ]

    def manage_positions(
        self, positions: list[PositionView], portfolio: PortfolioSnapshot
    ) -> list[TradeIntent]:
        mine = [p for p in positions if p.ticker.upper() == TRADE_TICKER]
        if not mine:
            return []
        try:
            self._refresh_history()
        except Exception as e:  # noqa: BLE001
            log.warning("s1_rotation: history refresh failed: %s", e)
        above = self._above_ma()
        if above is None or above:
            # Stale data intentionally does NOT force an exit: the MA exit is
            # a trend signal, not a stop. Unknown ≠ below.
            return []
        return [
            TradeIntent(
                strategy_name=self.name,
                ticker=p.ticker,
                side="sell",
                qty=abs(p.qty),
                rationale={"exit_reason": f"{SIGNAL_TICKER} close <= {MA_LEN}d SMA"},
                action="close",
            )
            for p in mine
        ]
