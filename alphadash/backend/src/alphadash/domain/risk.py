"""Risk & guardrail service (S1.3) — deterministic, pure, hard veto.

``validate_order`` is the single gate every order passes through. It runs AFTER any AI proposal
(S2.3) and BEFORE execution (S1.5). No LLM, no network, no clock: everything it needs arrives as
arguments. It returns *all* violations, not just the first — a veto is educational.

Frozen semantics per ``RiskLimitType``:
- ``max_position_pct``      buy: post-trade position value / equity ≤ limit
- ``max_asset_class_pct``   buy: post-trade asset-class exposure / equity ≤ limit (per class)
- ``max_trades_per_week``   any side: trades_this_week + 1 ≤ limit
- ``cash_floor_pct``        buy: post-trade cash / equity ≥ limit
- ``per_suggestion_max_pct``buy: order notional / equity ≤ limit
- ``drawdown_pause_pct``    current drawdown ≥ limit blocks BUYS (sells stay allowed — de-risking
                            is never trapped); an explicitly paused account blocks buys likewise.
Structural invariants (always on): qty > 0, price > 0, sells never exceed held quantity
(no shorting), buys never exceed available cash.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from alphadash.db.models import AssetClass, OrderSide, RiskLimitType

HUNDRED = Decimal("100")


@dataclass(frozen=True)
class PositionState:
    symbol: str
    asset_class: AssetClass
    quantity: Decimal
    market_value: Decimal  # quantity × current price, account currency


@dataclass(frozen=True)
class AccountState:
    equity: Decimal  # cash + sum(position market values)
    cash: Decimal
    positions: Mapping[str, PositionState]
    trades_this_week: int
    drawdown_pct: Decimal  # peak-to-now, positive percentage (0 = at peak)
    paused: bool = False


@dataclass(frozen=True)
class OrderIntent:
    symbol: str
    asset_class: AssetClass
    side: OrderSide
    qty: Decimal
    price: Decimal  # limit price or best-estimate fill price


@dataclass(frozen=True)
class RiskLimitSet:
    """Effective limits for an account. ``None`` = limit not configured (not enforced).

    ``max_asset_class_pct`` is per asset class (risk_profiles stores ``{equity, crypto}``);
    a uniform ``risk_limits`` row maps to the same value for every class.
    """

    max_position_pct: Decimal | None = None
    max_asset_class_pct: Mapping[str, Decimal] = field(default_factory=dict)
    max_trades_per_week: int | None = None
    cash_floor_pct: Decimal | None = None
    per_suggestion_max_pct: Decimal | None = None
    drawdown_pause_pct: Decimal | None = None


@dataclass(frozen=True)
class Violation:
    limit_type: RiskLimitType | None  # None for structural invariants
    message: str
    observed: Decimal
    limit: Decimal


@dataclass(frozen=True)
class Decision:
    allow: bool
    violations: tuple[Violation, ...] = ()

    @property
    def reason(self) -> str | None:
        if self.allow:
            return None
        return "; ".join(v.message for v in self.violations)


def validate_order(intent: OrderIntent, state: AccountState, limits: RiskLimitSet) -> Decision:
    violations: list[Violation] = []

    # --- Structural invariants (not configurable, always enforced) ---
    if intent.qty <= 0:
        violations.append(
            Violation(None, f"quantity must be positive, got {intent.qty}", intent.qty, Decimal(0))
        )
    if intent.price <= 0:
        violations.append(
            Violation(None, f"price must be positive, got {intent.price}", intent.price, Decimal(0))
        )
    if violations:
        # Notional math below is meaningless with non-positive inputs — fail fast.
        return Decision(allow=False, violations=tuple(violations))

    notional = intent.qty * intent.price
    held = state.positions.get(intent.symbol)

    if intent.side is OrderSide.sell:
        held_qty = held.quantity if held else Decimal(0)
        if intent.qty > held_qty:
            violations.append(
                Violation(
                    None,
                    f"cannot sell {intent.qty} {intent.symbol}: only {held_qty} held (no shorting)",
                    intent.qty,
                    held_qty,
                )
            )
    else:  # buy
        if notional > state.cash:
            violations.append(
                Violation(
                    None,
                    f"order needs {notional} but only {state.cash} cash available",
                    notional,
                    state.cash,
                )
            )

    # --- max_trades_per_week (both sides — churn is churn) ---
    if limits.max_trades_per_week is not None:
        proposed = state.trades_this_week + 1
        if proposed > limits.max_trades_per_week:
            violations.append(
                Violation(
                    RiskLimitType.max_trades_per_week,
                    f"trade #{proposed} this week exceeds the {limits.max_trades_per_week}/week limit",
                    Decimal(proposed),
                    Decimal(limits.max_trades_per_week),
                )
            )

    # --- Buy-side exposure limits (equity==0 accounts can't buy anything anyway) ---
    if intent.side is OrderSide.buy and state.equity > 0:
        if state.paused:
            violations.append(
                Violation(
                    RiskLimitType.drawdown_pause_pct,
                    "account is paused — new buys are blocked until you resume",
                    Decimal(1),
                    Decimal(0),
                )
            )
        if (
            limits.drawdown_pause_pct is not None
            and state.drawdown_pct >= limits.drawdown_pause_pct
        ):
            violations.append(
                Violation(
                    RiskLimitType.drawdown_pause_pct,
                    f"drawdown {state.drawdown_pct}% ≥ pause threshold "
                    f"{limits.drawdown_pause_pct}% — buys paused, sells still allowed",
                    state.drawdown_pct,
                    limits.drawdown_pause_pct,
                )
            )

        if limits.per_suggestion_max_pct is not None:
            observed = notional / state.equity * HUNDRED
            if observed > limits.per_suggestion_max_pct:
                violations.append(
                    Violation(
                        RiskLimitType.per_suggestion_max_pct,
                        f"order is {observed.quantize(Decimal('0.01'))}% of equity, "
                        f"limit is {limits.per_suggestion_max_pct}% per trade",
                        observed,
                        limits.per_suggestion_max_pct,
                    )
                )

        if limits.max_position_pct is not None:
            post_value = (held.market_value if held else Decimal(0)) + notional
            observed = post_value / state.equity * HUNDRED
            if observed > limits.max_position_pct:
                violations.append(
                    Violation(
                        RiskLimitType.max_position_pct,
                        f"{intent.symbol} would be {observed.quantize(Decimal('0.01'))}% of your "
                        f"portfolio, limit is {limits.max_position_pct}%",
                        observed,
                        limits.max_position_pct,
                    )
                )

        class_cap = limits.max_asset_class_pct.get(intent.asset_class.value)
        if class_cap is not None:
            class_value = (
                sum(
                    (
                        p.market_value
                        for p in state.positions.values()
                        if p.asset_class is intent.asset_class
                    ),
                    Decimal(0),
                )
                + notional
            )
            observed = class_value / state.equity * HUNDRED
            if observed > class_cap:
                violations.append(
                    Violation(
                        RiskLimitType.max_asset_class_pct,
                        f"{intent.asset_class.value} would be "
                        f"{observed.quantize(Decimal('0.01'))}% of your portfolio, "
                        f"limit is {class_cap}%",
                        observed,
                        class_cap,
                    )
                )

        if limits.cash_floor_pct is not None:
            post_cash = state.cash - notional
            observed = post_cash / state.equity * HUNDRED
            if observed < limits.cash_floor_pct:
                violations.append(
                    Violation(
                        RiskLimitType.cash_floor_pct,
                        f"cash would fall to {observed.quantize(Decimal('0.01'))}% of equity, "
                        f"your floor is {limits.cash_floor_pct}%",
                        observed,
                        limits.cash_floor_pct,
                    )
                )

    return Decision(allow=not violations, violations=tuple(violations))
