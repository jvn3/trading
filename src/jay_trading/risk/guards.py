"""Phase-3 risk guards.

Two shapes of guards:

*Pipeline gates* run once per ``execute_strategies`` tick, before any
strategy generates intents. If any gate trips, **new entries are blocked
for that tick**. ``manage_stops`` is never blocked — position exits must
always be allowed. A tripped gate writes a ``breaker_trip`` RiskEvent.

*Per-intent gates* (currently just the sector-correlation cap) run inside
the for-intent loop, alongside sizing. A tripped gate writes a
``sizing_veto`` RiskEvent and rejects the single intent.

Thresholds are module-level constants; override in tests via monkeypatch.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from jay_trading.data import store
from jay_trading.risk import api_health, equity_tracker
from jay_trading.strategies.base import PortfolioSnapshot, TradeIntent

log = logging.getLogger(__name__)


# -- Thresholds (module constants, tunable per PR if needed) ---------------

DAILY_LOSS_THRESHOLD = -0.02           # trip if daily DD < -2%
DRAWDOWN_THRESHOLD = -0.05             # trip if DD from HWM < -5%
API_HEALTH_WINDOW_MINUTES = 30
API_HEALTH_FAIL_RATE_THRESHOLD = 0.30
API_HEALTH_MIN_CALLS = 10
SECTOR_CORRELATION_CAP = 3
# NOTE: the binary ``check_market_regime`` gate was retired on 2026-04-21 when
# Strategy V (``risk.macro_regime``) shipped. The 5-level macro regime
# classifier replaces it; its output feeds position sizing rather than a
# hard long/short block. See development/log.md 2026-04-21.


# -- Result types ----------------------------------------------------------


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reason: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PipelineDecision:
    allow_entries: bool
    trips: list[tuple[str, GateResult]]


# -- Pipeline gates --------------------------------------------------------


def check_daily_loss(*, alpaca: Any, **_: Any) -> GateResult:
    try:
        view = equity_tracker.build_view(alpaca)
    except Exception as e:  # noqa: BLE001
        log.warning("daily_loss: equity view failed, passing gate: %s", e)
        return GateResult(True, reason="equity unavailable, fail-open")

    change = view.daily_change_fraction
    if change < DAILY_LOSS_THRESHOLD:
        return GateResult(
            False,
            reason=(
                f"daily DD {change:.2%} breaches threshold "
                f"{DAILY_LOSS_THRESHOLD:.0%} "
                f"(equity ${view.equity:,.2f} vs last close ${view.last_equity:,.2f})"
            ),
            details={
                "equity": view.equity,
                "last_equity": view.last_equity,
                "change": change,
                "threshold": DAILY_LOSS_THRESHOLD,
            },
        )
    return GateResult(True)


def check_drawdown(*, alpaca: Any, **_: Any) -> GateResult:
    try:
        view = equity_tracker.build_view(alpaca)
    except Exception as e:  # noqa: BLE001
        log.warning("drawdown: equity view failed, passing gate: %s", e)
        return GateResult(True, reason="equity unavailable, fail-open")

    dd = view.drawdown_from_hwm
    if dd < DRAWDOWN_THRESHOLD:
        return GateResult(
            False,
            reason=(
                f"DD from HWM {dd:.2%} breaches {DRAWDOWN_THRESHOLD:.0%} "
                f"(equity ${view.equity:,.2f} vs HWM ${view.high_water_mark:,.2f})"
            ),
            details={
                "equity": view.equity,
                "high_water_mark": view.high_water_mark,
                "drawdown": dd,
                "threshold": DRAWDOWN_THRESHOLD,
            },
        )
    return GateResult(True)


def check_api_health(*, window_minutes: int = API_HEALTH_WINDOW_MINUTES, **_: Any) -> GateResult:
    for provider in ("fmp", "alpaca"):
        s = api_health.summary(provider, window_minutes=window_minutes)
        if s.total < API_HEALTH_MIN_CALLS:
            continue  # not enough data; skip this provider
        if s.fail_rate > API_HEALTH_FAIL_RATE_THRESHOLD:
            return GateResult(
                False,
                reason=(
                    f"{provider} {s.fail_rate:.0%} fail rate over {window_minutes}min "
                    f"({s.fails}/{s.total} calls failed)"
                ),
                details={
                    "provider": provider,
                    "fails": s.fails,
                    "total": s.total,
                    "fail_rate": s.fail_rate,
                    "window_minutes": window_minutes,
                    "threshold": API_HEALTH_FAIL_RATE_THRESHOLD,
                },
            )
    return GateResult(True)


# -- Per-intent gate -------------------------------------------------------


def check_correlation_cap(
    intent: TradeIntent,
    portfolio: PortfolioSnapshot,  # noqa: ARG001 — reserved for in-memory inference
    *,
    fmp: Any,
    cap: int = SECTOR_CORRELATION_CAP,
) -> GateResult:
    """Reject if opening this intent would push sector exposure past ``cap``.

    Only applies to ``open`` intents. Close intents always pass.
    """
    if intent.action != "open":
        return GateResult(True)

    sector = _resolve_sector(intent.ticker, fmp=fmp)
    if not sector:
        # Unknown sector → fail-open. The alternative (fail-closed) would
        # mean a misconfigured profile cache silently halts trading.
        return GateResult(True, reason="sector unknown, fail-open",
                          details={"ticker": intent.ticker})

    count = store.sector_position_count(sector)
    if count >= cap:
        return GateResult(
            False,
            reason=f"sector cap: {count} positions in {sector}, cap is {cap}",
            details={"sector": sector, "count": count, "cap": cap, "ticker": intent.ticker},
        )
    return GateResult(True, details={"sector": sector, "count": count})


# -- Orchestration ---------------------------------------------------------


_PIPELINE_GATES: list[tuple[str, Any]] = [
    ("daily_loss", check_daily_loss),
    ("drawdown", check_drawdown),
    ("api_health", check_api_health),
]


def evaluate_pipeline_gates(
    *, alpaca: Any, fmp: Any, portfolio: PortfolioSnapshot | None = None,
) -> PipelineDecision:
    """Run every pipeline gate in order; collect all trips.

    Returns ``allow_entries=False`` if any gate tripped. Does not short-circuit
    — we want to see every failure in logs, not just the first.
    """
    trips: list[tuple[str, GateResult]] = []
    for name, fn in _PIPELINE_GATES:
        try:
            res = fn(alpaca=alpaca, fmp=fmp, portfolio=portfolio)
        except Exception as e:  # noqa: BLE001
            log.exception("gate %s raised — passing it fail-open", name)
            res = GateResult(True, reason=f"{name} errored: {e!r} (fail-open)")
        if not res.passed:
            trips.append((name, res))
    return PipelineDecision(allow_entries=not trips, trips=trips)


# -- Helpers ---------------------------------------------------------------


def _resolve_sector(ticker: str, *, fmp: Any) -> str | None:
    """Look up the ticker's sector via cache, falling back to FMP /profile.

    Returns ``None`` if we can't resolve it (and the caller should fail-open).
    """
    from datetime import datetime, timezone, timedelta

    prof = store.get_ticker_profile(ticker)
    # SQLite drops tz info even for DateTime(timezone=True) columns — normalize.
    last_refreshed = prof.last_refreshed if prof is not None else None
    if last_refreshed is not None and last_refreshed.tzinfo is None:
        last_refreshed = last_refreshed.replace(tzinfo=timezone.utc)
    stale = (
        prof is None
        or (last_refreshed is not None
            and last_refreshed < datetime.now(timezone.utc) - timedelta(days=30))
    )
    if not stale and prof is not None:
        return prof.sector

    # Cache miss or stale — fetch from FMP.
    try:
        raw = fmp.request("profile", params={"symbol": ticker})
    except Exception as e:  # noqa: BLE001
        log.warning("sector lookup failed for %s: %s — using cached (if any)", ticker, e)
        return prof.sector if prof is not None else None

    if not isinstance(raw, list) or not raw:
        return prof.sector if prof is not None else None

    row = raw[0]
    sector = row.get("sector") or None
    store.upsert_ticker_profile(
        ticker,
        sector=sector,
        industry=row.get("industry"),
        market_cap=row.get("marketCap") or row.get("mktCap"),
    )
    return sector
