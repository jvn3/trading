"""Strategy V — Macro Regime Switcher.

Classifies the portfolio's risk posture from three macro inputs:

1. **SPY trend**     — current vs 200d MA, 50d MA, golden-cross state.
2. **VIX level+trend** — spot VIX and ``vix > 1.05 × vix_20ma``.
3. **Yield curve**   — ``T10Y2Y`` from FRED; negative = inverted.

It outputs one of four :class:`MacroRegime` values and a per-input component
score (in ``[-1, 1]``, positive = risk-on). The executor translates the
regime to a ``sizing_multiplier`` and applies it to every strategy's per-trade
notional. A ``RISK_OFF_CRISIS`` regime blocks new entries entirely; exits are
never blocked.

The v1 scope dropped the fourth addendum input (congressional sector flow) —
see ``development/log.md`` 2026-04-20 23:55 ET for the decision trail.

This module is **pure** — no I/O. ``classify_live`` in the job layer wires
FMP + FRED clients and calls ``classify``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

log = logging.getLogger(__name__)


# -- Regime + sizing map ---------------------------------------------------


class MacroRegime(str, Enum):
    """Four-level ladder from offense to crisis.

    The string values are the canonical wire form stored in
    ``macro_regime_snapshots.regime`` and referenced in sizing logic.
    """

    FULL_RISK_ON = "FULL_RISK_ON"
    MODERATE_RISK_ON = "MODERATE_RISK_ON"
    RISK_OFF_DEFENSIVE = "RISK_OFF_DEFENSIVE"
    RISK_OFF_CRISIS = "RISK_OFF_CRISIS"


#: Per-regime multiplier applied to each strategy's target notional. ``0.0``
#: means "reject all new opens" — the executor short-circuits there. Close /
#: exit intents are **never** scaled by this map.
SIZING_MULTIPLIER: dict[MacroRegime, float] = {
    MacroRegime.FULL_RISK_ON: 1.00,
    MacroRegime.MODERATE_RISK_ON: 0.75,
    MacroRegime.RISK_OFF_DEFENSIVE: 0.50,
    MacroRegime.RISK_OFF_CRISIS: 0.00,
}


def sizing_multiplier(regime: MacroRegime | str | None) -> float:
    """Map a regime (enum or wire string) to its sizing multiplier.

    Unknown / ``None`` → ``1.0`` (fail-open, matching gate-fail behavior
    elsewhere in the risk layer). The executor logs a warning if the regime
    snapshot is missing so this fail-open is visible.
    """
    if regime is None:
        return 1.0
    try:
        key = regime if isinstance(regime, MacroRegime) else MacroRegime(regime)
    except ValueError:
        log.warning("unknown macro regime %r — falling back to 1.0", regime)
        return 1.0
    return SIZING_MULTIPLIER[key]


# -- Input dataclasses + result -------------------------------------------


@dataclass(frozen=True)
class MacroInputs:
    """Cleaned numeric inputs feeding :func:`classify`.

    All three inputs are required. Callers that cannot fetch a value should
    refuse to classify rather than guess; we prefer a missing snapshot over
    a wrong one.
    """

    # SPY trend
    spy_price: float
    spy_ma50: float
    spy_ma200: float
    # VIX level + trend
    vix_spot: float
    vix_ma20: float
    # Yield curve
    t10y2y: float  # percentage points; negative = inverted


@dataclass(frozen=True)
class Classification:
    """Output of :func:`classify`. Serialized into the snapshot row."""

    regime: MacroRegime
    spy_score: float
    vix_score: float
    curve_score: float
    raw: dict[str, Any] = field(default_factory=dict)


# -- Component scorers -----------------------------------------------------


def score_spy(inputs: MacroInputs) -> float:
    """Score SPY trend in ``[-1, 1]``.

    +1.0  → above 200MA AND golden cross AND above 50MA (strong up-trend)
    +0.5  → above 200MA, one of the other two fails
    -0.5  → below 200MA but not both legs broken
    -1.0  → below both 50MA and 200MA and death cross
    """
    above_200 = inputs.spy_price > inputs.spy_ma200
    above_50 = inputs.spy_price > inputs.spy_ma50
    golden = inputs.spy_ma50 > inputs.spy_ma200

    if above_200 and above_50 and golden:
        return 1.0
    if above_200:
        return 0.5
    if not above_50 and not golden:
        return -1.0
    return -0.5


def score_vix(inputs: MacroInputs) -> float:
    """Score VIX in ``[-1, 1]``.

    +1.0 → spot < 20 AND not rising (spot <= 1.05 × 20d MA)
    +0.5 → spot 20–25 AND not rising
    -0.5 → spot 25–30 OR rising above 20
    -1.0 → spot > 30 (crisis-level implied vol)
    """
    rising = inputs.vix_spot > 1.05 * inputs.vix_ma20

    if inputs.vix_spot > 30:
        return -1.0
    if inputs.vix_spot < 20 and not rising:
        return 1.0
    if inputs.vix_spot < 25 and not rising:
        return 0.5
    if inputs.vix_spot > 25:
        return -0.5
    # 20–25 AND rising → mild negative
    return -0.5 if rising else 0.5


def score_curve(inputs: MacroInputs) -> float:
    """Score the T10Y2Y yield curve in ``[-1, 1]``.

    Note: the 2020s proved yield-curve inversion is less predictive than in
    prior decades (SPY rose ~40% through a 541-day inversion, per the Phase 5
    research pass). We weight it accordingly — inversion is a tilt, not a veto.

    +1.0 → spread > 0.5 (normal, steepening)
    +0.5 → spread 0.0 to 0.5 (flat but positive)
    -0.5 → spread -0.25 to 0 (mildly inverted)
    -1.0 → spread <= -0.25 (deeply inverted)
    """
    s = inputs.t10y2y
    if s > 0.5:
        return 1.0
    if s > 0.0:
        return 0.5
    if s > -0.25:
        return -0.5
    return -1.0


# -- Main classifier -------------------------------------------------------


def classify(inputs: MacroInputs) -> Classification:
    """Combine three component scores into a :class:`MacroRegime`.

    Rules (evaluated in order — first match wins):

    1. If SPY and VIX are both -1 (below both MAs + crisis vol) → CRISIS.
    2. If SPY is negative (any sub-200MA reading) → DEFENSIVE. The addendum
       calls this "Below 200MA, vol stable" — even calm VIX doesn't excuse a
       broken trend.
    3. If SPY is +1 and VIX is +1 and curve is non-negative → FULL.
    4. Otherwise → MODERATE.

    The curve score never pushes us into CRISIS on its own — inversion has
    been a weak bear signal in the 2020s. It can push FULL → MODERATE (rule 3
    fails when ``curve_score < 0``).
    """
    spy = score_spy(inputs)
    vix = score_vix(inputs)
    curve = score_curve(inputs)

    if spy <= -1.0 and vix <= -1.0:
        regime = MacroRegime.RISK_OFF_CRISIS
    elif spy < 0:
        regime = MacroRegime.RISK_OFF_DEFENSIVE
    elif spy >= 1.0 and vix >= 1.0 and curve >= 0:
        regime = MacroRegime.FULL_RISK_ON
    else:
        regime = MacroRegime.MODERATE_RISK_ON

    raw = {
        "spy_price": inputs.spy_price,
        "spy_ma50": inputs.spy_ma50,
        "spy_ma200": inputs.spy_ma200,
        "vix_spot": inputs.vix_spot,
        "vix_ma20": inputs.vix_ma20,
        "vix_rising": inputs.vix_spot > 1.05 * inputs.vix_ma20,
        "t10y2y": inputs.t10y2y,
    }
    return Classification(
        regime=regime,
        spy_score=spy,
        vix_score=vix,
        curve_score=curve,
        raw=raw,
    )


# -- Live wiring (fetches + stores) ---------------------------------------


def gather_inputs(*, fmp: Any, fred: Any) -> MacroInputs:
    """Pull the three macro inputs from their live sources.

    - SPY price + 200MA: FMP ``/stable/quote`` (``price`` + ``priceAvg200``,
      ``priceAvg50``).
    - VIX spot: FMP ``/stable/quote?symbol=^VIX``.
    - VIX 20d MA: FRED ``VIXCLS`` last 20 non-null observations, averaged.
    - T10Y2Y: FRED latest observation.

    Raises ``RuntimeError`` if any input is unavailable — a missing snapshot
    is safer than a wrong one.
    """
    # SPY trend inputs
    spy_quote = fmp.request("quote", params={"symbol": "SPY"})
    if not isinstance(spy_quote, list) or not spy_quote:
        raise RuntimeError("macro_regime: SPY quote empty")
    row = spy_quote[0]
    spy_price = float(row.get("price") or 0.0)
    spy_ma50 = float(row.get("priceAvg50") or 0.0)
    spy_ma200 = float(row.get("priceAvg200") or 0.0)
    if spy_price <= 0 or spy_ma50 <= 0 or spy_ma200 <= 0:
        raise RuntimeError(
            f"macro_regime: SPY zero/missing (price={spy_price} "
            f"ma50={spy_ma50} ma200={spy_ma200})"
        )

    # VIX spot (FMP)
    vix_quote = fmp.request("quote", params={"symbol": "^VIX"})
    if not isinstance(vix_quote, list) or not vix_quote:
        raise RuntimeError("macro_regime: ^VIX quote empty")
    vix_spot = float(vix_quote[0].get("price") or 0.0)
    if vix_spot <= 0:
        raise RuntimeError(f"macro_regime: VIX spot invalid ({vix_spot})")

    # VIX 20d MA (FRED VIXCLS)
    from jay_trading.data.fred import moving_average, series_values

    vix_series = fred.get_series("VIXCLS")
    ma20 = moving_average(series_values(vix_series), 20)
    if ma20 is None or ma20 <= 0:
        raise RuntimeError("macro_regime: VIXCLS MA20 unavailable")

    # Yield curve (FRED T10Y2Y)
    t10y2y_obs = fred.latest("T10Y2Y")
    if t10y2y_obs is None or t10y2y_obs.value is None:
        raise RuntimeError("macro_regime: T10Y2Y latest missing")

    return MacroInputs(
        spy_price=spy_price,
        spy_ma50=spy_ma50,
        spy_ma200=spy_ma200,
        vix_spot=vix_spot,
        vix_ma20=float(ma20),
        t10y2y=float(t10y2y_obs.value),
    )
