"""User-authored strategies (S4.2): NL → rules author, walk-forward backtest, live candidates.

The LLM's only job is translating the user's plain-language intent into the frozen
``StrategyParams`` schema (domain/strategy_rules.py) — schema-validated with ≤3 attempts, same
discipline as S2.3. Everything downstream (evaluation, backtest, candidate generation, sizing,
the risk gate) is deterministic code. A strategy can never trade by itself: it only feeds
candidates into the same suggest → human-approve → risk-gate pipeline as every other idea.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from alphadash.db.models import (
    Account,
    AssetClass,
    JournalEntryType,
    OrderSide,
    Strategy,
    StrategyBacktest,
    StrategyStatus,
    User,
)
from alphadash.domain.risk import AccountState, RiskLimitSet
from alphadash.domain.signals import CandidateAction
from alphadash.domain.strategy_backtest import (
    BacktestError,
    BacktestResult,
    result_to_json,
    run_backtest,
)
from alphadash.domain.strategy_rules import StrategyParams, describe, evaluate
from alphadash.llm.base import LLMClient, LLMError
from alphadash.providers.factory import ProviderBundle
from alphadash.services import journal

log = logging.getLogger(__name__)

PROMPT_VERSION = "s4.2-v1"
MAX_ATTEMPTS = 3
BACKTEST_DAYS = 365
BENCHMARK = "SPY"
MAX_ACTIVE_STRATEGIES = 5


class StrategyAuthorError(Exception):
    """Authoring failed (LLM unusable after retries or invalid text). Safe to show."""


class AuthoredStrategy(BaseModel):
    """What the LLM must return: a display name + the frozen rule document."""

    name: str = Field(min_length=1, max_length=120)
    params: StrategyParams


SYSTEM_PROMPT = (
    "You translate a beginner's plain-language trading idea into a strict JSON rule document. "
    "You NEVER invent trades, prices or quantities — only the rule document. If the user's "
    "text implies parameters, use them; otherwise choose conservative defaults within bounds. "
    "Output ONLY the JSON object, no prose."
)


def _author_prompt(text: str) -> str:
    schema = {
        "name": "short display name",
        "params": {
            "symbol": "ticker, e.g. AAPL or BTCUSD",
            "asset_class": "equity|crypto",
            "entry": {
                "kind": "price_above_sma|price_below_sma|return_exceeds|return_below",
                "window": "int 2-200 (days)",
                "threshold_pct": "decimal string, required only for return_* kinds (0.5-95)",
            },
            "exit_condition": "same shape as entry, or null",
            "take_profit_pct": "decimal string 1-500 or null",
            "stop_loss_pct": "decimal string 1-95 or null",
            "size_pct": "decimal string 0.5-20 (percent of portfolio per entry)",
        },
    }
    return (
        "Translate this strategy idea into the rule schema. At least one exit "
        "(exit_condition, take_profit_pct or stop_loss_pct) is required.\n"
        f"SCHEMA: {json.dumps(schema)}\n"
        f"STRATEGY_TEXT: {text}"
    )


@dataclass(frozen=True)
class DraftResult:
    strategy: Strategy
    params: StrategyParams
    description: str


def draft_strategy(
    session: Session, *, user: User, account: Account, llm: LLMClient, text: str, now: datetime
) -> DraftResult:
    text = text.strip()
    if not (5 <= len(text) <= 1000):
        raise StrategyAuthorError("describe your strategy in 5 to 1000 characters")

    messages = [{"role": "user", "content": _author_prompt(text)}]
    last_error = ""
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = llm.complete(system=SYSTEM_PROMPT, messages=messages, max_tokens=1024)
        except LLMError as e:
            raise StrategyAuthorError(f"the assistant is unavailable: {e}") from None
        try:
            raw = json.loads(response.text)
            authored = AuthoredStrategy.model_validate(raw)
            break
        except (json.JSONDecodeError, ValidationError) as e:
            last_error = str(e)
            log.warning("strategy author attempt %d invalid: %s", attempt + 1, e)
            messages = messages + [
                {"role": "assistant", "content": response.text},
                {
                    "role": "user",
                    "content": f"That was invalid: {e}. Return ONLY corrected JSON.",
                },
            ]
    else:
        raise StrategyAuthorError(
            f"could not turn that into valid rules after {MAX_ATTEMPTS} attempts: {last_error}"
        )

    strategy = Strategy(
        user_id=user.id,
        name=authored.name,
        source_text=text,
        params=json.loads(authored.params.model_dump_json()),
        status=StrategyStatus.draft,
        prompt_version=PROMPT_VERSION,
        model_version=response.model,
    )
    session.add(strategy)
    session.flush()
    journal.record(
        session,
        account_id=account.id,
        entry_type=JournalEntryType.note,
        ref_id=strategy.id,
        payload={
            "event": "strategy_drafted",
            "name": strategy.name,
            "source_text": text,
            "params": strategy.params,
        },
    )
    return DraftResult(
        strategy=strategy, params=authored.params, description=describe(authored.params)
    )


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------


def _daily_closes(bundle: ProviderBundle, symbol: str, now: datetime, days: int):
    bars = bundle.market_data.get_bars(symbol, "1D", now - timedelta(days=days), now)
    return {b.ts.date(): b.close for b in bars}


def backtest_strategy(
    session: Session,
    *,
    strategy: Strategy,
    account: Account,
    bundle: ProviderBundle,
    now: datetime,
    days: int = BACKTEST_DAYS,
) -> tuple[StrategyBacktest, BacktestResult]:
    params = StrategyParams.model_validate(strategy.params)
    try:
        symbol_closes = _daily_closes(bundle, params.symbol, now, days)
        bench_closes = _daily_closes(bundle, BENCHMARK, now, days)
    except Exception as e:
        raise BacktestError(f"price history unavailable: {e}") from None

    # Align on days both series actually have — never interpolate.
    shared = sorted(set(symbol_closes) & set(bench_closes))
    day_list = list(shared)
    result = run_backtest(
        days=day_list,
        closes=[symbol_closes[d] for d in day_list],
        benchmark_closes=[bench_closes[d] for d in day_list],
        params=params,
    )
    row = StrategyBacktest(
        strategy_id=strategy.id, params=strategy.params, results=result_to_json(result)
    )
    session.add(row)
    session.flush()
    journal.record(
        session,
        account_id=account.id,
        entry_type=JournalEntryType.note,
        ref_id=row.id,
        payload={
            "event": "strategy_backtested",
            "strategy_id": strategy.id,
            "total_return_pct": float(result.total_return_pct),
            "buy_hold_return_pct": float(result.buy_hold_return_pct),
            "max_drawdown_pct": float(result.max_drawdown_pct),
            "closed_trades": len(result.closed_trades),
        },
    )
    return row, result


def latest_backtest(session: Session, strategy: Strategy) -> StrategyBacktest | None:
    return session.scalar(
        select(StrategyBacktest)
        .where(StrategyBacktest.strategy_id == strategy.id)
        .order_by(StrategyBacktest.created_at.desc(), StrategyBacktest.id.desc())
    )


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def set_status(
    session: Session,
    *,
    strategy: Strategy,
    account: Account,
    status: StrategyStatus,
) -> Strategy:
    if status is StrategyStatus.active:
        if latest_backtest(session, strategy) is None:
            raise StrategyAuthorError("backtest the strategy before activating it")
        active = session.scalars(
            select(Strategy).where(
                Strategy.user_id == strategy.user_id, Strategy.status == StrategyStatus.active
            )
        ).all()
        if len([s for s in active if s.id != strategy.id]) >= MAX_ACTIVE_STRATEGIES:
            raise StrategyAuthorError(f"at most {MAX_ACTIVE_STRATEGIES} active strategies")
    strategy.status = status
    session.flush()
    journal.record(
        session,
        account_id=account.id,
        entry_type=JournalEntryType.note,
        ref_id=strategy.id,
        payload={"event": f"strategy_{status.value}", "name": strategy.name},
    )
    return strategy


# ---------------------------------------------------------------------------
# Live candidates (feeds the S2.x agent pipeline)
# ---------------------------------------------------------------------------


def strategy_candidates(
    session: Session,
    *,
    user: User,
    state: AccountState,
    limits: RiskLimitSet,
    closes_by_symbol: dict[str, list[Decimal]],
    avg_costs: dict[str, Decimal],
) -> list[CandidateAction]:
    """Evaluate every ACTIVE strategy on the latest closes → candidate actions.

    Buys are suppressed while paused or past the drawdown threshold (same rule as S2.1
    momentum); the risk gate would veto them anyway, but a suggestion that can only be vetoed
    is noise, not teaching.
    """
    buys_allowed = not state.paused and (
        limits.drawdown_pause_pct is None or state.drawdown_pct < limits.drawdown_pause_pct
    )
    candidates: list[CandidateAction] = []
    rows = session.scalars(
        select(Strategy)
        .where(Strategy.user_id == user.id, Strategy.status == StrategyStatus.active)
        .order_by(Strategy.created_at)
    ).all()
    for strategy in rows:
        try:
            params = StrategyParams.model_validate(strategy.params)
        except ValidationError as e:  # stored rules should always validate; never crash the run
            log.warning("stored strategy %s invalid: %s", strategy.id, e)
            continue
        closes = closes_by_symbol.get(params.symbol, [])
        held = state.positions.get(params.symbol)
        entry_price = avg_costs.get(params.symbol) if held and held.quantity > 0 else None
        action = evaluate(closes, params, entry_price)
        if action == "enter" and buys_allowed:
            side = OrderSide.buy
        elif action == "exit":
            side = OrderSide.sell
        else:
            continue
        features: dict[str, Decimal] = {
            "entry_window": Decimal(params.entry.window),
            "size_pct": params.size_pct,
        }
        if closes:
            features["last_close"] = closes[-1]
        if entry_price is not None:
            features["entry_price"] = entry_price
        candidates.append(
            CandidateAction(
                kind="user_strategy",
                symbol=params.symbol,
                asset_class=AssetClass(params.asset_class),
                side=side,
                features=features,
                ref=f"user_strategy:{strategy.id}",
            )
        )
    return candidates
