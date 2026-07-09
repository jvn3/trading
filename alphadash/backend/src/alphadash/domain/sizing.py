"""Sizing engine (S1.4) — deterministic, LLM-free.

Computes the largest buy (or a requested target size) that respects every buy-side cap in the
account's ``RiskLimitSet``. The invariant that matters — proven by property test — is:

    a size produced here, fed to ``validate_order`` with the same state + limits, is ALWAYS allowed.

Sells are sized trivially (capped at held quantity) and included for symmetry.
Quantities are quantized DOWN to 8 decimal places (matches ``Numeric(24,8)`` storage).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from alphadash.db.models import AssetClass
from alphadash.domain.risk import HUNDRED, AccountState, RiskLimitSet

QTY_STEP = Decimal("0.00000001")  # 8 dp, matches Numeric(24,8)
ZERO = Decimal("0")


@dataclass(frozen=True)
class SizeResult:
    qty: Decimal
    notional: Decimal  # qty × price
    pct_of_equity: Decimal  # notional / equity × 100 (0 when equity is 0)
    binding_constraint: str  # which cap limited the size ("target" when target_pct won)
    capped: bool  # True when a risk cap bit before the target/cash did


def size_buy(
    state: AccountState,
    limits: RiskLimitSet,
    symbol: str,
    asset_class: AssetClass,
    price: Decimal,
    target_pct: Decimal | None = None,
) -> SizeResult:
    """Largest permissible buy notional, optionally capped at ``target_pct`` of equity.

    Returns qty=0 (with the binding constraint named) when nothing is buyable — paused account,
    drawdown pause, zero cash, zero equity, or a cap already exhausted.
    """
    if price <= 0:
        raise ValueError(f"price must be positive, got {price}")

    if state.equity <= 0 or state.cash <= 0:
        return SizeResult(ZERO, ZERO, ZERO, "no cash available", capped=True)
    if state.paused:
        return SizeResult(ZERO, ZERO, ZERO, "account paused", capped=True)
    if limits.drawdown_pause_pct is not None and state.drawdown_pct >= limits.drawdown_pause_pct:
        return SizeResult(ZERO, ZERO, ZERO, "drawdown pause active", capped=True)
    if (
        limits.max_trades_per_week is not None
        and state.trades_this_week + 1 > limits.max_trades_per_week
    ):
        return SizeResult(ZERO, ZERO, ZERO, "weekly trade limit reached", capped=True)

    # Candidate notional ceilings: (constraint name, max notional under it)
    candidates: list[tuple[str, Decimal]] = [("available cash", state.cash)]

    if limits.cash_floor_pct is not None:
        floor_cash = state.equity * limits.cash_floor_pct / HUNDRED
        candidates.append(("cash floor", state.cash - floor_cash))

    if limits.per_suggestion_max_pct is not None:
        candidates.append(("per-trade cap", state.equity * limits.per_suggestion_max_pct / HUNDRED))

    if limits.max_position_pct is not None:
        held = state.positions.get(symbol)
        held_value = held.market_value if held else ZERO
        candidates.append(
            ("position cap", state.equity * limits.max_position_pct / HUNDRED - held_value)
        )

    class_cap = limits.max_asset_class_pct.get(asset_class.value)
    if class_cap is not None:
        class_value = sum(
            (p.market_value for p in state.positions.values() if p.asset_class is asset_class),
            ZERO,
        )
        candidates.append(("asset-class cap", state.equity * class_cap / HUNDRED - class_value))

    if target_pct is not None:
        candidates.append(("target", state.equity * target_pct / HUNDRED))

    binding, notional_cap = min(candidates, key=lambda c: c[1])
    if notional_cap <= 0:
        return SizeResult(ZERO, ZERO, ZERO, binding, capped=True)

    qty = (notional_cap / price).quantize(QTY_STEP, rounding=ROUND_DOWN)
    if qty <= 0:
        return SizeResult(ZERO, ZERO, ZERO, binding, capped=binding != "target")

    notional = qty * price
    pct = notional / state.equity * HUNDRED
    return SizeResult(
        qty=qty,
        notional=notional,
        pct_of_equity=pct,
        binding_constraint=binding,
        capped=binding not in ("target", "available cash"),
    )


def size_sell(state: AccountState, symbol: str, requested_qty: Decimal) -> SizeResult:
    """Cap a sell at the held quantity. qty=0 when nothing is held."""
    held = state.positions.get(symbol)
    held_qty = held.quantity if held else ZERO
    qty = min(requested_qty, held_qty).quantize(QTY_STEP, rounding=ROUND_DOWN)
    if qty <= 0:
        return SizeResult(ZERO, ZERO, ZERO, "nothing held", capped=True)
    price_per_unit = held.market_value / held.quantity if held and held.quantity else ZERO
    notional = qty * price_per_unit
    pct = notional / state.equity * HUNDRED if state.equity > 0 else ZERO
    return SizeResult(
        qty=qty,
        notional=notional,
        pct_of_equity=pct,
        binding_constraint="held quantity" if qty < requested_qty else "requested",
        capped=qty < requested_qty,
    )
