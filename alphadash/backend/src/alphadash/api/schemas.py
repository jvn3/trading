"""BFF response/request shapes (S1.9). All money/quantity fields are STRINGS over the wire
(Decimal never becomes a JS float) — matches the frozen S0.4 frontend contract."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PositionOut(BaseModel):
    symbol: str
    asset_class: str
    quantity: str
    avg_cost: str
    market_value: str
    unrealized_pl: str
    allocation_pct: float


class PortfolioOut(BaseModel):
    equity: str
    cash: str
    positions: list[PositionOut]
    allocation_pct: dict[str, float]


class PerformancePointOut(BaseModel):
    day: str  # ISO date
    equity: str
    benchmark_equity: str


class PerformanceOut(BaseModel):
    points: list[PerformancePointOut]
    return_pct: float
    benchmark_return_pct: float
    max_drawdown_pct: float
    current_drawdown_pct: float
    benchmark_symbol: str


class AccountOut(BaseModel):
    id: str
    mode: str
    base_currency: str
    starting_equity: str
    paused: bool
    trading_mode: str  # global app invariant, surfaced everywhere


class LimitsOut(BaseModel):
    max_position_pct: str | None
    max_asset_class_pct: dict[str, str]
    max_trades_per_week: int | None
    cash_floor_pct: str | None
    per_suggestion_max_pct: str | None
    drawdown_pause_pct: str | None


class ViolationOut(BaseModel):
    limit_type: str | None
    message: str


class OrderRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    asset_class: str = Field(pattern="^(equity|crypto)$")
    side: str = Field(pattern="^(buy|sell)$")
    order_type: str = Field(pattern="^(market|limit)$")
    qty: str  # Decimal string
    limit_price: str | None = None


class FillOut(BaseModel):
    qty: str
    price: str
    fee: str
    filled_at: str


class OrderOut(BaseModel):
    id: str
    symbol: str
    asset_class: str
    side: str
    order_type: str
    qty: str
    limit_price: str | None
    status: str
    rejected_reason: str | None
    created_at: str
    fill: FillOut | None = None


class OrderResult(BaseModel):
    order: OrderOut
    violations: list[ViolationOut]
    replayed: bool


class QuoteOut(BaseModel):
    symbol: str
    price: str
    as_of: str
    source: str
    is_stale: bool
