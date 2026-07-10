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


# --- S3.x beginner-experience shapes ---


class OnboardingRequest(BaseModel):
    experience: str = Field(pattern="^(new|some|confident)$")
    drop_reaction: str = Field(pattern="^(sell|wait|buy_more)$")
    goal: str = Field(pattern="^(preserve|learn|grow)$")


class OnboardingOut(BaseModel):
    profile: str  # conservative | balanced | curious
    limits: LimitsOut
    onboarded: bool


class OnboardingStatusOut(BaseModel):
    onboarded: bool
    profiles: dict[str, LimitsOut]  # preset name -> limits, for the wizard's teaching copy


class LimitsUpdateRequest(BaseModel):
    max_position_pct: str  # Decimal strings, like everything money-adjacent
    max_asset_class_pct: dict[str, str]  # keys: equity, crypto
    max_trades_per_week: int = Field(ge=0, le=100)
    cash_floor_pct: str
    per_suggestion_max_pct: str
    drawdown_pause_pct: str


class LimitsUpdateOut(BaseModel):
    limits: LimitsOut
    profile: str
    loosened: list[str]  # field names the edit made MORE permissive (teaching copy hook)


class NotificationOut(BaseModel):
    id: str
    kind: str
    title: str
    body: str
    payload: dict
    created_at: str
    read_at: str | None


class DigestOut(BaseModel):
    notification: NotificationOut
    created: bool


class NudgeOut(BaseModel):
    kind: str
    severity: str
    message: str


class JournalEntryOut(BaseModel):
    id: str
    entry_type: str
    ref_id: str
    payload: dict
    created_at: str


class JournalOut(BaseModel):
    entries: list[JournalEntryOut]
    nudges: list[NudgeOut]


# --- S4.2 strategy lab ---


class StrategyDraftRequest(BaseModel):
    text: str = Field(min_length=5, max_length=1000)


class StrategyOut(BaseModel):
    id: str
    name: str
    source_text: str
    status: str
    params: dict
    description: str  # plain-language compilation of the rules (faithfulness)
    created_at: str
    last_backtest: dict | None = None  # results JSON of the most recent backtest


class BacktestWindowOut(BaseModel):
    start: str
    end: str
    strategy_return_pct: float
    buy_hold_return_pct: float
    trades: int


class BacktestOut(BaseModel):
    strategy_id: str
    windows: list[BacktestWindowOut]
    total_return_pct: float
    buy_hold_return_pct: float
    benchmark_return_pct: float
    max_drawdown_pct: float
    closed_trades: int
    win_rate_pct: float | None
    windows_beating_buy_hold: int
    small_sample: bool
    days: int
    caveats: list[str]


# --- S4.3 what-if simulator ---


class ShockRequest(BaseModel):
    equity_pct: str = "0"  # Decimal strings; -20 means "falls 20%"
    crypto_pct: str = "0"
    symbol_overrides: dict[str, str] = Field(default_factory=dict)


class PositionImpactOut(BaseModel):
    symbol: str
    asset_class: str
    value_before: str
    value_after: str
    applied_pct: str


class ShockImpactOut(BaseModel):
    equity_before: str
    equity_after: str
    equity_change_pct: str
    cash: str
    positions: list[PositionImpactOut]
    allocation_after_pct: dict[str, float]
    would_trip_drawdown_pause: bool
    drawdown_pause_pct: str | None


class TradePreviewRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    asset_class: str = Field(pattern="^(equity|crypto)$")
    side: str = Field(pattern="^(buy|sell)$")
    qty: str  # Decimal string


class TradePreviewOut(BaseModel):
    allowed: bool
    violations: list[ViolationOut]
    est_price: str
    cash_after: str
    position_value_after: str
    position_allocation_after_pct: float
    cash_allocation_after_pct: float


class ClosedTradesOut(BaseModel):
    closed_trades: int
    wins: int
    losses: int
    win_rate_pct: float | None
    small_sample: bool


class ReviewOut(BaseModel):
    performance: PerformanceOut
    trades: ClosedTradesOut
    verdict: str
    disclaimers: list[str]
