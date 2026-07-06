"""S3: crypto trend-following sleeve (redesign-2026-07-05 §M5).

Donchian-channel breakout on BTC and ETH, evaluated on daily FMP EOD
closes via the price_bars cache:

- Enter long when the last close exceeds the highest close of the prior
  ENTRY_LOOKBACK days.
- Exit when the last close drops below the lowest close of the prior
  EXIT_LOOKBACK days.

Runs on its own 7-day schedule (crypto never closes; the equity market-
clock gate must not apply — hence ``manages_out_of_band = True``, which
keeps the Mon–Fri ``manage_stops`` job from double-managing these
positions). Symbols are used WITHOUT the slash ("BTCUSD") everywhere:
Alpaca accepts both forms for orders but reports positions slashless, and
one canonical form keeps reconcile's strategy attribution working.

Parameters are the backtest-study verdict (scripts/backtest/studies/
crypto_trend.py, adversarially verified 2026-07-07): Donchian 55/20 on
50/50 BTC+ETH — Sharpe 1.57 vs B&H 1.10 (sqrt-365 convention), MaxDD
−44% vs −88%, 2022 return −23% vs −66%, H1-2026 DD −15% vs −47%,
turnover ~6.5×/yr so 25 bps costs barely dent it. The verifier's attacks
(ex-2017/2020 subwindows, 100 bps costs, +1-day lag) all failed to kill
it. Expectations should anchor on the post-2020 regime (Sharpe ~0.8–1.2),
not the 2017-inflated full-window CAGR.
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

UNIVERSE = ("BTCUSD", "ETHUSD")
# Donchian 55/20 per the verified study (see module docstring) — NOT 20/10,
# which had higher Sharpe but worse whipsaw/protection and 2.3x the turnover.
ENTRY_LOOKBACK = 55
EXIT_LOOKBACK = 20
PER_SYMBOL_PCT = 0.075  # 15% sleeve across 2 symbols; allocator binds further
MAX_SIGNAL_AGE_DAYS = 3  # crypto prints every day; staleness bites sooner


class CryptoMomentumStrategy(Strategy):
    name = "crypto_momentum"
    enabled = True
    shadow_mode = False
    max_concurrent_positions = 2
    #: Managed by the 7-day crypto job, not the Mon–Fri manage_stops loop.
    manages_out_of_band = True

    # ------------------------------------------------------------------ data

    def _refresh_history(self) -> None:
        from jay_trading.data.fmp import FMPClient
        from jay_trading.data.price_cache import ensure_history

        start = date.today() - timedelta(days=ENTRY_LOOKBACK * 3 + 20)
        fmp = FMPClient()
        try:
            for sym in UNIVERSE:
                ensure_history(fmp, sym, start)
        finally:
            try:
                fmp.close()
            except Exception:  # noqa: BLE001
                pass

    def _closes(self, symbol: str) -> list[float] | None:
        from jay_trading.data.price_cache import get_closes

        rows = get_closes(symbol, date.today() - timedelta(days=ENTRY_LOOKBACK * 3 + 20))
        if len(rows) < ENTRY_LOOKBACK + 1:
            log.warning("crypto_momentum: %d cached closes for %s (< %d) — no signal",
                        len(rows), symbol, ENTRY_LOOKBACK + 1)
            return None
        last_date = rows[-1][0]
        if (date.today() - last_date).days > MAX_SIGNAL_AGE_DAYS:
            log.warning("crypto_momentum: %s data stale (last %s) — no signal",
                        symbol, last_date)
            return None
        return [c for _, c in rows]

    # -------------------------------------------------------------- contract

    def generate_intents(
        self, signals: list[SignalView], portfolio: PortfolioSnapshot
    ) -> list[TradeIntent]:
        try:
            self._refresh_history()
        except Exception as e:  # noqa: BLE001
            log.warning("crypto_momentum: history refresh failed: %s", e)
        intents: list[TradeIntent] = []
        for sym in UNIVERSE:
            if portfolio.holds(sym):
                continue
            closes = self._closes(sym)
            if closes is None:
                continue
            last = closes[-1]
            entry_high = max(closes[-(ENTRY_LOOKBACK + 1):-1])
            if last > entry_high:
                intents.append(
                    TradeIntent(
                        strategy_name=self.name,
                        ticker=sym,
                        side="buy",
                        notional=round(portfolio.equity * PER_SYMBOL_PCT, 2),
                        time_in_force="gtc",  # crypto rejects DAY
                        rationale={
                            "rule": f"close > {ENTRY_LOOKBACK}d high (donchian)",
                            "entry_high": entry_high,
                            "last_close": last,
                        },
                        action="open",
                    )
                )
        return intents

    def manage_positions(
        self, positions: list[PositionView], portfolio: PortfolioSnapshot
    ) -> list[TradeIntent]:
        try:
            self._refresh_history()
        except Exception as e:  # noqa: BLE001
            log.warning("crypto_momentum: history refresh failed: %s", e)
        intents: list[TradeIntent] = []
        for p in positions:
            closes = self._closes(p.ticker.upper())
            if closes is None:
                continue
            last = closes[-1]
            exit_low = min(closes[-(EXIT_LOOKBACK + 1):-1])
            if last < exit_low:
                intents.append(
                    TradeIntent(
                        strategy_name=self.name,
                        ticker=p.ticker,
                        side="sell",
                        qty=abs(p.qty),
                        time_in_force="gtc",
                        rationale={
                            "exit_reason": f"close < {EXIT_LOOKBACK}d low (donchian)",
                            "exit_low": exit_low,
                            "last_close": last,
                        },
                        action="close",
                    )
                )
        return intents
