"""Tests for the Strategy V macro regime classifier."""
from __future__ import annotations

import pytest

from jay_trading.risk.macro_regime import (
    MacroInputs,
    MacroRegime,
    SIZING_MULTIPLIER,
    classify,
    score_curve,
    score_spy,
    score_vix,
    sizing_multiplier,
)


# ---- Fixtures: one MacroInputs per regime --------------------------------

# Numbers chosen to mirror plausible market states; the absolute levels
# matter less than the *relationships* the scorers test for.

FULL_RISK_ON_INPUTS = MacroInputs(
    spy_price=520.0, spy_ma50=505.0, spy_ma200=480.0,    # above both MAs, golden cross
    vix_spot=14.0, vix_ma20=15.0,                         # low + falling
    t10y2y=0.55,                                          # normal, steep
)

MODERATE_RISK_ON_FROM_VIX_INPUTS = MacroInputs(
    spy_price=520.0, spy_ma50=505.0, spy_ma200=480.0,    # SPY healthy
    vix_spot=22.0, vix_ma20=20.0,                         # 20-25 and rising → vix score -0.5
    t10y2y=0.55,
)

DEFENSIVE_INPUTS = MacroInputs(
    spy_price=470.0, spy_ma50=480.0, spy_ma200=485.0,    # below both MAs, no golden cross
    vix_spot=22.0, vix_ma20=21.0,                         # 20-25, not strongly rising
    t10y2y=0.10,
)

CRISIS_INPUTS = MacroInputs(
    spy_price=400.0, spy_ma50=460.0, spy_ma200=470.0,    # spy_score = -1.0
    vix_spot=42.0, vix_ma20=20.0,                         # >30 → vix_score = -1.0
    t10y2y=-0.50,                                         # deeply inverted
)


# ---- Component scorer tests ---------------------------------------------


def test_score_spy_full_uptrend() -> None:
    assert score_spy(FULL_RISK_ON_INPUTS) == 1.0


def test_score_spy_full_breakdown_returns_minus_one() -> None:
    inp = MacroInputs(
        spy_price=470.0, spy_ma50=475.0, spy_ma200=485.0,
        vix_spot=18, vix_ma20=18, t10y2y=0.5,
    )
    # below all: not above_200, not above_50, death cross → -1.0
    assert score_spy(inp) == -1.0


def test_score_spy_below_200_but_above_50_returns_minus_half() -> None:
    inp = MacroInputs(
        spy_price=478.0, spy_ma50=475.0, spy_ma200=485.0,
        vix_spot=18, vix_ma20=18, t10y2y=0.5,
    )
    # below 200, above 50 (death cross still) → -0.5 fallback branch
    assert score_spy(inp) == -0.5


def test_score_spy_above_200_but_below_50() -> None:
    inp = MacroInputs(
        spy_price=482.0, spy_ma50=485.0, spy_ma200=480.0,
        vix_spot=18, vix_ma20=18, t10y2y=0.5,
    )
    # above 200 but below 50 → +0.5
    assert score_spy(inp) == 0.5


def test_score_vix_calm() -> None:
    inp = MacroInputs(
        spy_price=500, spy_ma50=500, spy_ma200=500,
        vix_spot=14.0, vix_ma20=15.0, t10y2y=0.5,
    )
    assert score_vix(inp) == 1.0


def test_score_vix_rising_threshold_uses_5pct_buffer() -> None:
    # spot exactly equal to 1.05 × MA → not "rising" (we use strict >)
    inp = MacroInputs(
        spy_price=500, spy_ma50=500, spy_ma200=500,
        vix_spot=21.0, vix_ma20=20.0, t10y2y=0.5,
    )
    # 21.0 > 1.05 * 20 = 21.0 → False (strict). spot < 25 and not rising → +0.5
    assert score_vix(inp) == 0.5

    # Bump spot just above the threshold → now rising, score drops.
    inp2 = MacroInputs(
        spy_price=500, spy_ma50=500, spy_ma200=500,
        vix_spot=21.5, vix_ma20=20.0, t10y2y=0.5,
    )
    assert score_vix(inp2) == -0.5


def test_score_vix_crisis() -> None:
    inp = MacroInputs(
        spy_price=500, spy_ma50=500, spy_ma200=500,
        vix_spot=35.0, vix_ma20=20.0, t10y2y=0.5,
    )
    assert score_vix(inp) == -1.0


def test_score_curve_normal_to_inverted() -> None:
    base = dict(spy_price=500, spy_ma50=500, spy_ma200=500, vix_spot=18, vix_ma20=18)
    assert score_curve(MacroInputs(**base, t10y2y=0.6)) == 1.0
    assert score_curve(MacroInputs(**base, t10y2y=0.2)) == 0.5
    assert score_curve(MacroInputs(**base, t10y2y=-0.10)) == -0.5
    assert score_curve(MacroInputs(**base, t10y2y=-0.50)) == -1.0


# ---- Top-level classify() tests -----------------------------------------


def test_classify_full_risk_on() -> None:
    res = classify(FULL_RISK_ON_INPUTS)
    assert res.regime is MacroRegime.FULL_RISK_ON
    assert res.spy_score == 1.0
    assert res.vix_score == 1.0
    assert res.curve_score == 1.0


def test_classify_moderate_when_vix_only_partially_safe() -> None:
    res = classify(MODERATE_RISK_ON_FROM_VIX_INPUTS)
    assert res.regime is MacroRegime.MODERATE_RISK_ON


def test_classify_defensive_when_spy_below_200() -> None:
    res = classify(DEFENSIVE_INPUTS)
    assert res.regime is MacroRegime.RISK_OFF_DEFENSIVE


def test_classify_crisis_requires_both_spy_and_vix_at_minus_one() -> None:
    res = classify(CRISIS_INPUTS)
    assert res.regime is MacroRegime.RISK_OFF_CRISIS


def test_classify_inverted_curve_alone_does_not_trip_crisis() -> None:
    # SPY healthy + low VIX + deeply inverted curve → MODERATE, not CRISIS.
    # The 2020s anomaly: inversion has been a weak bear signal.
    inp = MacroInputs(
        spy_price=520, spy_ma50=505, spy_ma200=480,
        vix_spot=14, vix_ma20=15,
        t10y2y=-0.80,
    )
    res = classify(inp)
    assert res.regime is MacroRegime.MODERATE_RISK_ON
    assert res.curve_score == -1.0


def test_classify_raw_inputs_round_trip() -> None:
    res = classify(FULL_RISK_ON_INPUTS)
    assert res.raw["spy_price"] == 520.0
    assert res.raw["t10y2y"] == 0.55
    assert res.raw["vix_rising"] is False


# ---- sizing_multiplier --------------------------------------------------


@pytest.mark.parametrize("regime,expected", list(SIZING_MULTIPLIER.items()))
def test_sizing_multiplier_each_regime(regime: MacroRegime, expected: float) -> None:
    assert sizing_multiplier(regime) == expected
    # Wire-string form must agree with enum form.
    assert sizing_multiplier(regime.value) == expected


def test_sizing_multiplier_none_fails_open() -> None:
    assert sizing_multiplier(None) == 1.0


def test_sizing_multiplier_unknown_string_fails_open() -> None:
    assert sizing_multiplier("BOGUS_REGIME") == 1.0
