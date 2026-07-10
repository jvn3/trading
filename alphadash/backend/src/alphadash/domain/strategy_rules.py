"""User-authored strategy rules (S4.2) — the frozen deterministic DSL.

An LLM (or the user directly) AUTHORS a ``StrategyParams`` document; nothing else. Evaluation
is pure code with injected closes — no LLM, no network, no clock. Every trade a strategy
produces still passes the S1.3 risk gate; this module only decides *enter / exit / hold*.

FROZEN CONTRACT — S4.2 rule schema (bounds enforced by pydantic):

- Condition kinds (computed on daily EOD closes, most recent last):
    ``price_above_sma`` / ``price_below_sma``  — last close vs SMA(window)
    ``return_exceeds``  — window-day return ≥ threshold_pct  (momentum)
    ``return_below``    — window-day return ≤ -threshold_pct (dip)
- Entry: exactly one condition.
- Exit: optional condition, plus optional take_profit_pct / stop_loss_pct vs entry price.
  At least ONE exit mechanism is required — a strategy that can never exit is not a strategy.
- ``size_pct``: percent of equity per entry, hard-capped at 20 (the risk layer applies the
  user's own per-trade cap on top at execution time).
"""

from __future__ import annotations

import enum
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

HUNDRED = Decimal("100")

MIN_WINDOW, MAX_WINDOW = 2, 200
MIN_THRESHOLD, MAX_THRESHOLD = Decimal("0.5"), Decimal("95")
MIN_SIZE, MAX_SIZE = Decimal("0.5"), Decimal("20")
MIN_TAKE_PROFIT, MAX_TAKE_PROFIT = Decimal("1"), Decimal("500")
MIN_STOP_LOSS, MAX_STOP_LOSS = Decimal("1"), Decimal("95")


class ConditionKind(enum.StrEnum):
    price_above_sma = "price_above_sma"
    price_below_sma = "price_below_sma"
    return_exceeds = "return_exceeds"
    return_below = "return_below"


class Condition(BaseModel):
    kind: ConditionKind
    window: int = Field(ge=MIN_WINDOW, le=MAX_WINDOW)
    threshold_pct: Decimal | None = None  # required for return_* kinds

    @model_validator(mode="after")
    def _threshold_matches_kind(self) -> Condition:
        needs = self.kind in (ConditionKind.return_exceeds, ConditionKind.return_below)
        if needs and self.threshold_pct is None:
            raise ValueError(f"{self.kind.value} requires threshold_pct")
        if not needs and self.threshold_pct is not None:
            raise ValueError(f"{self.kind.value} does not take threshold_pct")
        if self.threshold_pct is not None and not (
            MIN_THRESHOLD <= self.threshold_pct <= MAX_THRESHOLD
        ):
            raise ValueError(f"threshold_pct must be between {MIN_THRESHOLD} and {MAX_THRESHOLD}")
        return self


class StrategyParams(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    asset_class: Literal["equity", "crypto"]
    entry: Condition
    exit_condition: Condition | None = None
    take_profit_pct: Decimal | None = None
    stop_loss_pct: Decimal | None = None
    size_pct: Decimal = Field(default=Decimal("5"))

    @field_validator("symbol")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()

    @model_validator(mode="after")
    def _bounds_and_exit_required(self) -> StrategyParams:
        if not (MIN_SIZE <= self.size_pct <= MAX_SIZE):
            raise ValueError(f"size_pct must be between {MIN_SIZE} and {MAX_SIZE}")
        if self.take_profit_pct is not None and not (
            MIN_TAKE_PROFIT <= self.take_profit_pct <= MAX_TAKE_PROFIT
        ):
            raise ValueError("take_profit_pct out of bounds")
        if self.stop_loss_pct is not None and not (
            MIN_STOP_LOSS <= self.stop_loss_pct <= MAX_STOP_LOSS
        ):
            raise ValueError("stop_loss_pct out of bounds")
        if (
            self.exit_condition is None
            and self.take_profit_pct is None
            and self.stop_loss_pct is None
        ):
            raise ValueError(
                "strategy needs at least one exit: exit_condition, take_profit_pct or stop_loss_pct"
            )
        return self


# ---------------------------------------------------------------------------
# Evaluation (pure)
# ---------------------------------------------------------------------------


def sma(closes: list[Decimal], window: int) -> Decimal | None:
    if len(closes) < window:
        return None
    tail = closes[-window:]
    return sum(tail, Decimal("0")) / Decimal(window)


def condition_met(closes: list[Decimal], cond: Condition) -> bool | None:
    """True/False when computable, None when there is not enough history (never guess)."""
    if not closes:
        return None
    last = closes[-1]
    if cond.kind in (ConditionKind.price_above_sma, ConditionKind.price_below_sma):
        avg = sma(closes, cond.window)
        if avg is None:
            return None
        return last > avg if cond.kind is ConditionKind.price_above_sma else last < avg
    # return_* kinds: window-day return needs window+1 closes
    if len(closes) < cond.window + 1:
        return None
    prior = closes[-(cond.window + 1)]
    if prior <= 0:
        return None
    ret_pct = (last - prior) / prior * HUNDRED
    if cond.kind is ConditionKind.return_exceeds:
        return ret_pct >= cond.threshold_pct
    return ret_pct <= -cond.threshold_pct


def evaluate(
    closes: list[Decimal], params: StrategyParams, entry_price: Decimal | None
) -> Literal["enter", "exit", "hold", "wait"]:
    """One deterministic decision from history + holding state.

    ``entry_price`` is None when flat. Exit precedence: stop loss → take profit →
    exit condition (protective exits first, always).
    Returns "wait" when flat and entry not met, or when history is insufficient.
    """
    if not closes:
        return "wait" if entry_price is None else "hold"
    last = closes[-1]

    if entry_price is not None:
        if entry_price > 0:
            move_pct = (last - entry_price) / entry_price * HUNDRED
            if params.stop_loss_pct is not None and move_pct <= -params.stop_loss_pct:
                return "exit"
            if params.take_profit_pct is not None and move_pct >= params.take_profit_pct:
                return "exit"
        if params.exit_condition is not None and condition_met(closes, params.exit_condition):
            return "exit"
        return "hold"

    return "enter" if condition_met(closes, params.entry) else "wait"


# ---------------------------------------------------------------------------
# Plain-language description (faithfulness: users approve what the code will do)
# ---------------------------------------------------------------------------


def _fmt(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral_value():
        normalized = normalized.quantize(Decimal("1"))
    return format(normalized, "f")


def _describe_condition(cond: Condition) -> str:
    if cond.kind is ConditionKind.price_above_sma:
        return f"the price closes above its {cond.window}-day average"
    if cond.kind is ConditionKind.price_below_sma:
        return f"the price closes below its {cond.window}-day average"
    if cond.kind is ConditionKind.return_exceeds:
        return f"the price has risen at least {_fmt(cond.threshold_pct)}% over {cond.window} days"
    return f"the price has fallen at least {_fmt(cond.threshold_pct)}% over {cond.window} days"


def describe(params: StrategyParams) -> str:
    parts = [
        f"Buy {params.symbol} with {_fmt(params.size_pct)}% of the portfolio when "
        f"{_describe_condition(params.entry)}."
    ]
    exits: list[str] = []
    if params.stop_loss_pct is not None:
        exits.append(f"the position is down {_fmt(params.stop_loss_pct)}% (stop loss)")
    if params.take_profit_pct is not None:
        exits.append(f"the position is up {_fmt(params.take_profit_pct)}% (take profit)")
    if params.exit_condition is not None:
        exits.append(_describe_condition(params.exit_condition))
    parts.append("Sell when " + " or ".join(exits) + ".")
    parts.append("Every trade still passes your safety limits before it can execute.")
    return " ".join(parts)
