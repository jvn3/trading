# AlphaDash — Build Tracker (live)

Single source of truth for build progress on the beginner strategy-agent product.
Companion to the blueprint: [docs/product/beginner_agent_product_blueprint.md](../docs/product/beginner_agent_product_blueprint.md).

> **This file is meant to be updated by whoever (human or agent) does the work.** Keep it current.

---

## How to use this file (agent instructions)

1. **Pick the lowest-numbered session whose dependencies are all `[x]`.** Do not start a session
   whose `Depends on` list has unfinished items.
2. **Read the session's Frozen Contract before writing anything.** The contract is the spec — do not
   deviate from interface/schema/prop shapes. If a contract is marked _"freeze before start"_, stop
   and get it frozen (by the operator) first; do not invent it.
3. **Set status as you go:** `[~]` when you start, `[x]` when every acceptance box is checked, `[!]`
   if blocked (add a `Blocked:` line with the reason).
4. **Tick each acceptance sub-box** only when it is genuinely true (tests actually run green, etc.).
5. **Fill the `Landed:` line** on completion: date · commit/PR · one-line note. Never delete a
   session; if you discover new work, add it under that session's `Notes:`.
6. **Also append one entry to** `development/log.md` (repo convention) after code changes.
7. **Never flip `trading_mode` off `paper`.** Real money is Phase 5 only, gated by counsel.

**Status legend:** `[ ]` to-do · `[~]` in progress · `[x]` done · `[!]` blocked

---

## Progress summary

| Phase | Theme | Sessions | Done |
|---|---|---|---|
| 0 | Foundations | S0.1–S0.4 | 4 / 4 |
| 1 | Safety & data spine (no AI) | S1.1–S1.12 | 12 / 12 |
| 2 | The agent | S2.1–S2.9 | 0 / 9 |
| 3 | Beginner experience | S3.1–S3.7 | 0 / 7 |
| 4 | Trust-earning extensions | S4.x | not scoped |
| 5 | Real-money mode (gated) | S5.x | not scoped |

**Phase gate — do not start Phase 2 until this is true:** a user can place a limit-checked,
reconciled, journaled paper trade and see honest performance **with zero AI in the loop.**

---

# Phase 0 — Foundations

## `[x]` S0.1 — Repo scaffold, CI, lint/test harness, secrets config
- **Depends on:** —
- **Deliverable:** isolated `alphadash/` monorepo (backend + frontend), path-scoped CI, config.
- **Acceptance:**
  - [x] Backend: `uv sync` + `ruff check` + `ruff format --check` + `pytest` all green
  - [x] Backend `GET /health` returns `{status, version, trading_mode}` with `trading_mode="paper"`
  - [x] Frontend: `npm run test` + `npm run lint` + `npm run build` all green
  - [x] Frontend wired with Zustand (UI state) + TanStack Query (server state), `/api` → `:8000`
  - [x] CI at `.github/workflows/alphadash-ci.yml`, path-scoped to `alphadash/**`
  - [x] Zero changes to root `pyproject.toml` / `uv.lock` (live engine untouched)
- **Landed:** 2026-07-08 · scaffold in-session · backend 2 tests + frontend 1 test green.
- **Notes:** `npm install` flags 5 transitive dev advisories — run `npm audit` before beta.
  `jay_trading` reuse intentionally deferred to S1.1.

---

## `[x]` S0.2 — Data model + Alembic migrations (§9.4 entities)
- **Depends on:** S0.1
- **Goal:** model every §9.4 entity as SQLAlchemy 2.0 typed models with isolated Alembic migrations.
- **Deliverable:**
  - `alphadash/backend/src/alphadash/db/base.py` (declarative base, metadata, UTC mixin)
  - `alphadash/backend/src/alphadash/db/models.py` (all entities)
  - `alphadash/backend/alembic.ini` + `alphadash/backend/migrations/` (isolated from root alembic)
  - `alphadash/backend/tests/test_schema.py`

### FROZEN CONTRACT — S0.2

**Global rules (non-negotiable):**
- Primary keys: `id` = `str` UUID (`uuid4().hex`), generated app-side.
- All tables carry `created_at` (tz-aware UTC, server default now). Mutable tables also `updated_at`.
- **Money & quantities: `Numeric` / `Decimal` only — never `Float`.** Prices, quantities, amounts,
  fees, equity all `Numeric(24, 8)`.
- Timestamps: `DateTime(timezone=True)`, stored UTC.
- Enums: SQLAlchemy `Enum` (or `String` + `CheckConstraint`) with the exact members listed below.
- **Tenant scoping:** every user-owned row is reachable via `user_id` (directly or through `account`).
  Physical RLS enforcement is S1.8 — S0.2 only guarantees the columns + FKs exist.
- FKs enforced (`ForeignKey(..., ondelete=...)`); no orphan rows.

**Tables & key columns:**

| Table | Columns (type) | Enums / notes |
|---|---|---|
| `users` | id, email (unique), display_name, created_at | — |
| `risk_profiles` | id, user_id→users, name, max_position_pct (Num), max_asset_class_pct (JSON `{equity,crypto}`), max_trades_per_week (int), cash_floor_pct (Num), per_suggestion_max_pct (Num), drawdown_pause_pct (Num), created_at, updated_at | name ∈ {conservative, balanced, curious, custom} |
| `accounts` | id, user_id→users, mode, base_currency (str, default "USD"), starting_equity (Num), created_at | mode ∈ {paper, real}; **default paper** |
| `cash_balances` | id, account_id→accounts, currency (str), amount (Num) | unique(account_id, currency) |
| `positions` | id, account_id→accounts, symbol, asset_class, quantity (Num), avg_cost (Num), updated_at | asset_class ∈ {equity, crypto}; unique(account_id, symbol) |
| `orders` | id, account_id→accounts, symbol, asset_class, side, order_type, qty (Num), limit_price (Num, null), status, idempotency_key (unique), rejected_reason (str, null), suggestion_id→suggestions (null), created_at, updated_at | side ∈ {buy,sell}; order_type ∈ {market,limit}; status ∈ {pending,validated,rejected,submitted,filled,cancelled} |
| `fills` | id, order_id→orders, qty (Num), price (Num), fee (Num, default 0), filled_at | — |
| `suggestions` | id, account_id→accounts, headline, rationale (Text), confidence (Num 0–1), confidence_basis (Text), candidate_ref (str), prompt_version (str), model_version (str), status, falsifier (Text), reversibility (Text), sizing (JSON), evidence (JSON), worst_case (Text), blocked_reason (str, null), created_at, expires_at (null) | status ∈ {proposed,approved,modified,dismissed,expired,blocked} |
| `decisions` | id, suggestion_id→suggestions, action, reason (Text, null), modified_sizing (JSON, null), decided_by, created_at | action ∈ {approve,modify,dismiss}; decided_by ∈ {user,auto} |
| `risk_limits` | id, account_id→accounts, limit_type, value (Num), created_at | limit_type ∈ {max_position_pct, max_asset_class_pct, max_trades_per_week, cash_floor_pct, per_suggestion_max_pct, drawdown_pause_pct} |
| `risk_events` | id, account_id→accounts, event_type, detail (JSON), order_id (null), suggestion_id (null), created_at | event_type ∈ {breach,veto,auto_pause,reconcile_discrepancy} |
| `journal_entries` | id, account_id→accounts, entry_type, ref_id (str), payload (JSON), created_at | **append-only**; entry_type ∈ {suggestion,decision,order,fill,risk_event,note} |
| `watchlists` | id, user_id→users, name, created_at | — |
| `watchlist_items` | id, watchlist_id→watchlists, symbol, asset_class | unique(watchlist_id, symbol) |
| `agent_runs` | id, account_id→accounts, trigger, prompt_version, model_version, status, cost_tokens (int, null), input_snapshot_id→data_snapshots (null), started_at, completed_at (null) | trigger ∈ {scheduled,event,on_demand}; status ∈ {running,completed,failed} |
| `data_snapshots` | id, agent_run_id→agent_runs (null), payload (JSON), created_at | point-in-time inputs; no lookahead |

- **Acceptance:**
  - [x] All 16 tables above modeled in `db/models.py` with the exact columns/enums
  - [x] Money/quantity columns are `Numeric(24,8)`; zero `Float` columns
  - [x] Timestamps tz-aware UTC; PKs are uuid4 hex strings
  - [x] Alembic isolated under `alphadash/backend/`; `alembic upgrade head` **and** `downgrade base` run clean on sqlite
  - [x] `test_schema.py`: creating metadata yields exactly this table set; unique/FK constraints assert-tested
  - [x] `ruff check` + `ruff format --check` + `pytest` green
- **Out of scope:** RLS enforcement (S1.8), business logic, any HTTP endpoint, Postgres tuning.
- **Landed:** 2026-07-08 · in-session · 16 tables, migration `0001`, 13 schema tests green.
- **Notes:** Circular FK `agent_runs.input_snapshot_id` ↔ `data_snapshots.agent_run_id` uses
  `use_alter=True` on the snapshot FK so `create_all`/Alembic sort cleanly. Enums are non-native
  (`VARCHAR` + CHECK) storing enum *values*, portable sqlite↔Postgres. Deps added to backend
  pyproject only: `sqlalchemy`, `alembic`.

---

## `[x]` S0.3 — Provider interfaces + fixture-backed stub
- **Depends on:** S0.1
- **Goal:** define swappable data-source interfaces with mandatory provenance + freshness, plus a
  deterministic stub. Real implementations (against `jay_trading`) come in S1.1.
- **Deliverable:**
  - `alphadash/backend/src/alphadash/providers/dto.py`
  - `alphadash/backend/src/alphadash/providers/base.py`
  - `alphadash/backend/src/alphadash/providers/freshness.py`
  - `alphadash/backend/src/alphadash/providers/stub.py`
  - `alphadash/backend/tests/test_providers_stub.py`

### FROZEN CONTRACT — S0.3

**DTOs (pydantic v2, `Decimal` for numbers). Every DTO embeds `Provenance`.**
```
Provenance:      source: str, as_of: datetime (UTC), is_stale: bool = False
Quote:           symbol, price: Decimal, bid: Decimal|None, ask: Decimal|None, provenance
Bar:             symbol, timeframe: str, open/high/low/close: Decimal, volume: Decimal, ts: datetime, provenance
NewsItem:        id: str, symbols: list[str], headline, summary: str|None, url: str|None, published_at: datetime, source: str, sentiment: float|None
FundamentalSnapshot: symbol, as_of: datetime, metrics: dict[str, Decimal], provenance
MacroPoint:      series_id: str, ts: datetime, value: Decimal, provenance
```

**Protocols (sync — matches existing `jay_trading` clients; FastAPI runs them in a threadpool):**
```
MarketDataProvider(Protocol):
    def get_quote(self, symbol: str) -> Quote: ...
    def get_bars(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> list[Bar]: ...

NewsProvider(Protocol):
    def get_news(self, symbols: list[str], since: datetime, limit: int = 50) -> list[NewsItem]: ...

FundamentalsProvider(Protocol):
    def get_fundamentals(self, symbol: str) -> FundamentalSnapshot: ...

MacroProvider(Protocol):
    def get_series(self, series_id: str, since: datetime) -> list[MacroPoint]: ...
```

**Freshness:**
```
FreshnessPolicy: max_age: dict[str, timedelta]  # keyed by feed name: "quote","bar","news","fundamentals","macro"
    def stamp(self, feed: str, dto) -> dto      # sets provenance.is_stale = (now - as_of) > max_age[feed]
```
- Rule (enforced downstream, declared here): stale data must **lower confidence or block suggestions**,
  never silently feed decisions. `is_stale=True` is how that signal travels.

**Errors:** `ProviderError(Exception)`, `StaleDataError(ProviderError)`.

- **Acceptance:**
  - [x] All DTOs + 4 Protocols defined with the exact signatures above; provenance mandatory
  - [x] `FreshnessPolicy.stamp` flags stale by max-age (unit-tested with fixed `now` passed in — no wall-clock in logic)
  - [x] `StubProviders` implements every protocol returning deterministic fixtures
  - [x] `test_providers_stub.py`: stub returns fixtures; stale detection true/false cases pass
  - [x] **No `jay_trading` import** (deferred to S1.1); `ruff` + `pytest` green
- **Out of scope:** real provider calls, caching, rate-limit/backoff, cost budgeting (all S1.1+).
- **Landed:** 2026-07-08 · in-session · 4 protocols + 5 DTOs + stub, 8 provider tests green (incl. no-`jay_trading`-import guard).
- **Notes:** Protocols are `@runtime_checkable` so tests can `isinstance`-check implementations.
  `stamp` takes `now` as a required keyword (injected time, repo convention); boundary is strict
  `>` — exactly `max_age` old is still fresh. Fixture anchor `FIXTURE_AS_OF = 2026-07-01T14:30Z`.

---

## `[x]` S0.4 — Design-system primitives + Suggestion Card spec
- **Depends on:** S0.1
- **Goal:** the small primitive set that encodes the beginner UX principles (progressive disclosure,
  confidence display, provenance, definitions), plus the flagship **SuggestionCard**.
- **Deliverable:**
  - `alphadash/frontend/src/ui/{Card,Chip,ConfidenceBadge,SourceChip,RiskMeter,DisclosurePanel,DefinitionTooltip,ActionButton}.tsx`
  - `alphadash/frontend/src/features/suggestions/SuggestionCard.tsx`
  - `alphadash/frontend/src/features/suggestions/types.ts` (the **Suggestion view-model** below)
  - `alphadash/frontend/src/dev/Gallery.tsx` (renders every primitive + card states)
  - vitest tests + a11y checks

### FROZEN CONTRACT — S0.4

**Primitive prop interfaces (TypeScript — freeze these names/shapes):**
```
Card:            { children; padded?: boolean; as?: keyof JSX.IntrinsicElements }
Chip:            { label: string; tone?: 'neutral'|'info'|'positive'|'caution'; icon?: ReactNode }
ConfidenceBadge: { value: number /*0..1*/; basis?: string }   // renders band Low/Med/High + numeric + icon (never color-only)
SourceChip:      { source: string; asOf: string /*ISO*/; href?: string; onClick?: () => void }
RiskMeter:       { level: 'low'|'moderate'|'elevated'|'high'; label: string }  // text+icon, never color-only
DisclosurePanel: { summary: string; defaultOpen?: boolean; children }          // the progressive-disclosure primitive
DefinitionTooltip:{ term: string; definition: string; children }              // tappable inline definition
ActionButton:    { label: string; intent: 'primary'|'secondary'|'subtle'|'danger'; onClick: () => void; disabled?: boolean; confirm?: boolean }
```

**Suggestion view-model — this is the frozen presentation contract the backend (S2.4) MUST produce:**
```
EvidenceItem:  { claim: string; source: string; asOf: string; ref?: string }
ProposedOrder: { symbol: string; side: 'buy'|'sell'; qty: string; orderType: 'market'|'limit';
                 limitPrice?: string; cashImpact: string; allocationAfterPct: number }
Suggestion:    { id: string;
                 headline: string;            // L1
                 rationale: string;           // L1, <= 3 sentences
                 confidence: number;          // 0..1
                 confidenceBasis: string;
                 evidence: EvidenceItem[];     // L2
                 proposedOrder: ProposedOrder; // L2
                 worstCase: string;            // L2
                 falsifier: string;            // "what would change our mind"
                 reversibility: string;
                 status: 'proposed'|'approved'|'modified'|'dismissed'|'expired'|'blocked';
                 blockedReason?: string }      // present iff status === 'blocked' (risk-layer veto)
```
_All monetary/quantity fields are strings (Decimal over the wire — never JS number)._

**SuggestionCard behavior (freeze):**
- **L1 always visible:** headline, rationale, `ConfidenceBadge`.
- **L2 in a `DisclosurePanel`:** evidence as `SourceChip`s + claims, the `ProposedOrder` (with cash
  impact + allocation-after), `worstCase`, and `falsifier`.
- **Actions:** `Approve` (primary), `Modify` (secondary), `Dismiss` (subtle), `Ask` (subtle). Emitted
  as callbacks — **no backend calls in S0.4.**
- **Blocked state:** when `status==='blocked'`, show `blockedReason` as a teaching note and **disable
  Approve** (a veto is educational, not an error).
- **L3 (full trace)** is a separate `ExplanationTrace` component in S2.6 — leave a labelled hook only.

- **Acceptance:**
  - [x] Every primitive implemented with the exact prop interface above
  - [x] `SuggestionCard` renders L1 always, L2 via `DisclosurePanel`, all four action callbacks fire
  - [x] Blocked state disables Approve and shows `blockedReason`
  - [x] **Accessibility:** no color-only signals (text+icon on ConfidenceBadge/RiskMeter/Chip), ARIA
        roles/labels, keyboard-focusable actions; a11y check (vitest-axe or equivalent) passes
  - [x] `Gallery.tsx` renders all primitives + SuggestionCard in `proposed` and `blocked` states
  - [x] vitest: ConfidenceBadge band thresholds, disclosure open/close, blocked disables Approve
  - [x] `npm run lint` + `npm run build` + `npm run test` green
- **Out of scope:** data fetching / mutations, ExplanationTrace (S2.6), full theming beyond tokens,
  routing/app-shell (S1.10).
- **Landed:** 2026-07-08 · in-session · 8 primitives + SuggestionCard + Gallery, 13 new tests (14 total) green.
- **Notes:** Changing the `Suggestion` type here ripples to backend S2.4 — treat it as a shared contract.
  Frozen in-session: ConfidenceBadge bands `<0.4 Low, <0.7 Medium, else High` (`confidenceBand()` exported,
  test-pinned). Approve uses `ActionButton confirm` (two-tap arm/confirm — consequence-scaled). L3 hook is
  `data-slot="explanation-trace"` in the card. Axe runs on the whole Gallery with `color-contrast` disabled
  (jsdom has no renderer); re-check contrast in a real browser pass (S3.7). Deps added: `vitest-axe`,
  `@testing-library/user-event`. Fixtures at `features/suggestions/fixtures.ts` shared by Gallery + tests.

---

# Phase 1 — Safety & data spine (build first, no AI)

> Contracts for S1.x are **freeze before start** — lock the interface with the operator when the
> session comes up (most derive directly from S0.2 schema + S0.3 providers).

## `[x]` S1.1 — Real provider implementations (wire in `jay_trading`)
- **Depends on:** S0.3
- **Deliverable:** implement S0.3 protocols against `jay_trading` (`data/alpaca_client`, `fmp`, `fred`,
  `edgar`); add `[tool.uv.sources] jay-trading = { path = "../.." }` + dependency; caching + backoff.
- **Acceptance:** [x] live quote/bar/news/fundamental normalized to S0.3 DTOs · [x] freshness stamped
  · [x] integration tests marked `integration` · [x] unit tests use stub, green.
- **Landed:** 2026-07-08 · in-session · `providers/{real,cache,factory}.py`; live FMP+FRED integration verified.
- **Notes:** Market data + fundamentals via engine `FMPClient` (duck-typed, engine untouched); macro via
  `FREDClient`; news via own httpx adapter (engine has no news endpoint) with tenacity backoff + TTL cache.
  Providers select via `ALPHADASH_PROVIDERS=stub|real`. FMP key: `ALPHADASH_FMP_API_KEY`, dev fallback reads
  root `.env` (engine Settings is cwd-bound + demands Alpaca keys — unusable from alphadash process).
  Bars are FMP EOD `1D` only; intraday timeframes raise `ProviderError` (Alpaca bars can arrive later).
  Integration tests gated by `ALPHADASH_RUN_INTEGRATION=1`.

## `[x]` S1.2 — Fundamentals + news ingestion + normalization
- **Depends on:** S1.1, S0.2
- **Acceptance:** [x] cited, timestamped data persisted to `data_snapshots` shape · [x] tests.
- **Landed:** 2026-07-09 · in-session · `services/ingestion.py::snapshot_market_context`, live-verified.
- **Notes:** One `data_snapshots` row per call: quotes/news/fundamentals/macro with provenance,
  Decimals as strings. Failing feed degrades (recorded in `payload.errors`), never kills snapshot.

## `[x]` S1.3 — Risk & guardrail service (deterministic, hard veto)
- **Depends on:** S0.2
- **Deliverable:** pure `validate_order(order, account_state, limits) -> Decision(allow|reject+reason)`.
- **Acceptance:** [x] every `risk_limits.limit_type` enforced · [x] breach → reason, allow paths · [x]
  property/unit tests cover boundaries · [x] **no LLM, no network**.
- **Landed:** 2026-07-09 · in-session · `domain/risk.py`, 16 tests (incl. hypothesis properties).
- **Notes:** Frozen semantics: buy-side caps use ≤ (boundary allowed); drawdown pause + paused flag
  block buys only (sells/de-risking never trapped); trades/week counts both sides; structural
  invariants always on (qty>0, price>0, no shorting, no buying past cash). Decision returns ALL
  violations (educational veto). `RiskLimitSet.max_asset_class_pct` is per-class map from the
  risk_profiles JSON.

## `[x]` S1.4 — Sizing engine (deterministic)
- **Depends on:** S0.2
- **Acceptance:** [x] given profile + price + account, returns exact size · [x] never exceeds
  per-suggestion/position caps · [x] property tests · [x] LLM-free.
- **Landed:** 2026-07-09 · in-session · `domain/sizing.py`, 9 tests.
- **Notes:** `size_buy` takes min over cap-derived notional ceilings, floors qty at 8dp, names the
  `binding_constraint` (teaching). Central property (300 hypothesis examples): a sized buy ALWAYS
  passes `validate_order` with the same state+limits. `size_sell` caps at held qty.

## `[ ]` S1.5 — Paper execution engine (fills, idempotency)
- **Depends on:** S1.3, S1.4
- **Acceptance:** [x] order → validated → simulated fill w/ modeled slippage · [x] idempotency_key
  dedupes · [x] rejects on risk veto · [x] tests.
- **Landed:** 2026-07-09 · in-session · `services/execution.py::place_order`, 8 tests.
- **Notes:** Frozen: 5 bps adverse slippage on market orders; limit orders marketable-or-reject
  (fill clamped to limit, never violates it; no resting book in Phase 1). Fees 0 in paper. Veto →
  `rejected` + `risk_events(veto)` + journal. Idempotent replay returns original outcome untouched.
  `build_account_state` assembles the risk view from DB + injected prices (trades/week from fills).

## `[ ]` S1.6 — Reconciliation + append-only journal
- **Depends on:** S1.5
- **Acceptance:** [x] every lifecycle event journaled · [x] discrepancy raises `risk_events` · [x]
  journal is append-only (no update/delete path) · [x] tests.
- **Landed:** 2026-07-09 · in-session · `services/{journal,reconciliation}.py`, 6 tests.
- **Notes:** Append-only enforced at ORM level: `before_flush` guard raises `JournalTamperError` on
  any UPDATE/DELETE of journal rows. Reconciliation replays fills from `starting_equity` and compares
  to stored positions/cash; position/cash/phantom-position tampering all detected → risk_event + journal.
  Never silently repairs.

## `[ ]` S1.7 — Portfolio & accounting (perf vs benchmark, drawdown)
- **Depends on:** S1.5
- **Acceptance:** [x] holdings/cash/allocation correct vs hand-computed fixtures · [x] performance
  reported **with benchmark + drawdown** · [x] tests.
- **Landed:** 2026-07-09 · in-session · `services/portfolio.py`, 5 tests vs hand-computed fixtures.
- **Notes:** Benchmark frozen: SPY (starting equity hypothetically invested at first close).
  Equity curve replayed daily from fills, priced by EOD closes with ≤7-day carry-forward
  (weekends/holidays); missing-bar days emit carried values, never interpolated lies. Reports
  return %, benchmark return %, max + current drawdown %.

## `[x]` S1.8 — Auth, accounts, tenant isolation (RLS)
- **Depends on:** S0.2
- **Acceptance:** [x] auth + session · [x] cross-tenant read blocked by test · [x] paper account
  provisioning.
- **Landed:** 2026-07-09 · in-session · argon2id + DB sessions + Postgres RLS; 7 sqlite tests + 3 live-Postgres RLS tests.
- **Notes:** Operator-frozen: email+password (argon2id), server-side sessions (SHA-256 of token in
  new `auth_sessions` table; migration 0002 also adds `users.password_hash` — schema extension beyond
  the S0.2 sixteen). Postgres via `alphadash/docker-compose.yml` (:5433). Migration 0003 = physical
  RLS: ENABLE+FORCE + `tenant_isolation` policy on all 15 tenant tables keyed on
  `current_setting('app.user_id', true)`; child tables (fills/decisions/watchlist_items/data_snapshots)
  inherit via RLS-in-subquery. **App must connect as non-superuser `alphadash_app`** (RLS never binds
  superusers — bit us; role created by `docker/initdb/01-app-role.sql`); migrations run as owner.
  `set_config(..., is_local=true)` per transaction (pool-safe). users/auth_sessions stay outside RLS
  (auth bootstrap). Registration pins tenant context before provisioning (WITH CHECK). Live-verified:
  cross-tenant read empty, no-context zero rows, forged cross-tenant INSERT rejected.

## `[x]` S1.9 — BFF + typed API contract (OpenAPI)
- **Depends on:** S1.7, S1.8
- **Acceptance:** [x] endpoints return shaped responses · [x] client types generated from OpenAPI ·
  [x] contract test.
- **Landed:** 2026-07-09 · in-session · `api/{schemas,portfolio,orders,deps}.py`, 8 BFF tests.
- **Notes:** Endpoints: /auth/*, /account (+/limits,/pause,/resume), /portfolio, /portfolio/performance,
  /orders (POST needs `Idempotency-Key` header), /quotes/{symbol}. Money = string on the wire
  (contract-tested against openapi.json). Types: `npm run gen:api` → `frontend/src/lib/api-types.ts`
  via openapi-typescript; spec exporter `python -m alphadash.openapi_export`. Kill switch modeled as
  `risk_events(auto_pause)` with detail.action pause/resume (schema has no paused column — audit
  trail is better anyway). Every tenant endpoint goes through `get_tenant_db` (RLS context).
  Cosmetic: Numeric(24,8) limits render trailing zeros in veto copy — normalize in S3.7 pass.

## `[x]` S1.10 — Frontend app shell (nav, routing, safety indicator)
- **Depends on:** S0.4
- **Acceptance:** [x] bottom nav Home/Agent/Portfolio/Learn · [x] global paper badge + reachable kill
  switch · [x] Query + WS adapter wired.
- **Landed:** 2026-07-09 · in-session · `app/Shell.tsx`, `App.tsx` auth gate + routes, AuthScreen; 3 shell tests.
- **Notes:** react-router v7. Auth gate on /auth/me (401 → sign-in/register screen). Kill switch =
  two-tap confirm in the sticky header, calls /account/pause|resume, shows Paused chip. WS adapter
  (`lib/ws.ts`) has reconnect/backoff + subscribe surface but stays dormant until S2.7 ships a socket.

## `[x]` S1.11 — Portfolio screen
- **Depends on:** S1.9, S1.10
- **Acceptance:** [x] renders holdings/allocation/perf from BFF · [x] benchmark + drawdown shown.
- **Landed:** 2026-07-09 · in-session · `features/portfolio/PortfolioScreen.tsx`; screen test.
- **Notes:** Stat tiles: equity, cash, 90d return **with SPY same-period sub-line**, max + current
  drawdown. Holdings table with unrealized P/L, allocation incl. cash bucket, teaching empty state,
  paper/not-advice microcopy. Chart deferred (numbers first; dataviz pass can come with S3.x).

## `[x]` S1.12 — Manual paper order ticket + approve→execute
- **Depends on:** S1.9, S1.11
- **Acceptance:** [x] places a limit-checked paper trade end-to-end · [x] confirmation scales with
  consequence. **← Phase 1 exit gate.**
- **Landed:** 2026-07-09 · in-session · `features/orders/OrderTicket.tsx`; 2 ticket tests + live e2e.
- **Notes:** Quote preview with provenance SourceChip + est. cost; two-tap confirm; client-minted
  UUID Idempotency-Key (new key per intent, replay-safe); fill panel notes modeled slippage; veto
  renders as "your safety rules stepped in" with every violation listed. **Exit gate verified live**
  against Postgres+RLS (uvicorn, curl): register → limit buy filled at 210.61 (clamped < 211 limit)
  → veto with reasons → portfolio math exact → performance w/ SPY → unauthenticated blocked.

---

# Phase 2 — The agent

> Load the `claude-api` skill for current model IDs/params before any LLM-touching session.

## `[ ]` S2.1 — Signal/candidate engine (deterministic idea generation)
- **Depends on:** S1.7
- **Acceptance:** [ ] emits candidate actions + numeric features · [ ] tests · [ ] LLM-free.
- **Landed:** —

## `[ ]` S2.2 — RAG context assembly + vector store
- **Depends on:** S1.2
- **Acceptance:** [ ] retrieves cited, fresh evidence with provenance · [ ] ingested text treated as
  untrusted (injection-sandboxed).
- **Landed:** —

## `[ ]` S2.3 — AI orchestration pipeline + schema validation
- **Depends on:** S2.1, S2.2
- **Acceptance:** [ ] malformed LLM output rejected/retried · [ ] **risk layer (S1.3) validates AFTER
  the LLM** · [ ] cadence/quantity caps enforced (0–3 suggestions).
- **Landed:** —

## `[ ]` S2.4 — Explanation assembly → Suggestion object
- **Depends on:** S2.3, S1.3
- **Acceptance:** [ ] produces the **S0.4 `Suggestion` contract** exactly · [ ] explanation generated
  from deterministic candidate features (faithfulness) · [ ] blocked suggestions carry `blockedReason`.
- **Landed:** —

## `[ ]` S2.5 — Suggestion Card wired to live data
- **Depends on:** S0.4, S2.4, S1.9
- **Acceptance:** [ ] renders real suggestions · [ ] Approve→execute via S1.5 · [ ] Modify/Dismiss
  persist `decisions`.
- **Landed:** —

## `[ ]` S2.6 — Explanation trace (L3 "show your work")
- **Depends on:** S2.5
- **Acceptance:** [ ] shows candidate logic → source data → prompt/model version.
- **Landed:** —

## `[ ]` S2.7 — Conversational Q&A endpoint + streaming
- **Depends on:** S2.2, S2.3
- **Acceptance:** [ ] grounded, cited answers · [ ] reframes "should I buy X?" as education + bounded
  option, never a bare directive · [ ] SSE/WS streaming.
- **Landed:** —

## `[ ]` S2.8 — Chat UI + streaming
- **Depends on:** S2.7, S1.10
- **Acceptance:** [ ] tokens stream · [ ] sources shown.
- **Landed:** —

## `[ ]` S2.9 — Eval harness + red-team + calibration (land early, alongside S2.3)
- **Depends on:** S2.3
- **Acceptance:** [ ] safety evals in CI (no profit-promising, veto surfacing, citations, jargon
  avoidance) · [ ] prompt-injection red-team · [ ] confidence-calibration tracking.
- **Landed:** —

---

# Phase 3 — Beginner experience

## `[ ]` S3.1 — Guided onboarding + risk/goals interview
- **Depends on:** S1.8, S1.3 — **Acceptance:** [ ] new user → starter profile + funded paper account,
  reaches first explained read <5 min. · **Landed:** —

## `[ ]` S3.2 — Daily/weekly digest + notifications
- **Depends on:** S2.4 — **Acceptance:** [ ] scheduled digest (today's read + what changed + 0–3
  suggestions) · [ ] push/email. · **Landed:** —

## `[ ]` S3.3 — Contextual education (definitions + explainers)
- **Depends on:** S0.4 — **Acceptance:** [ ] first-use glossary terms tappable via `DefinitionTooltip`.
  · **Landed:** —

## `[ ]` S3.4 — Decision journal + behavioral feedback
- **Depends on:** S1.6 — **Acceptance:** [ ] decisions/outcomes shown · [ ] overtrading/loss-chasing
  nudge fires. · **Landed:** —

## `[ ]` S3.5 — Honest performance review
- **Depends on:** S1.7 — **Acceptance:** [ ] benchmark + drawdown framing · [ ] no naked returns · [ ]
  disclaimers present. · **Landed:** —

## `[ ]` S3.6 — Settings + kill switch + pause-all
- **Depends on:** S1.3 — **Acceptance:** [ ] one-tap pause halts automation (verified) · [ ] limits
  editable + persistently displayed. · **Landed:** —

## `[ ]` S3.7 — Accessibility + empty/loading states + microcopy pass
- **Depends on:** all Phase 3 FE — **Acceptance:** [ ] axe passes app-wide · [ ] states teach, not
  spin · [ ] "simulated/paper/not advice" copy where it matters. · **Landed:** —

---

# Phase 4 — Trust-earning extensions (not scoped — freeze when reached)
- `[ ]` S4.1 Bounded auto-mode (only after risk layer battle-tested in beta)
- `[ ]` S4.2 User-authored simple strategies (NL → deterministic rules) + backtesting (walk-forward)
- `[ ]` S4.3 Scenario / what-if simulator
- `[ ]` S4.4 Richer sentiment/social ingestion + manipulation defenses
- `[ ]` S4.5 Goal-based planning · `[ ]` S4.6 Voice · `[ ]` S4.7 Tax-lot awareness

# Phase 5 — Real-money mode (MAJOR, gated — do not start without counsel)
- `[ ]` S5.1 KYC/AML + suitability · `[ ]` S5.2 Funding + broker/exchange adapters (same execution
  interface, new adapter) · `[ ]` S5.3 Elevated compliance/disclosures + lowered defaults + cooling-off
  · `[ ]` S5.4 Jurisdiction rollout. **Reuses the Phase 1 safety spine — no re-architecture.**

---

## Appendix — conventions (apply to every session)
- Python: `uv`, `ruff` (line-length 100), `pytest` (`integration` marker skipped in CI), pydantic v2,
  SQLAlchemy 2.0 typed, `Decimal` for money — never `float`.
- Frontend: React + Vite + TS, Zustand (UI state only), TanStack Query (all server state; never mirror
  server data into Zustand). Decimal values cross the wire as strings.
- No `Date.now()`/`Math.random()` inside pure logic that must be testable — inject time.
- Every money-touching path: deterministic, idempotent, journaled. The AI proposes; the risk layer
  vetoes; the human disposes. `trading_mode` stays `paper` until Phase 5.
