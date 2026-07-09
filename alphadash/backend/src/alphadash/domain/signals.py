"""Signal / candidate engine (S2.1) — deterministic idea generation. No LLM, no network.

Produces ``CandidateAction``s with numeric features from three rule families:

- ``rebalance``    — an asset class or position drifted above its cap → trim candidate.
- ``momentum``     — watchlist symbol with strong recent EOD momentum and headroom → buy candidate.
- ``take_profit``  — held position with large unrealized gain → trim candidate.

Every number that later appears in an explanation comes from ``features`` here — the LLM
(S2.3/S2.4) narrates these candidates; it never invents its own (faithfulness guarantee).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from alphadash.db.models import AssetClass, OrderSide
from alphadash.domain.risk import AccountState, RiskLimitSet

HUNDRED = Decimal("100")
TWO_DP = Decimal("0.01")

# Frozen thresholds (S2.1). Tuning these is an eval-driven exercise, not a code smell.
MOMENTUM_MIN_RETURN_PCT = Decimal("5")  # 20-bar return must exceed this
TAKE_PROFIT_MIN_GAIN_PCT = Decimal("25")  # unrealized gain triggering a trim candidate
REBALANCE_TOLERANCE_PCT = Decimal("1")  # drift beyond cap before a trim candidate fires
MAX_CANDIDATES = 5


@dataclass(frozen=True)
class CandidateAction:
    kind: str  # "rebalance" | "momentum" | "take_profit"
    symbol: str
    asset_class: AssetClass
    side: OrderSide
    features: dict[str, Decimal]  # numeric evidence — the ONLY numbers explanations may cite
    ref: str  # stable candidate_ref, e.g. "momentum:AAPL"

    def as_json(self) -> dict:
        return {
            "kind": self.kind,
            "symbol": self.symbol,
            "asset_class": self.asset_class.value,
            "side": self.side.value,
            "features": {k: str(v) for k, v in self.features.items()},
            "ref": self.ref,
        }


@dataclass(frozen=True)
class WatchItem:
    symbol: str
    asset_class: AssetClass


@dataclass(frozen=True)
class SignalInputs:
    state: AccountState
    limits: RiskLimitSet
    # symbol -> ordered daily closes, oldest→newest (from S0.3 bars; >= 21 entries to fire momentum)
    closes: dict[str, list[Decimal]] = field(default_factory=dict)
    watchlist: tuple[WatchItem, ...] = ()
    # symbol -> avg cost for held positions (unrealized-gain rule)
    avg_costs: dict[str, Decimal] = field(default_factory=dict)


def _pct(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == 0:
        return Decimal("0")
    return (numerator / denominator * HUNDRED).quantize(TWO_DP)


def generate_candidates(inputs: SignalInputs) -> list[CandidateAction]:
    """Deterministic: same inputs → same candidates in the same order."""
    state = inputs.state
    candidates: list[CandidateAction] = []

    # --- rebalance: asset-class exposure above cap ---
    if state.equity > 0:
        exposure: dict[AssetClass, Decimal] = {}
        for p in state.positions.values():
            exposure[p.asset_class] = exposure.get(p.asset_class, Decimal("0")) + p.market_value
        for asset_class in sorted(exposure, key=lambda a: a.value):
            cap = inputs.limits.max_asset_class_pct.get(asset_class.value)
            if cap is None:
                continue
            observed_pct = _pct(exposure[asset_class], state.equity)
            if observed_pct > cap + REBALANCE_TOLERANCE_PCT:
                # Trim the largest position in the class (deterministic tie-break by symbol)
                largest = max(
                    (p for p in state.positions.values() if p.asset_class is asset_class),
                    key=lambda p: (p.market_value, p.symbol),
                )
                candidates.append(
                    CandidateAction(
                        kind="rebalance",
                        symbol=largest.symbol,
                        asset_class=asset_class,
                        side=OrderSide.sell,
                        features={
                            "class_allocation_pct": observed_pct,
                            "class_cap_pct": cap,
                            "excess_pct": (observed_pct - cap).quantize(TWO_DP),
                            "position_value": largest.market_value,
                        },
                        ref=f"rebalance:{asset_class.value}:{largest.symbol}",
                    )
                )

    # --- take_profit: large unrealized gains ---
    for symbol in sorted(state.positions):
        p = state.positions[symbol]
        avg_cost = inputs.avg_costs.get(symbol)
        if not avg_cost or avg_cost <= 0 or p.quantity <= 0:
            continue
        current_price = p.market_value / p.quantity
        gain_pct = _pct(current_price - avg_cost, avg_cost)
        if gain_pct >= TAKE_PROFIT_MIN_GAIN_PCT:
            candidates.append(
                CandidateAction(
                    kind="take_profit",
                    symbol=symbol,
                    asset_class=p.asset_class,
                    side=OrderSide.sell,
                    features={
                        "unrealized_gain_pct": gain_pct,
                        "avg_cost": avg_cost.quantize(TWO_DP),
                        "current_price": current_price.quantize(TWO_DP),
                        "position_value": p.market_value,
                    },
                    ref=f"take_profit:{symbol}",
                )
            )

    # --- momentum: watchlist strength (buys only when not paused/drawdown-blocked) ---
    buys_allowed = not state.paused and (
        inputs.limits.drawdown_pause_pct is None
        or state.drawdown_pct < inputs.limits.drawdown_pause_pct
    )
    if buys_allowed:
        for item in sorted(inputs.watchlist, key=lambda w: w.symbol):
            closes = inputs.closes.get(item.symbol, [])
            if len(closes) < 21:
                continue
            last, prior = closes[-1], closes[-21]
            if prior <= 0:
                continue
            return_pct = _pct(last - prior, prior)
            if return_pct < MOMENTUM_MIN_RETURN_PCT:
                continue
            high = max(closes)
            candidates.append(
                CandidateAction(
                    kind="momentum",
                    symbol=item.symbol,
                    asset_class=item.asset_class,
                    side=OrderSide.buy,
                    features={
                        "return_20d_pct": return_pct,
                        "last_close": last,
                        "distance_from_high_pct": _pct(high - last, high),
                    },
                    ref=f"momentum:{item.symbol}",
                )
            )

    return candidates[:MAX_CANDIDATES]
