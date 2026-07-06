"""Portfolio engine v2 tests: sleeve allocator, vol targeting, regime
leverage caps, Kelly estimator."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from jay_trading.data import models
from jay_trading.data.db import create_all, session_scope
from jay_trading.data.price_cache import upsert_bars
from jay_trading.risk import allocator, kelly
from jay_trading.strategies.base import PortfolioSnapshot, PositionView


def _pos(ticker: str, strategy: str, mv: float) -> PositionView:
    return PositionView(
        ticker=ticker, qty=1.0, avg_entry_price=mv, current_price=mv,
        market_value=mv, unrealized_pl=0.0, unrealized_plpc=0.0,
        strategy_name=strategy, hard_stop=None, trail_peak=None,
        trail_active=False, opened_at=None, entry_signal_id=None,
    )


def _snap(equity: float = 10_000.0, cash: float = 10_000.0,
          bp: float = 40_000.0, positions: list[PositionView] | None = None) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        equity=equity, cash=cash, buying_power=bp, positions=positions or []
    )


def _seed_low_vol_prices(ticker: str, days: int = 60) -> None:
    """Gently alternating series → tiny positive realized vol, so the
    vol-target scale clamps at VOL_SCALE_MAX. (Perfectly flat prices give
    rv == 0.0, which the allocator treats as no-data → scale 1.0.)"""
    create_all()
    today = date.today()
    rows = [
        {"date": (today - timedelta(days=i)).isoformat(),
         "close": 100.0 + (0.25 if i % 2 else 0.0)}
        for i in range(days)
    ]
    upsert_bars(ticker, rows)


# -- allocator ---------------------------------------------------------------


def test_sleeve_cap_full_risk_on_gives_budget() -> None:
    create_all()
    dec = allocator.sleeve_cap("smart_copy", _snap(), "FULL_RISK_ON")
    # 5% budget, no vol scaling policy, no positions → cap = 500, spend = 500.
    assert dec.cap_dollars == 500.0
    assert dec.max_spend == 500.0
    assert dec.per_position_cap_pct == 0.10


def test_sleeve_exposure_reduces_headroom() -> None:
    create_all()
    snap = _snap(positions=[_pos("AAPL", "smart_copy", 400.0)])
    dec = allocator.sleeve_cap("smart_copy", snap, "FULL_RISK_ON")
    assert dec.sleeve_exposure == 400.0
    assert dec.max_spend == 100.0  # 500 cap - 400 held


def test_crisis_regime_blocks_all_new_exposure() -> None:
    create_all()
    dec = allocator.sleeve_cap("s1_rotation", _snap(), "RISK_OFF_CRISIS")
    assert dec.max_spend == 0.0


def test_unknown_regime_uses_conservative_gross_cap() -> None:
    create_all()
    # gross cap 0.75x equity with unknown regime; a sleeve wanting 45% fits,
    # but existing gross of 7000 leaves only 500 headroom.
    snap = _snap(positions=[_pos("SPY", "other", 7_000.0)])
    dec = allocator.sleeve_cap("smart_copy", snap, None)
    assert dec.max_spend == 500.0  # min(sleeve 500, gross 7500-7000=500)


def test_full_risk_on_allows_margin_above_cash() -> None:
    """The 1.5x gross cap deliberately exceeds equity — margin in risk-on."""
    create_all()
    snap = _snap(equity=10_000.0, cash=1_000.0, bp=40_000.0)
    dec = allocator.sleeve_cap("s1_rotation", snap, "FULL_RISK_ON")
    # Sleeve budget 45% (vol targeting off per study verdict) = 4500;
    # gross headroom 15000; bp*0.95 = 38000 → sleeve binds at 4500,
    # comfortably above available cash: margin is usable.
    assert dec.max_spend == 4_500.0
    assert dec.max_spend > snap.cash


def test_vol_targeting_disabled_by_default_per_study_verdict() -> None:
    """vol_target_s1.py study: overlay is Sharpe-neutral but costs CAGR —
    target_vol must be None on every shipped sleeve."""
    for policy in allocator.SLEEVES.values():
        assert policy.target_vol is None


def test_vol_scale_machinery_still_works_when_enabled() -> None:
    """The DD-control knob stays tested: low-vol data + explicit target →
    scale clamps at VOL_SCALE_MAX; no data → 1.0."""
    create_all()
    _seed_low_vol_prices("TQQQ")
    policy = allocator.SleevePolicy(
        budget_pct=0.45, per_position_cap_pct=0.50,
        target_vol=0.45, vol_ticker="TQQQ",
    )
    assert allocator._vol_scale(policy, None) == allocator.VOL_SCALE_MAX
    no_data = allocator.SleevePolicy(
        budget_pct=0.45, per_position_cap_pct=0.50,
        target_vol=0.45, vol_ticker="NODATA",
    )
    assert allocator._vol_scale(no_data, None) == 1.0


# -- kelly --------------------------------------------------------------------


def _closed_trade(strategy: str, pnl: float) -> None:
    with session_scope() as s:
        s.add(
            models.Position(
                ticker="X", strategy_name=strategy, qty=1.0,
                avg_entry_price=100.0,
                opened_at=datetime.now(timezone.utc) - timedelta(days=5),
                closed_at=datetime.now(timezone.utc),
                exit_price=100.0 + pnl, realized_pnl=pnl,
                trail_active=False,
            )
        )


def test_kelly_none_below_min_trades() -> None:
    create_all()
    for _ in range(5):
        _closed_trade("smart_copy", 10.0)
    assert kelly.kelly_fraction("smart_copy", min_trades=20) is None


def test_kelly_none_when_no_losses() -> None:
    create_all()
    for _ in range(25):
        _closed_trade("smart_copy", 10.0)
    assert kelly.kelly_fraction("smart_copy", min_trades=20) is None


def test_kelly_half_fraction_math() -> None:
    create_all()
    # 15 wins of +20, 10 losses of -10: p=0.6, b=2.0
    # f* = 0.6 - 0.4/2 = 0.4 → half-Kelly 0.2
    for _ in range(15):
        _closed_trade("smart_copy", 20.0)
    for _ in range(10):
        _closed_trade("smart_copy", -10.0)
    assert kelly.kelly_fraction("smart_copy", min_trades=20) == 0.2


def test_kelly_negative_edge_returns_zero() -> None:
    create_all()
    # 10 wins of +10, 15 losses of -20: p=0.4, b=0.5 → f* = 0.4 - 1.2 < 0
    for _ in range(10):
        _closed_trade("smart_copy", 10.0)
    for _ in range(15):
        _closed_trade("smart_copy", -20.0)
    assert kelly.kelly_fraction("smart_copy", min_trades=20) == 0.0
