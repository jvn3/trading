"""Strategy base class + shared value types.

A strategy turns *signals* + *portfolio state* into *trade intents*. Intents
are then vetted (position sizer here; more checks in a future risk layer)
and handed to the executor.

The interface matches Appendix B of the implementation plan, with one small
change: we keep :class:`TradeIntent` concrete rather than a protocol, since
strategies only ever produce it and the executor only ever consumes it.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class TradeIntent:
    """A strategy's proposal to open or close a position.

    Either ``notional`` or ``qty`` must be set (but not both).
    """

    strategy_name: str
    ticker: str
    side: str  # "buy" | "sell"
    order_type: str = "market"  # "market" | "limit"
    notional: float | None = None
    qty: float | None = None
    limit_price: float | None = None
    time_in_force: str = "day"
    stop_price: float | None = None
    signal_id: int | None = None
    rationale: dict[str, Any] = field(default_factory=dict)
    # Internal: "open" = new position, "close" = exit, "adjust" = stop change.
    action: str = "open"

    def __post_init__(self) -> None:
        if (self.notional is None) == (self.qty is None):
            raise ValueError("exactly one of notional/qty must be set")
        if self.side not in ("buy", "sell"):
            raise ValueError(f"invalid side: {self.side!r}")


@dataclass(frozen=True)
class PositionView:
    """Flattened view of one open position, combined from Alpaca + our DB."""

    ticker: str
    qty: float
    avg_entry_price: float
    current_price: float
    market_value: float
    unrealized_pl: float
    unrealized_plpc: float  # -0.08 = down 8%
    strategy_name: str | None
    hard_stop: float | None
    trail_peak: float | None
    trail_active: bool
    opened_at: datetime | None
    entry_signal_id: int | None


@dataclass(frozen=True)
class PortfolioSnapshot:
    """Point-in-time view of the paper account."""

    equity: float
    cash: float
    buying_power: float
    positions: list[PositionView] = field(default_factory=list)
    taken_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def positions_for(self, strategy_name: str) -> list[PositionView]:
        return [p for p in self.positions if p.strategy_name == strategy_name]

    def holds(self, ticker: str) -> bool:
        return any(p.ticker.upper() == ticker.upper() for p in self.positions)


@dataclass(frozen=True)
class SignalView:
    """A Signal row plus anything the strategy needs inline (no re-query)."""

    id: int
    strategy_name: str
    ticker: str
    direction: str  # "long" | "short" | "flat"
    score: float
    rationale: dict[str, Any]
    generated_at: datetime


class Strategy(ABC):
    """Base class for all trading strategies."""

    #: Globally unique strategy name. Used for client_order_id prefix and DB joins.
    name: str = "base"
    #: Master on/off switch (toggled via config or DB).
    enabled: bool = False
    #: When True, :func:`generate_intents` runs but the executor converts
    #: submits to shadow writes. Default True — flip via config for live.
    shadow_mode: bool = True
    #: Cap on open positions attributable to this strategy.
    max_concurrent_positions: int = 10

    @abstractmethod
    def generate_intents(
        self,
        signals: list[SignalView],
        portfolio: PortfolioSnapshot,
    ) -> list[TradeIntent]:
        """Emit new-position intents from unacted-on signals."""

    @abstractmethod
    def manage_positions(
        self,
        positions: list[PositionView],
        portfolio: PortfolioSnapshot,
    ) -> list[TradeIntent]:
        """Emit exit / stop-adjust intents for currently-open positions."""
