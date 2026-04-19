---
title: Jay Trading Platform — Implementation Plan
type: implementation-spec
audience: coding-agent (Claude Code)
version: 1.0
last_updated: 2026-04-19
---

# Jay Trading Platform — Implementation Plan

An end-to-end build spec for an AI-executed, congressional/insider-signal-driven paper trading system on Alpaca. This document is the single source of truth for the agent doing the coding. Read it top to bottom before writing any code.

---

## How to use this document

- **Read the whole thing once** before starting Phase 0. Context in later phases affects decisions in earlier ones.
- **Complete phases in order.** Do not start Phase N+1 until Phase N's acceptance criteria are all green.
- **Stop points are non-negotiable.** When you see a 🛑 block, stop and get explicit user approval in chat before proceeding.
- **Show your work.** Every phase ends with you writing a short summary to `trading/briefings/phase_N_complete.md` in the Obsidian vault, listing what was built, what was tested, and what's deferred.
- **Ask if uncertain.** This spec leaves some decisions intentionally open. If you hit one, ask — don't guess.

---

## 1. Context recap (non-negotiable decisions)

| Decision | Value | Why |
|---|---|---|
| Trading mode | Alpaca **paper only** | No real money, period |
| Starting equity | **$10,000** (reset from $100K default) | Realistic constraint surface |
| Congressional + insider data | **FMP Starter** (~$19/mo) | Dual-chamber + insider + market data in one |
| Market data | FMP + Alpaca IEX (free tier) | Redundancy; yfinance as offline backup |
| Runtime | **Python service** (APScheduler in WSL) | Reliable; doesn't depend on Claude Code being open |
| Interactive layer | Claude Code + Alpaca MCP + mcp-obsidian | For analysis, tuning, and human-in-the-loop review |
| Persistence | SQLite (machine) + Obsidian markdown (human) | Both audiences served |
| Vault path | `/mnt/c/Users/jayna/OneDrive/Shared/Obsidian/trading` | Already exists |
| Project path | `~/mtn/k/trading/` (WSL) | New |
| Python version | 3.11+ | Modern typing, async |

---

## 2. Hard rules for the agent

These apply throughout the build. Violating any of these is a showstopper.

1. **Never touch the live Alpaca account.** Every API call uses the paper base URL: `https://paper-api.alpaca.markets`. If you ever see `api.alpaca.markets` (no `paper-`) in code or config, stop immediately.
2. **Never commit secrets.** `.env` is gitignored. If you suspect a key was committed, stop and tell the user.
3. **Never delete trade history or signal history.** Ever. If state corruption forces a wipe, ask first.
4. **Every order placed must have a rationale note** written to `trading/trades/` before the order is submitted. If rationale write fails, cancel the order.
5. **Every strategy ships in "shadow mode" first** (logs signals, does not execute) for a minimum of 7 calendar days before flipping to live paper execution.
6. **No strategy gets live paper execution without explicit user approval** (🛑 checkpoint).
7. **All scheduled jobs must be idempotent.** Running twice must not double-place orders or double-count signals.
8. **If anything unexpected happens in live execution, halt the strategy and notify.** Don't try to auto-recover trade logic in real-time.
9. **Markdown files in the vault are human-readable documents.** Don't dump raw JSON into them. Use tables, headings, frontmatter, human prose.
10. **Tests run before merge.** `pytest` green before any phase closes.

---

## 3. Architecture overview

```
┌─────────────────────────────────────────────────────────┐
│  Orchestration  (APScheduler in WSL, systemd service)   │
└─────────────────────────────────────────────────────────┘
           ↓                    ↓                   ↓
┌──────────────┐  ┌──────────────────┐  ┌──────────────────┐
│ Data Layer   │  │ Signal Layer     │  │ Execution Layer  │
│              │  │                  │  │                  │
│ • FMP        │→ │ • Politician     │→ │ • Alpaca SDK     │
│ • Alpaca     │  │   scorer         │  │ • Order builder  │
│ • SQLite     │  │ • Cluster detect │  │ • Fill tracker   │
└──────────────┘  │ • Sector flows   │  └──────────────────┘
                  │ • Insider cluster│           ↓
                  └──────────────────┘  ┌──────────────────┐
                           ↓            │ Risk Layer       │
                  ┌──────────────────┐  │ • Position size  │
                  │ Strategy Layer   │← │ • Portfolio heat │
                  │ (pluggable)      │  │ • Circuit breakrs│
                  │ • smart_copy     │  │ • Stop manager   │
                  │ • insider_follow │  └──────────────────┘
                  │ • sector_momentum│           ↓
                  └──────────────────┘  ┌──────────────────┐
                                        │ Persistence      │
                                        │ • SQLite         │
                                        │ • Obsidian vault │
                                        └──────────────────┘

Parallel interactive layer (not part of runtime):
  Claude Code + alpaca-mcp-server + mcp-obsidian
  → Used by user for analysis, tuning, manual override
```

### Key interfaces

Every strategy implements:

```python
class Strategy(ABC):
    name: str
    enabled: bool
    shadow_mode: bool

    @abstractmethod
    def generate_intents(
        self,
        signals: list[Signal],
        portfolio: PortfolioSnapshot,
    ) -> list[TradeIntent]: ...

    @abstractmethod
    def manage_positions(
        self,
        positions: list[Position],
        market_data: MarketSnapshot,
    ) -> list[TradeIntent]: ...
```

Every `TradeIntent` goes through the risk layer:

```python
def vet_intent(intent: TradeIntent, portfolio: PortfolioSnapshot) -> IntentDecision:
    # returns APPROVE / REJECT(reason) / MODIFY(new_intent)
```

The executor only ever places orders from approved intents.

---

## 4. Repo structure (target state)

```
~/mnt/k/trading
├── pyproject.toml
├── README.md
├── .env                                  # gitignored
├── .env.example                          # committed, no real values
├── .gitignore
├── .python-version                       # 3.11
├── alembic.ini
├── migrations/                           # SQLAlchemy/Alembic
│
├── src/jay_trading/
│   ├── __init__.py
│   ├── config.py                         # pydantic settings from .env
│   │
│   ├── data/
│   │   ├── fmp.py                        # FMP REST client
│   │   ├── alpaca_client.py              # thin wrapper over alpaca-py
│   │   ├── models.py                     # SQLAlchemy ORM models
│   │   └── store.py                      # DAO layer
│   │
│   ├── signals/
│   │   ├── politician_scorer.py
│   │   ├── cluster_detector.py
│   │   ├── insider_cluster.py
│   │   └── sector_flow.py
│   │
│   ├── strategies/
│   │   ├── base.py                       # Strategy ABC
│   │   ├── smart_copy.py
│   │   ├── insider_follow.py
│   │   └── sector_momentum.py
│   │
│   ├── risk/
│   │   ├── sizing.py
│   │   ├── portfolio_heat.py
│   │   ├── guards.py                     # circuit breakers
│   │   └── stop_manager.py
│   │
│   ├── executor/
│   │   ├── order_builder.py
│   │   ├── fills.py
│   │   └── reconcile.py
│   │
│   ├── vault/
│   │   ├── writer.py                     # markdown + YAML frontmatter
│   │   └── templates.py                  # jinja2 templates for notes
│   │
│   └── schedule/
│       ├── jobs.py                       # job definitions
│       └── service.py                    # APScheduler bootstrap
│
├── scripts/
│   ├── reset_paper_to_10k.py
│   ├── smoke_test.py
│   ├── run_briefing.py
│   ├── run_eod_summary.py
│   └── backtest.py
│
├── tests/
│   ├── test_fmp_client.py
│   ├── test_cluster_detector.py
│   ├── test_sizing.py
│   ├── test_guards.py
│   └── conftest.py                       # fixtures, VCR cassettes
│
└── deploy/
    ├── jay-trading.service               # systemd unit
    └── README.md                         # deploy instructions
```

---

## Phase 0 — Foundation

**Goal:** Plumbing. No strategy logic yet. End this phase able to (a) read Alpaca paper account balance, (b) fetch at least one senate trade from FMP, (c) write a markdown file to the Obsidian vault — all from Python.

**Duration:** ~1 session.

### Prerequisites (user-side, confirm before starting)

- [ ] FMP Starter account created; `FMP_API_KEY` available
- [ ] Alpaca paper API key + secret available
- [ ] WSL Python 3.11+ installed (`python3.11 --version`)
- [ ] `uv` installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- [ ] Obsidian vault exists at the documented path
- [ ] `mcp-obsidian` confirmed working in Claude Code (user reports this is done)

### Steps

1. **Reset Alpaca paper account to $10,000.**
   - In the Alpaca dashboard: Account → Reset (choose $10,000), OR create a new paper account with that starting balance.
   - Confirm via API: `GET /v2/account` → `equity` ≈ 10000, `cash` ≈ 10000.
   - Document the account_id in `.env` as `ALPACA_ACCOUNT_ID` for cross-reference safety.

2. **Install the official Alpaca MCP server into Claude Code.**
   - Repo: `https://github.com/alpacahq/alpaca-mcp-server`
   - Follow its README for Claude Code config. Pass `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` as env vars, not in the config file.
   - Keep the existing `mcp-obsidian` server; DO NOT remove the broken `npx`-based `obsidian` server yet — that's a separate cleanup task we'll log for later.
   - Verify from Claude Code: ask "what's my Alpaca account balance?" and confirm it returns $10,000.

3. **Scaffold the Python project.**
   ```bash
   cd ~/projects
   mkdir jay-trading && cd jay-trading
   uv init --python 3.11
   uv add alpaca-py requests httpx pydantic pydantic-settings \
          sqlalchemy alembic apscheduler python-dotenv pandas \
          jinja2 tenacity
   uv add --dev pytest pytest-cov pytest-mock ruff mypy vcrpy
   ```
   Create `.python-version` with `3.11`, `.gitignore` (include `.env`, `*.db`, `__pycache__`, `.venv`, `.pytest_cache`), and `.env.example`:
   ```
   # Alpaca (paper)
   ALPACA_API_KEY=
   ALPACA_SECRET_KEY=
   ALPACA_BASE_URL=https://paper-api.alpaca.markets
   ALPACA_ACCOUNT_ID=

   # FMP
   FMP_API_KEY=

   # Paths
   OBSIDIAN_VAULT_PATH=/mnt/c/Users/jayna/OneDrive/Shared/Obsidian/trading
   DATA_DIR=./data
   DB_URL=sqlite:///./data/jay_trading.db

   # Mode
   APP_ENV=development
   LOG_LEVEL=INFO
   ```

4. **Create Obsidian folder structure.** Create these empty folders (add a `.gitkeep` or `README.md` in each so Obsidian shows them):
   ```
   trading/
   ├── CLAUDE.md
   ├── watchlist.md
   ├── strategies/
   ├── signals/
   ├── briefings/
   ├── trades/
   ├── lessons/
   └── prompts/         (already exists)
   ```

5. **Write `trading/CLAUDE.md`.** This is the persistent system context that every Claude Code session in this vault should read. Template:

   ```markdown
   ---
   type: system-context
   updated: 2026-04-19
   ---

   # Jay Trading — Claude Code Context

   ## What this is
   An AI-executed paper trading system that uses congressional and insider
   disclosure data (via FMP) to generate signals and execute paper trades
   on Alpaca. $10,000 starting capital. Paper only — never live.

   ## Key locations
   - Code: ~/projects/jay-trading/ (WSL)
   - Vault: /mnt/c/Users/jayna/OneDrive/Shared/Obsidian/trading (this vault)
   - DB: ~/projects/jay-trading/data/jay_trading.db
   - Service: jay-trading.service (systemd, WSL)

   ## Active strategies
   (populated by agent as strategies go live)

   ## Rules you must always follow
   - Paper trading only. Never touch the live account.
   - Every trade needs a rationale note in trading/trades/ BEFORE execution.
   - Respect circuit breakers. If daily loss > 2% or drawdown > 8%, halt.
   - Don't delete trade history.
   - When in doubt, ask the user.

   ## How to help Jay
   - If Jay asks about the bot's recent activity, check trading/briefings/
     for the latest EOD summary first, then query the SQLite DB if needed.
   - For strategy tuning, read the strategy's .md file in trading/strategies/
     before changing parameters.
   - For code changes, preserve the Strategy/Risk/Executor layer boundaries.
   ```

6. **Write `scripts/smoke_test.py`.** Three round-trips, each must succeed:
   - Alpaca: `GET /v2/account` → print equity, cash, buying_power, confirm paper mode
   - FMP: `GET /stable/senate-trades?limit=5` (or the current endpoint) → print 5 most recent senate trades
   - Obsidian: write `trading/briefings/smoke_test_{ISO_DATE}.md` with a summary of the above

7. **Run the smoke test.** If any leg fails, fix before declaring Phase 0 done.

### Acceptance criteria

- [ ] `python scripts/smoke_test.py` prints three green checkmarks
- [ ] Alpaca paper `equity` is $10,000 ± $100 (slight slippage if orders were placed)
- [ ] `trading/CLAUDE.md` exists and is populated
- [ ] `.env.example` committed; `.env` gitignored and populated locally
- [ ] `uv run pytest` runs (even with zero tests) without import errors
- [ ] Claude Code can answer "what's my Alpaca balance" using the MCP server

### 🛑 Stop point 0

Before moving to Phase 1, send the user:
- Screenshot/text of smoke test output
- Confirmation that `trading/CLAUDE.md` is in place
- Any deviations from spec

Wait for user "go" before Phase 1.

---

## Phase 1 — Data layer and SQLite store

**Goal:** Reliable, idempotent data ingestion. Still no trading. End this phase with a daily job that ingests congressional + insider trades and writes a human-readable daily summary to the vault.

**Duration:** 1–2 sessions.

### Steps

1. **SQLAlchemy models** (`src/jay_trading/data/models.py`). Minimum schema:

   ```python
   # Pseudocode — use SQLAlchemy 2.0 declarative syntax

   class DisclosedTrade(Base):
       __tablename__ = "disclosed_trades"
       id: Mapped[int] = mapped_column(primary_key=True)
       source: Mapped[str]              # "senate" | "house" | "insider"
       person_name: Mapped[str]         # politician or insider name
       person_role: Mapped[str | None]  # committee, officer title, etc.
       ticker: Mapped[str]
       transaction_type: Mapped[str]    # "buy" | "sell" | "exchange"
       transaction_date: Mapped[date]
       filing_date: Mapped[date]
       amount_low: Mapped[float | None] # politicians report ranges
       amount_high: Mapped[float | None]
       amount_exact: Mapped[float | None]
       raw_payload: Mapped[dict]        # JSONB; preserve for auditing
       ingested_at: Mapped[datetime]
       __table_args__ = (
           UniqueConstraint("source", "person_name", "ticker",
                            "transaction_date", "amount_low", "amount_high"),
       )

   class Signal(Base):
       __tablename__ = "signals"
       id: Mapped[int] = mapped_column(primary_key=True)
       strategy_name: Mapped[str]
       ticker: Mapped[str]
       direction: Mapped[str]           # "long" | "short" | "flat"
       score: Mapped[float]             # strategy-specific
       rationale: Mapped[dict]          # JSON; what triggered it
       generated_at: Mapped[datetime]
       acted_on: Mapped[bool] = False
       acted_order_id: Mapped[str | None]

   class Position(Base):
       # mirrors Alpaca position + local metadata (strategy_name, entry_signal_id)
       ...

   class Order(Base):
       # our record of every order submitted; includes alpaca_order_id
       ...

   class Fill(Base):
       # reconciled from Alpaca fills
       ...

   class RiskEvent(Base):
       # circuit breaker trips, vetoes, etc.
       ...
   ```

   Set up Alembic; create initial migration.

2. **FMP client** (`src/jay_trading/data/fmp.py`).
   - One class `FMPClient` with methods: `senate_trades(limit, since)`, `house_trades(...)`, `insider_trades(ticker=None, since=None)`, `quote(ticker)`, `historical_prices(ticker, from_, to)`, `sector_performance()`.
   - Use `httpx` with retries (`tenacity`), rate limit to 250/min (below the 300/min FMP Starter cap for safety).
   - Record actual FMP endpoint paths in a constants module so they're easy to update when FMP changes them.
   - **Important:** FMP occasionally changes endpoint paths between v3/v4/stable. If an endpoint returns 404, log it loudly and surface to the user rather than silently swallowing.

3. **Alpaca client** (`src/jay_trading/data/alpaca_client.py`).
   - Thin wrapper on `alpaca-py`. Methods: `get_account()`, `get_positions()`, `get_orders(status, after)`, `submit_order(intent)`, `close_position(symbol, qty)`, `latest_quote(symbol)`.
   - Hard-enforce paper URL at construction time — raise if base_url doesn't contain `paper-`.

4. **Store / DAO** (`src/jay_trading/data/store.py`).
   - `upsert_disclosed_trades(list[DisclosedTrade])` — idempotent by unique constraint
   - `recent_trades(source, since) -> list[DisclosedTrade]`
   - `unique_tickers_traded_by(person_name, since)`
   - Helpers for positions, orders, signals, risk events

5. **Ingestion job** (`src/jay_trading/schedule/jobs.py::ingest_disclosures`).
   - Pull last 14 days of senate, house, insider trades from FMP
   - Upsert into SQLite
   - Count new vs existing
   - Write a daily markdown summary to `trading/briefings/YYYY-MM-DD_data.md` using a jinja2 template:
     ```markdown
     ---
     type: data-briefing
     date: 2026-04-20
     ---
     # Data ingestion — 2026-04-20

     ## Senate trades (new today)
     | Senator | Ticker | Side | Tx Date | Filing Date | Amount |
     | ... |

     ## House trades (new today)
     ...

     ## Insider trades (new today)
     ...

     ## Stats
     - Total new rows: X
     - Politicians active (7d): Y
     - Most-traded ticker (7d): Z (N trades)
     ```

6. **Tests** (`tests/test_fmp_client.py`, `tests/test_store.py`).
   - VCR-recorded cassettes of real FMP responses (commit cassettes, redact API key)
   - Assert upsert idempotency: run twice, row count unchanged
   - Assert required fields populated

### Acceptance criteria

- [ ] `uv run python -m jay_trading.schedule.jobs ingest` runs end-to-end
- [ ] Running it twice does not create duplicates
- [ ] SQLite DB has > 0 rows in senate, house, insider sources
- [ ] `trading/briefings/YYYY-MM-DD_data.md` exists and renders nicely in Obsidian
- [ ] `pytest` green with ≥ 5 tests covering FMP + store

### 🛑 Stop point 1

Before Phase 2, show the user:
- Count of rows ingested per source
- One sample markdown briefing
- Test coverage report (`pytest --cov`)

---

## Phase 2 — Strategy #1: Smart Congress Copy

**Goal:** First strategy end-to-end. Runs in shadow mode for 7 days, then (with user approval) goes live paper.

**Duration:** 2 sessions.

### Design

**Core thesis:** Individual politician trades have weak signal due to 45-day disclosure lag. But *clusters* — multiple politicians converging on the same ticker within a narrow window — are informative. We further filter by (a) politician quality and (b) committee relevance.

**Parameters (tunable, initially):**

| Parameter | Value | Rationale |
|---|---|---|
| Cluster window | 14 days | Long enough to catch convergence, short enough to be timely |
| Cluster min members | 2 distinct politicians | Start loose; tighten if too many signals |
| Cluster direction | same side (both buys or both sells) | Mixed = noise |
| Politician filter | trailing-6mo return > 0 | Cheap quality gate |
| Committee bonus | +20% score if ≥1 member is on a relevant committee | Known in literature |
| Position size | 5% of current equity | Hard cap |
| Max concurrent positions (this strategy) | 10 | Diversification |
| Entry type | market-on-open next trading day | Simple, good enough |
| Hard stop | -8% from entry | Risk cap |
| Trail activation | +10% from entry | Lock in gains |
| Trail distance | 5% below peak | Standard |
| Exit on signal reversal | yes (2+ politicians selling in 14d) | Symmetric logic |

**Why these specifics:** they're reasonable defaults, not optimal. Phase 2 ships working; tuning happens in Phase 7+.

### Steps

1. **Politician scorer** (`signals/politician_scorer.py`).
   - Inputs: all `DisclosedTrade`s for a politician over last 180 days
   - For each buy/sell, compute the return that position would have had if held to today (or until matching sell). Price data from FMP historical.
   - Output: `{person_name: trailing_6mo_return_pct}` sorted.
   - Cache results; this is slow.

2. **Cluster detector** (`signals/cluster_detector.py`).
   - Given recent disclosed trades, group by `(ticker, direction)` and slide a 14-day window over filing_dates.
   - A cluster = ≥2 distinct politicians filing same-direction trades within the window.
   - Emit `Signal` rows with rationale JSON:
     ```json
     {
       "strategy": "smart_copy",
       "cluster": {
         "ticker": "NVDA",
         "direction": "buy",
         "window_start": "2026-04-05",
         "window_end": "2026-04-19",
         "members": [
           {"name": "Jane Doe", "party": "R", "role": "Rep",
            "committee": "Armed Services", "quality_score": 0.08,
            "tx_date": "2026-04-07", "amount_range": "15K-50K"},
           ...
         ],
         "committee_bonus_applied": true
       },
       "computed_score": 0.73
     }
     ```
   - Score formula (initial): `base = min(n_members, 5) / 5`, `quality_mult = mean(quality_scores > 0 ? 1.2 : 0.8)`, `committee_mult = 1.2 if any relevant committee else 1.0`. Clip to [0,1].
   - Committee relevance mapping: start with a hand-built dict (e.g., Armed Services → defense tickers, Finance → financials, Energy → energy/utilities). Don't over-engineer this; iterate later.

3. **SmartCopyStrategy** (`strategies/smart_copy.py`).
   - Extends `Strategy` base class.
   - `generate_intents(signals, portfolio)`: for each signal with score > 0.5 not already acted on, and where we have <10 open positions from this strategy, and we don't already hold this ticker, emit a `TradeIntent(ticker, side, notional=5% equity)`.
   - `manage_positions(positions, market_data)`: implement the stop logic (hard stop, trail activation, trail update, signal-reversal exit).

4. **Order builder** (`executor/order_builder.py`).
   - Convert `TradeIntent` to Alpaca `MarketOrderRequest` (or `LimitOrderRequest` where appropriate).
   - Use fractional shares via `notional=` parameter.
   - Attach `client_order_id = f"{strategy}_{signal_id}_{uuid4()[:8]}"` for reconciliation.

5. **Rationale writer** (`vault/writer.py`).
   - Before submitting any order, write `trading/trades/YYYY-MM-DD_{ticker}_{side}.md`:
     ```markdown
     ---
     type: trade-rationale
     date: 2026-04-20T13:45:00-04:00
     strategy: smart_copy
     ticker: NVDA
     side: buy
     notional: 500
     signal_id: 42
     status: submitted
     ---
     # NVDA buy — smart_copy — 2026-04-20

     ## Why
     Cluster of 3 politicians filed NVDA buys in the last 14 days:
     - Jane Doe (R-TX), Rep, Armed Services — bought 15K–50K on 2026-04-07
     - ...

     ## Risk
     - Position size: $500 (5% of $10,000 equity)
     - Hard stop: -8% ($460)
     - Trail activation: +10% ($550)

     ## Alpaca order
     - order_id: (filled after submission)
     - client_order_id: smart_copy_42_ab12cd34
     ```
   - If the write fails, **do not submit the order**.

6. **Shadow mode toggle.**
   - `strategies/base.py` has a `shadow_mode: bool` flag.
   - When `shadow_mode=True`, strategy runs fully but `order_builder.submit()` is replaced with a mock that logs what would have been placed.
   - Shadow logs go to `trading/trades/shadow/YYYY-MM-DD_*.md` with `status: shadow` in frontmatter.

7. **Tests.**
   - Cluster detector unit tests with fixture data (known clusters, known non-clusters)
   - Strategy unit tests with mocked signals + portfolio
   - Integration test: generate signals from real ingested data, assert output shape

### Acceptance criteria (Phase 2A — shadow)

- [ ] After 7 days of ingestion, ≥ 1 cluster signal has been detected (or we've confirmed the threshold is too high and tuned it)
- [ ] Every signal has a rationale note in `trading/trades/shadow/`
- [ ] No real orders have been submitted
- [ ] Tests green, coverage ≥ 70% for cluster_detector and smart_copy

### 🛑 Stop point 2A — before going live

Send the user a **review packet** with:
- Last 7 days of shadow signals and rationales
- What would P&L have been if we'd executed them? (Approximate — use daily close prices)
- Any obvious false positives the user should know about
- Parameter values currently in use
- Explicit ask: "Approve flipping SmartCopy to live paper execution?"

Only flip to live on explicit "yes, go live."

### Acceptance criteria (Phase 2B — live paper)

- [ ] First live paper order submitted and filled on Alpaca paper
- [ ] Rationale note written before submission; order_id patched in after fill
- [ ] Position appears in `get_positions()` and is tracked in our `Position` table
- [ ] Stop orders placed as separate Alpaca orders (not just in our memory)
- [ ] `trading/strategies/smart_copy.md` exists with status: `active` and live parameters

---

## Phase 3 — Risk layer

**Goal:** Harden execution before adding more strategies. Retrofit SmartCopy to route through the risk layer.

**Duration:** 1 session.

### Components

1. **Position sizer** (`risk/sizing.py`).
   - Fixed fractional (default 5% of equity) with an override for vol-scaled sizing (size = target_risk_dollars / (ATR_14 * 2)).
   - Respect max position size (10% of equity) hard cap regardless of strategy ask.

2. **Portfolio heat** (`risk/portfolio_heat.py`).
   - Max 30% in any single GICS sector (pull sector via FMP profile endpoint)
   - Max 25% total open risk (sum of per-position max losses)
   - Reject new position if 90-day price correlation > 0.85 with existing position

3. **Circuit breakers** (`risk/guards.py`).
   - Daily loss: if realized + unrealized P&L today < -2% of starting equity, halt all new entries (existing positions can still close).
   - Drawdown: if equity < 92% of 30-day rolling high, halt **all** strategies (including exits — force manual review).
   - Connectivity: if Alpaca API fails 3 times in 5 minutes, halt.
   - Data staleness: if FMP hasn't returned fresh data in 24 hours, halt new entries.
   - Every trip writes a `RiskEvent` row and a note to `trading/briefings/incidents/`.

4. **Pre-trade check pipeline** (`risk/vet.py`).
   ```python
   def vet(intent: TradeIntent, portfolio: PortfolioSnapshot) -> IntentDecision:
       for check in [check_circuit_breakers, check_sizing, check_heat,
                     check_correlation, check_duplicate, check_funds]:
           decision = check(intent, portfolio)
           if decision.verdict != "APPROVE":
               log_veto(intent, check.__name__, decision.reason)
               return decision
       return IntentDecision.APPROVE(intent)
   ```

5. **Stop manager** (`risk/stop_manager.py`).
   - Centralized stop management. Strategies declare stop rules on entry; stop manager tracks all open positions each tick and places/modifies/cancels Alpaca stop orders.
   - Runs every 15 min during market hours.

### Acceptance criteria

- [ ] All SmartCopy orders now pass through `vet_intent`; direct executor calls removed
- [ ] Circuit breaker tests: can force-trip each breaker via mocked data; all emit RiskEvents and halt as expected
- [ ] Stop orders on Alpaca match our internal stop tracking after each cycle
- [ ] Manual test: try to submit an oversized intent → rejected with clear reason in logs

---

## Phase 4 — Strategy #2: Insider cluster follow

**Goal:** Add a second, structurally stronger signal (insider Form 4 filings, 2-day lag vs. 45-day).

**Duration:** 1 session.

### Design

- Cluster definition: ≥3 distinct insiders buying same issuer within 30 days
- **Buys only** — insider sells are noisy (taxes, 10b5-1 plans, diversification); buys are almost always voluntary conviction
- Role filter: weight CEO (3x), CFO (2x), COO/other officers (1.5x), directors (1x), 10% holders (0.5x)
- Exclude: companies in chapter 11, companies with market cap < $300M (liquidity), ETFs
- Score: `(weighted_count / 5)` capped at 1.0
- Position size: 4% of equity
- Stop: -10% hard, trail at 8% below peak after +12% gain
- Max concurrent (this strategy): 8

### Steps

1. `signals/insider_cluster.py` — same pattern as `cluster_detector.py`, adapted for insider data and role weighting
2. `strategies/insider_follow.py` — implements `Strategy`
3. Register in strategy registry
4. Shadow for 7 days
5. 🛑 Stop point 4 — user approval to go live

### Acceptance criteria

Same structure as Phase 2. Shadow logs → review → live approval → first order.

---

## Phase 5 — Strategy #3: Sector momentum

**Goal:** Lower-variance aggregate strategy on sector ETFs. Uses congressional sector flows as one input among several.

**Duration:** 1 session.

### Design

- Universe: 11 SPDR sector ETFs (XLK, XLF, XLE, XLV, XLY, XLP, XLI, XLU, XLB, XLC, XLRE)
- Ranking composite (weekly rebalance):
  - 40% — congressional net buy dollars in sector (last 30 days, across senate+house, normalized)
  - 40% — 90-day total return
  - 20% — relative strength vs SPY over 30 days
- Holdings: top 3 sectors, equal-weighted, ~20% of equity each (so strategy uses up to 60% of equity)
- Rebalance: Monday 10:00 ET after first-hour volatility settles
- Exit: drop from top 3 → sell on next rebalance
- No stops — this is a momentum strategy, whipsaws are the cost of the premium
- Correlation check (Phase 3 risk layer) will likely block some combinations; that's fine

### Steps

1. `signals/sector_flow.py` — aggregate congressional dollar flow by GICS sector (use FMP `/profile/{ticker}` → sector, or a static mapping for big tickers)
2. `strategies/sector_momentum.py`
3. Backtest on 2 years of historical congressional data (`scripts/backtest.py`) before even shadow mode — this is a slower-moving strategy, backtest is meaningful
4. Shadow 14 days (one rebalance cycle + buffer)
5. 🛑 Stop point 5 — user approval

### Acceptance criteria

- [ ] Backtest report in `trading/lessons/backtest_sector_momentum.md` with Sharpe, max DD, hit rate
- [ ] Shadow mode logs a rebalance event
- [ ] Live: first rebalance executes cleanly, correlation rejections documented

---

## Phase 6 — Orchestration

**Goal:** Self-running service. No more manual `python -m` invocations.

**Duration:** 1 session.

### Schedule (all times ET)

| Time | Job | Purpose |
|---|---|---|
| 08:30 | `ingest_disclosures` | Pull fresh FMP data |
| 08:40 | `generate_signals` | Run all detectors |
| 08:45 | `write_morning_briefing` | Compose morning note |
| 09:35 | `execute_strategies` | Place orders after first-5-min vol |
| 10:00 Mon | `sector_momentum_rebalance` | Weekly rebalance |
| 12:00 | `manage_stops` | Midday stop check |
| 12:00 | `check_circuit_breakers` | Risk check |
| 15:00 | `manage_stops` | Late stop check |
| 15:55 | `eod_wrap_up` | Reconcile fills, finalize positions |
| 16:10 | `write_eod_summary` | Daily summary note |
| Sun 18:00 | `weekly_review` | Weekly note |

### Steps

1. `schedule/service.py` — APScheduler `BlockingScheduler` with all jobs registered.
2. `deploy/jay-trading.service` — systemd unit file for WSL (since WSL 2 supports systemd).
3. Health check: job writes a heartbeat file every 5 minutes (`data/heartbeat.txt`). A separate cron job checks staleness and alerts via `trading/briefings/incidents/` if stale.
4. Graceful shutdown: on SIGTERM, finish current job, do not start new ones.
5. Logging: rotating file logs in `~/projects/jay-trading/logs/`, `INFO` to file, `WARNING+` also to a `trading/briefings/incidents/` file.

### Acceptance criteria

- [ ] `systemctl --user start jay-trading` starts the service
- [ ] Service survives `wsl --shutdown && wsl` cycle (or documented manual restart procedure)
- [ ] Heartbeat file updates every ≤5 min
- [ ] One full market-day cycle runs without manual intervention

### 🛑 Stop point 6

Walk the user through:
- How to start/stop the service
- Where logs live
- How to kill-switch trading (recommended: set all strategies to `enabled=False` in a config table and reload)
- How to add a new strategy

---

## Phase 7 — Observability and weekly review

**Goal:** Close the human-in-the-loop loop. Make it easy for the user (and Claude Code) to understand what happened and decide what to change.

**Duration:** 1 session.

### Artifacts

1. **Morning briefing** (`trading/briefings/YYYY-MM-DD_morning.md`):
   - Account state (equity, cash, buying power)
   - Open positions with P&L
   - Signals generated overnight, classified by strategy
   - Planned trades for today
   - Circuit breaker status
   - Market context (SPY, QQQ, VIX pre-market — via FMP)

2. **EOD summary** (`trading/briefings/YYYY-MM-DD_eod.md`):
   - P&L attribution by strategy
   - Fills today
   - Any veto'd intents and why
   - Incidents (if any)
   - Drawdown / equity curve snapshot

3. **Weekly review** (`trading/briefings/YYYY-Www_weekly.md`, runs Sunday 18:00):
   - Week P&L by strategy
   - Hit rate, avg win/loss, profit factor
   - Top winners/losers
   - Open questions for user (e.g., "Strategy X has 0 signals in 14 days — tune or kill?")
   - Suggested actions

### Steps

1. Jinja2 templates for each briefing type in `vault/templates.py`
2. Jobs in `schedule/jobs.py`
3. Tests for template rendering with fixture data

### Acceptance criteria

- [ ] One week of briefings exists in the vault
- [ ] Weekly review surfaces at least one actionable item
- [ ] Templates render cleanly in Obsidian (headings, tables, no broken markdown)

---

## Ongoing — tuning, backtesting, extending

Not a phase; the steady-state mode after Phase 7.

### Backtesting framework

- `scripts/backtest.py` accepts a strategy name and a date range
- Pulls historical disclosed trades from our SQLite store
- Simulates the strategy against historical price data
- Produces Sharpe, max DD, hit rate, profit factor, a trade-by-trade log
- Writes report to `trading/lessons/backtest_{strategy}_{date}.md`

### Tuning rhythm

- Never tune a strategy on data it's currently trading on — you'll overfit
- Use an 18-month backtest + 3-month out-of-sample validation
- Parameter changes require a `trading/lessons/tuning_{strategy}_{date}.md` note documenting before/after and why

### Adding a new strategy

1. Design note in `trading/strategies/{name}_design.md` — rationale, parameters, expected Sharpe
2. Implement signal module if new
3. Implement `Strategy` subclass
4. Backtest
5. Shadow 7 days
6. 🛑 User approval
7. Live, with reduced sizing (50% of target) for first 30 days

---

## Appendix A — Environment variables

| Var | Required | Purpose |
|---|---|---|
| `ALPACA_API_KEY` | yes | Paper API key |
| `ALPACA_SECRET_KEY` | yes | Paper secret |
| `ALPACA_BASE_URL` | yes | Must contain `paper-` |
| `ALPACA_ACCOUNT_ID` | yes | Safety cross-check |
| `FMP_API_KEY` | yes | FMP Starter key |
| `OBSIDIAN_VAULT_PATH` | yes | Vault root |
| `DATA_DIR` | yes | SQLite location |
| `DB_URL` | yes | SQLAlchemy URL |
| `APP_ENV` | yes | `development` | `production` |
| `LOG_LEVEL` | no | default `INFO` |

---

## Appendix B — Base interfaces

```python
# src/jay_trading/strategies/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

@dataclass
class TradeIntent:
    strategy_name: str
    ticker: str
    side: str                 # "buy" | "sell"
    notional: float | None    # dollars; mutually exclusive with qty
    qty: float | None
    order_type: str           # "market" | "limit"
    limit_price: float | None
    time_in_force: str        # "day" | "gtc"
    stop_price: float | None
    rationale: dict
    signal_id: int | None

@dataclass
class IntentDecision:
    verdict: str              # "APPROVE" | "REJECT" | "MODIFY"
    reason: str | None
    modified_intent: TradeIntent | None

class Strategy(ABC):
    name: str
    enabled: bool = False
    shadow_mode: bool = True
    max_concurrent_positions: int = 10

    @abstractmethod
    def generate_intents(
        self,
        signals: list[Signal],
        portfolio: PortfolioSnapshot,
    ) -> list[TradeIntent]: ...

    @abstractmethod
    def manage_positions(
        self,
        positions: list[Position],
        market_data: MarketSnapshot,
    ) -> list[TradeIntent]: ...
```

---

## Appendix C — Common gotchas

- **Alpaca paper URL.** `paper-api.alpaca.markets`, not `api.alpaca.markets`. Enforce at client construction.
- **Fractional shares + stop orders.** Alpaca does not support stop orders on fractional positions. If a position is fractional, manage the stop in-software and submit a market close when the stop is hit.
- **FMP rate limits.** 300/min on Starter, but some endpoints are pricier. Stay at 250/min ceiling.
- **FMP endpoint drift.** They shift between `/api/v3/`, `/api/v4/`, and `/stable/` without notice. Centralize endpoint paths in one module.
- **Politician name normalization.** "Nancy Pelosi" vs "Pelosi, Nancy" vs "Rep. Nancy Pelosi (D-CA)" — build a name-canonicalizer early, don't put off. Save aliases in a `person_aliases` table.
- **Ticker symbol changes.** Tickers get renamed (FB → META). Resolve current ticker from FMP profile at ingestion.
- **STOCK Act amounts are ranges.** Politicians report "$15,001 – $50,000" etc. Use the geometric mean for sizing estimates, not max or min.
- **PDT rule on paper.** Paper trading simulates the PDT rule. At $10K equity you're below the $25K threshold; design strategies that don't require > 3 day trades in 5 business days.
- **Market hours edge cases.** Half-days before holidays; early closes. Use FMP's market hours endpoint, don't hardcode.
- **Daylight saving.** APScheduler + America/New_York timezone handles it; don't do anything clever.
- **Obsidian sync conflicts.** OneDrive occasionally creates `filename (conflicted).md`. Write atomically (write to `.tmp`, then rename).

---

## Appendix D — Phase-transition checklist (use verbatim each phase)

```
## Phase N complete — checklist

- [ ] All acceptance criteria ticked
- [ ] Tests green; coverage report attached
- [ ] CHANGELOG updated
- [ ] trading/briefings/phase_N_complete.md written
- [ ] No new secrets committed
- [ ] Service (if running) still healthy
- [ ] User notified; explicit "go" received for Phase N+1
```

---

## Appendix E — What we are explicitly NOT building (yet)

Logged so nobody drifts into these:

- Options strategies (wheel, covered calls, spreads) — capital too low
- Live (non-paper) execution — not until the user opens a live account and gives explicit written approval
- ML-based signals — manual, interpretable features first; ML only after we understand the base rates
- Multi-broker support — Alpaca only
- Non-US markets — US equities + US ETFs only
- Crypto — separate project
- Web UI / dashboard — Obsidian is the UI
- Slack/email alerts — vault notes only for now

---

## Appendix F — Disclaimer

This is a paper trading system for educational purposes. Past backtest performance is not indicative of future real-money results. The strategies implemented here (congressional copy, insider cluster, sector momentum) are all documented in the academic and retail literature and have produced mixed live results. Nothing in this codebase is financial advice. Do not migrate to live trading without independent analysis of the risks.
