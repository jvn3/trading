"""What-if simulator (S4.3) — pure, deterministic scenario math over a portfolio snapshot.

Two questions a beginner actually asks, answered without placing anything:

- **Shock**: "what happens to MY portfolio if stocks drop 20% / crypto halves / AAPL -50%?"
  Applies per-asset-class shocks (with optional per-symbol overrides) to current positions and
  reports the damage in the same terms the safety rules use — including whether the move would
  trip the drawdown auto-pause.
- **Trade preview**: "what would buying X do?" — post-trade cash/allocation plus the S1.3 risk
  gate's verdict, using the exact same ``validate_order`` the real order path uses (parity by
  construction, not by copy).

No LLM, no network, no persistence. Read-only teaching math.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from alphadash.db.models import AssetClass, OrderSide
from alphadash.domain.risk import (
    AccountState,
    Decision,
    OrderIntent,
    RiskLimitSet,
    validate_order,
)

ZERO = Decimal("0")
HUNDRED = Decimal("100")
TWO_DP = Decimal("0.01")

MIN_SHOCK, MAX_SHOCK = Decimal("-95"), Decimal("100")


class ScenarioError(ValueError):
    """Invalid scenario inputs. Message is safe to show the user."""


@dataclass(frozen=True)
class ShockScenario:
    """Percent moves. -20 means 'falls 20%'. Overrides win over the class shock."""

    equity_pct: Decimal = ZERO
    crypto_pct: Decimal = ZERO
    symbol_overrides: dict[str, Decimal] | None = None

    def validated(self) -> ShockScenario:
        for name, value in (("equity_pct", self.equity_pct), ("crypto_pct", self.crypto_pct)):
            if not (MIN_SHOCK <= value <= MAX_SHOCK):
                raise ScenarioError(f"{name} must be between {MIN_SHOCK} and {MAX_SHOCK}")
        for symbol, value in (self.symbol_overrides or {}).items():
            if not (MIN_SHOCK <= value <= MAX_SHOCK):
                raise ScenarioError(
                    f"override for {symbol} must be between {MIN_SHOCK} and {MAX_SHOCK}"
                )
        return self


@dataclass(frozen=True)
class PositionImpact:
    symbol: str
    asset_class: str
    value_before: Decimal
    value_after: Decimal
    applied_pct: Decimal


@dataclass(frozen=True)
class ShockImpact:
    equity_before: Decimal
    equity_after: Decimal
    equity_change_pct: Decimal
    cash: Decimal  # cash is unshocked by construction — that's the lesson
    positions: tuple[PositionImpact, ...]
    allocation_after_pct: dict[str, Decimal]
    would_trip_drawdown_pause: bool
    drawdown_pause_pct: Decimal | None


def apply_shock(state: AccountState, scenario: ShockScenario, limits: RiskLimitSet) -> ShockImpact:
    scenario = scenario.validated()
    overrides = {k.upper(): v for k, v in (scenario.symbol_overrides or {}).items()}
    class_shock = {
        AssetClass.equity: scenario.equity_pct,
        AssetClass.crypto: scenario.crypto_pct,
    }

    impacts: list[PositionImpact] = []
    total_after = state.cash
    for symbol in sorted(state.positions):
        p = state.positions[symbol]
        pct = overrides.get(symbol.upper(), class_shock.get(p.asset_class, ZERO))
        after = (p.market_value * (HUNDRED + pct) / HUNDRED).quantize(TWO_DP)
        impacts.append(
            PositionImpact(
                symbol=p.symbol,
                asset_class=p.asset_class.value,
                value_before=p.market_value,
                value_after=after,
                applied_pct=pct,
            )
        )
        total_after += after

    change_pct = (
        ((total_after / state.equity - 1) * HUNDRED).quantize(TWO_DP) if state.equity > 0 else ZERO
    )

    allocation: dict[str, Decimal] = {}
    if total_after > 0:
        by_class: dict[str, Decimal] = {}
        for impact in impacts:
            by_class[impact.asset_class] = (
                by_class.get(impact.asset_class, ZERO) + impact.value_after
            )
        for cls, value in by_class.items():
            allocation[cls] = (value / total_after * HUNDRED).quantize(TWO_DP)
        allocation["cash"] = (state.cash / total_after * HUNDRED).quantize(TWO_DP)

    # Would this move trip the auto-pause? Drawdown here = the scenario's own drop from the
    # CURRENT equity (conservative: assumes you were at peak — the honest worst framing).
    scenario_drawdown = -change_pct if change_pct < 0 else ZERO
    trips = limits.drawdown_pause_pct is not None and scenario_drawdown >= limits.drawdown_pause_pct

    return ShockImpact(
        equity_before=state.equity,
        equity_after=total_after.quantize(TWO_DP),
        equity_change_pct=change_pct,
        cash=state.cash,
        positions=tuple(impacts),
        allocation_after_pct=allocation,
        would_trip_drawdown_pause=trips,
        drawdown_pause_pct=limits.drawdown_pause_pct,
    )


@dataclass(frozen=True)
class TradePreview:
    decision: Decision
    cash_after: Decimal
    position_value_after: Decimal
    position_allocation_after_pct: Decimal
    cash_allocation_after_pct: Decimal


def preview_trade(
    state: AccountState,
    limits: RiskLimitSet,
    *,
    symbol: str,
    asset_class: AssetClass,
    side: OrderSide,
    qty: Decimal,
    price: Decimal,
) -> TradePreview:
    """Risk-gate verdict + post-trade shape WITHOUT touching the book.

    Uses the real ``validate_order`` — the preview can never disagree with the order path.
    """
    intent = OrderIntent(
        symbol=symbol.upper(), asset_class=asset_class, side=side, qty=qty, price=price
    )
    decision = validate_order(intent, state, limits)

    notional = qty * price
    held = state.positions.get(intent.symbol)
    held_value = held.market_value if held else ZERO
    if side is OrderSide.buy:
        cash_after = state.cash - notional
        position_after = held_value + notional
    else:
        cash_after = state.cash + notional
        position_after = max(ZERO, held_value - notional)

    equity = state.equity  # a marked-to-market trade doesn't change total equity
    return TradePreview(
        decision=decision,
        cash_after=cash_after.quantize(TWO_DP),
        position_value_after=position_after.quantize(TWO_DP),
        position_allocation_after_pct=(
            (position_after / equity * HUNDRED).quantize(TWO_DP) if equity > 0 else ZERO
        ),
        cash_allocation_after_pct=(
            (cash_after / equity * HUNDRED).quantize(TWO_DP) if equity > 0 else ZERO
        ),
    )
