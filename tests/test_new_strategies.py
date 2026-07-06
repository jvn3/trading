"""S1 rotation + crypto momentum strategy logic tests (price fixtures via
the price_bars cache; FMP refresh monkeypatched out)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from jay_trading.data.db import create_all
from jay_trading.data.price_cache import upsert_bars
from jay_trading.strategies.base import PortfolioSnapshot, PositionView
from jay_trading.strategies.crypto_momentum import CryptoMomentumStrategy
from jay_trading.strategies.s1_rotation import MA_LEN, S1RotationStrategy


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(S1RotationStrategy, "_refresh_history", lambda self: None)
    monkeypatch.setattr(CryptoMomentumStrategy, "_refresh_history", lambda self: None)


def _snap(positions: list[PositionView] | None = None) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        equity=10_000.0, cash=10_000.0, buying_power=40_000.0,
        positions=positions or [],
    )


def _pos(ticker: str, strategy: str, qty: float = 10.0) -> PositionView:
    return PositionView(
        ticker=ticker, qty=qty, avg_entry_price=100.0, current_price=100.0,
        market_value=qty * 100.0, unrealized_pl=0.0, unrealized_plpc=0.0,
        strategy_name=strategy, hard_stop=None, trail_peak=None,
        trail_active=False, opened_at=None, entry_signal_id=None,
    )


def _seed_trend(ticker: str, *, last: float, rest: float, days: int) -> None:
    """days-1 closes at `rest`, then the most recent close at `last`.

    Weekend-safe: dates step back one calendar day at a time, so the newest
    bar is always today (never stale)."""
    create_all()
    today = date.today()
    rows = [
        {"date": (today - timedelta(days=i)).isoformat(),
         "close": last if i == 0 else rest}
        for i in range(days)
    ]
    upsert_bars(ticker, rows)


# -- S1 rotation ---------------------------------------------------------------


def test_s1_enters_tqqq_when_qqq_above_ma() -> None:
    _seed_trend("QQQ", last=120.0, rest=100.0, days=MA_LEN + 20)
    strat = S1RotationStrategy()
    intents = strat.generate_intents([], _snap())
    assert len(intents) == 1
    (i,) = intents
    assert i.ticker == "TQQQ" and i.side == "buy" and i.action == "open"
    assert i.notional == 4_500.0  # 45% sleeve upper bound; allocator binds later


def test_s1_no_entry_below_ma() -> None:
    _seed_trend("QQQ", last=80.0, rest=100.0, days=MA_LEN + 20)
    assert S1RotationStrategy().generate_intents([], _snap()) == []


def test_s1_no_entry_when_already_holding() -> None:
    _seed_trend("QQQ", last=120.0, rest=100.0, days=MA_LEN + 20)
    snap = _snap(positions=[_pos("TQQQ", "s1_rotation")])
    assert S1RotationStrategy().generate_intents([], snap) == []


def test_s1_no_signal_with_insufficient_data() -> None:
    _seed_trend("QQQ", last=120.0, rest=100.0, days=50)  # < MA_LEN
    assert S1RotationStrategy().generate_intents([], _snap()) == []


def test_s1_exits_when_qqq_crosses_below_ma() -> None:
    _seed_trend("QQQ", last=80.0, rest=100.0, days=MA_LEN + 20)
    snap = _snap(positions=[_pos("TQQQ", "s1_rotation", qty=45.0)])
    exits = S1RotationStrategy().manage_positions(snap.positions, snap)
    assert len(exits) == 1
    assert exits[0].side == "sell" and exits[0].qty == 45.0
    assert exits[0].action == "close"


def test_s1_holds_through_missing_data() -> None:
    """Unknown ≠ below: stale/absent data must not force an exit."""
    create_all()  # no QQQ bars at all
    snap = _snap(positions=[_pos("TQQQ", "s1_rotation")])
    assert S1RotationStrategy().manage_positions(snap.positions, snap) == []


# -- crypto momentum -------------------------------------------------------------


from jay_trading.strategies.crypto_momentum import ENTRY_LOOKBACK

_CRYPTO_DAYS = ENTRY_LOOKBACK + 10


def _seed_breakout(sym: str, *, breakout: bool) -> None:
    """Flat closes at 100, newest close 110 (breakout) or 95 (no breakout)."""
    _seed_trend(sym, last=110.0 if breakout else 95.0, rest=100.0, days=_CRYPTO_DAYS)


def test_crypto_enters_on_donchian_breakout() -> None:
    _seed_breakout("BTCUSD", breakout=True)
    _seed_breakout("ETHUSD", breakout=False)
    intents = CryptoMomentumStrategy().generate_intents([], _snap())
    assert [i.ticker for i in intents] == ["BTCUSD"]
    (i,) = intents
    assert i.time_in_force == "gtc"
    assert i.notional == 750.0  # 7.5% per symbol


def test_crypto_no_entry_when_holding() -> None:
    _seed_breakout("BTCUSD", breakout=True)
    snap = _snap(positions=[_pos("BTCUSD", "crypto_momentum")])
    intents = CryptoMomentumStrategy().generate_intents([], snap)
    assert intents == []


def test_crypto_exits_below_channel_low() -> None:
    # newest close 90 < min of prior EXIT_LOOKBACK closes (100)
    _seed_trend("BTCUSD", last=90.0, rest=100.0, days=_CRYPTO_DAYS)
    snap = _snap(positions=[_pos("BTCUSD", "crypto_momentum", qty=0.05)])
    exits = CryptoMomentumStrategy().manage_positions(snap.positions, snap)
    assert len(exits) == 1
    assert exits[0].side == "sell" and exits[0].time_in_force == "gtc"


def test_crypto_holds_inside_channel() -> None:
    # newest close 100 equals prior closes: neither breakout nor breakdown
    _seed_trend("BTCUSD", last=100.0, rest=100.0, days=_CRYPTO_DAYS)
    snap = _snap(positions=[_pos("BTCUSD", "crypto_momentum")])
    strat = CryptoMomentumStrategy()
    assert strat.manage_positions(snap.positions, snap) == []
    assert strat.generate_intents([], _snap()) == []


def test_crypto_marked_out_of_band() -> None:
    assert CryptoMomentumStrategy().manages_out_of_band is True
