# Beginner Strategy-Agent Product — Product & Architecture Blueprint

Status: draft blueprint for product + engineering · 2026-07-08
Working name: **Compass** (placeholder)
Audience: product stakeholders and engineering teams
Scope: stocks + crypto · paper-trading first · designed to graduate to real money responsibly

Companion to [alphadesk_saas_spec.md](alphadesk_saas_spec.md) (the tinkerer/operator-facing spec).
This document is the **beginner-facing** consumer product. It inherits the same non-negotiable DNA:
the AI **explains and proposes; it never silently decides**, risk limits are enforced by the
execution layer rather than by model good manners, and we **never imply guaranteed profit**.

---

## 0. How to read this document

- **Part A — Product** (sections 1–7): vision, users, value, journeys, UX principles, features, the agent concept.
- **Part B — Architecture** (sections 8–15): data, backend, frontend, state, AI orchestration, risk, observability, security/compliance.
- **Part C — Execution** (sections 16–17): phased roadmap, what to build first and why, open questions and risks.
- **Appendices**: MVP checklist, feature matrix, glossary.

A one-paragraph product summary is in §1.1; the "what it is / is not" contract is in §1.3; the
must-have MVP list is in §6.1 and Appendix A.

---

# PART A — PRODUCT

## 1. Product vision and positioning

### 1.1 Product summary

Compass is a beginner-first investing companion for stocks and crypto. Instead of dropping a novice
into a wall of charts and order tickets, it pairs them with an **automated natural-language strategy
agent** that continuously reads the market from many sources — live prices, news, fundamentals,
macro context, sentiment, and social signals — and turns that firehose into a small number of
**clear, explained, optional suggestions**. Everything runs on **paper money first**, so users learn
by doing without financial consequence. Every suggestion shows its reasoning, its confidence, the
risk it carries, and what would change its mind. The product's job is not to make users rich; it is
to make them **competent and calm**, and to be trustworthy enough that when real-money trading is
introduced later, the safety rails are already proven.

### 1.2 Positioning statement

> For beginners who feel locked out of investing because it looks compland risky, Compass is a
> guided, paper-first trading companion whose AI agent explains the market in plain language and
> proposes safe, sized, reversible actions — unlike brokerage apps that assume you already know what
> you're doing, and unlike "signal" services that tell you what to buy without telling you why or
> what could go wrong.

### 1.3 What the product IS and IS NOT

**Compass IS:**
- A **learning-by-doing** environment: real market data, simulated money, honest simulated fills.
- An **explainer**: every insight and suggestion is traceable to the data that produced it.
- A **decision-support** tool: the agent proposes; the human (or an explicit, bounded auto-mode) disposes.
- A **safety-first system**: hard, user-set risk limits enforced in the execution layer.
- A **confidence builder**: it teaches concepts in context, exactly when they're relevant.

**Compass IS NOT:**
- A profit promise, a "get rich" product, or a source of financial advice. It gives **education and
  decision support**, not personalized investment recommendations in the regulated sense (see §15).
- A day-trading / high-frequency terminal. Cadence is deliberate and slow by default.
- An autonomous money manager. Even in auto-mode, actions are bounded, logged, explained, reversible
  (in paper) and pausable.
- A place where the AI's word is final. The AI cannot breach a risk limit; the deterministic risk
  layer can veto the AI.
- A copy-trading or social-following product at MVP (a possible, carefully-gated future feature).

### 1.4 Guiding principles (the product's DNA)

1. **Explainability over cleverness.** A worse suggestion that the user understands beats a better one they don't.
2. **Safety is structural, not advisory.** Limits are enforced by code paths the AI cannot go around.
3. **Honesty about uncertainty.** Confidence, drawdown, and "what could go wrong" ship next to every number.
4. **Progressive disclosure.** Show the least that's useful; let the curious dig deeper.
5. **Paper parity.** The paper experience is a faithful rehearsal for real money, minus the money.
6. **No dark patterns.** No streaks-to-trade, no loss-chasing nudges, no gamified overtrading.

---

## 2. Target users and personas

### 2.1 Audience definition

Adults (18+) who are curious about investing but under-served by existing tools: they have some
savings, low-to-zero market experience, and are deterred by jargon, fear of loss, and the feeling
that "everyone else already knows the rules." They are mobile-first, time-poor, and skeptical of hype.

### 2.2 Personas

**Persona 1 — "Cautious Casey" (primary)**
- 29, salaried, has an emergency fund and a vague plan to "invest eventually."
- Owns crypto she bought impulsively once and doesn't understand.
- Fears losing money and looking dumb; distrusts finance influencers.
- **Needs:** a safe place to learn, plain-language explanations, small confident steps.
- **Success:** after 4 weeks she can explain why she holds what she holds, and feels in control.

**Persona 2 — "Busy Ben" (primary)**
- 41, professional, wants to be a competent long-term investor but has ~20 min/week.
- Wants the system to do the watching and only surface what matters.
- **Needs:** high-signal, low-frequency nudges; a trustworthy auto-mode with guardrails.
- **Success:** a weekly digest he trusts; rare, well-explained actions he can approve in one tap.

**Persona 3 — "Learning Lena" (secondary)**
- 22, student, high curiosity, low capital, high time.
- Wants to understand mechanics and eventually try her own ideas.
- **Needs:** depth on demand, backtesting she can trust, a path from guided to self-directed.
- **Success:** graduates to building/adjusting her own simple strategies with the agent's help.

**Persona 4 — "Returning Riley" (tertiary)**
- 35, tried a brokerage app, lost money on a meme stock, quit, wants to restart responsibly.
- **Needs:** rebuilt trust, loss-context education, disciplined defaults.
- **Success:** re-engages without repeating the impulsive behavior that burned them.

### 2.3 Anti-persona
Active day traders, options/leverage seekers, and users hunting alpha signals to front-run. The
product should feel *slightly boring* to them by design — that's a feature.

### 2.4 What each persona needs from the AI agent
- Casey: reassurance + plain words + "is this normal?" answers.
- Ben: filtering + summarization + bounded automation.
- Lena: mechanism explanations + backtest rigor + a ramp to authorship.
- Riley: behavioral guardrails + honest post-mortems.

---

## 3. Core value proposition

**Primary value:** *Understand the market and act on it safely, without needing to become an expert first.*

Three pillars:

1. **Clarity** — The agent compresses a chaotic, multi-source market into a few understandable,
   explained observations and options. It reduces overwhelm.
2. **Safety** — Paper-first, hard risk limits, reversible actions, and a system that can veto itself.
   It reduces fear and real downside.
3. **Growth** — Contextual education and honest feedback turn every action into a lesson. Users get
   more capable over time, not more dependent.

**Why each matters commercially:** beginners churn from finance apps because of overwhelm and fear.
Clarity attacks overwhelm; safety attacks fear; growth creates the retention loop and the eventual,
trust-earned upgrade to real money (the monetization moment).

**What we explicitly do not sell:** returns, edge, or "signals." Our credibility *is* the product.

---

## 4. Key user journeys

Each journey lists trigger → steps → agent's role → success metric.

### 4.1 First-run onboarding (target: <5 minutes to first "aha")
Trigger: new signup.
1. Warm welcome; one-sentence honest promise ("We help you learn to invest with fake money and real data. We never promise profit.").
2. **Risk & goals interview** (3–5 plain questions): time horizon, loss comfort, topics of interest (tech? crypto? dividends?), how hands-on they want to be.
3. System proposes a **starter risk profile** (Conservative / Balanced / Curious) with defaults pre-filled and editable.
4. Funded paper account auto-created (e.g., $10,000 simulated).
5. Agent produces a **first read of the market** in plain language + one small optional suggestion, fully explained.
6. Guided tour of the three core surfaces (Home, Agent, Portfolio).
Agent's role: interviewer, explainer, first-suggestion author.
Success: user reaches their first explained suggestion and understands it (measured via a one-tap "did this make sense?").

### 4.2 Daily / weekly check-in (the core retention loop)
Trigger: push/email digest or app open.
1. **Today's read**: 2–4 sentence market summary tailored to their holdings + interests.
2. **What changed** since last visit (holdings, watchlist, notable news) — each item one line, tap to expand.
3. **Suggestions** (0–3): each with rationale, confidence, risk, and Approve / Modify / Dismiss / Explain more.
4. Optional **learn** card relevant to what's happening.
Agent's role: summarizer, prioritizer, proposer.
Success: user reviews digest and takes an intentional action (including "dismiss," which is a valid, logged outcome).

### 4.3 Reviewing and acting on a suggestion
Trigger: a suggestion appears.
1. Headline in plain language ("Consider trimming NVDA back toward your target — it's grown to 22% of your paper portfolio").
2. **Why** (bulleted evidence with source chips).
3. **Risk & sizing**: exact proposed order, cash impact, how it moves diversification, worst-case framing.
4. **What would change our mind** (the falsifier).
5. Action: Approve (executes in paper), Modify (adjust size), Dismiss (with optional reason), Ask (chat follow-up).
Agent's role: proposer + Socratic explainer.
Success: action taken with understanding; the decision + its context is logged to the journal.

### 4.4 Asking the agent a question (conversational)
Trigger: user types/speaks a question ("Why did my portfolio drop today?", "Is now a good time to buy bitcoin?").
1. Agent answers in plain language, grounded in *their* data and current market context.
2. For "should I buy X?" questions it reframes into education + a bounded, explained option — never a bare yes/no directive.
3. Cites sources; offers to turn the answer into a tracked suggestion.
Agent's role: grounded Q&A with guardrails against advice-giving overreach.
Success: question answered, sourced, and safely framed.

### 4.5 Setting up (light) automation
Trigger: user opts into auto-mode after building trust.
1. Explain auto-mode honestly: what it can and cannot do, the hard caps, how to pause.
2. User sets bounds (max position size, max trades/week, allowed universe, drawdown pause threshold).
3. Agent runs inside those bounds; every automated action is logged, explained, and notified.
4. **Kill switch** always one tap away; auto-pauses on breach or unusual conditions.
Agent's role: bounded executor within a provable envelope.
Success: automation runs without a single limit breach; user feels in control (verified by low kill-switch panic use).

### 4.6 Learning moment
Trigger: a concept appears in context (first time user sees "drawdown", "diversification", "limit order").
1. Inline definition chip; tap for a 30-second explainer with a concrete example from *their* portfolio.
2. Optional short lesson track.
Success: concept comprehension (light quiz / self-report), reduced repeat questions.

### 4.7 Reviewing performance honestly
Trigger: weekly/monthly review.
1. Paper performance shown **with a benchmark** (e.g., buy-and-hold SPY / BTC) and **drawdown next to return**.
2. Agent narrates what worked, what didn't, and what was luck vs. process.
3. Behavioral feedback (e.g., "you dismissed 4 trim suggestions and your tech weight is now high").
Success: user can distinguish process quality from outcome — the anti-gambling lesson.

### 4.8 (Future) Graduating to real money
Trigger: eligibility + explicit user intent (see §16 phasing).
1. Extensive disclosures, suitability check, KYC, funding.
2. **Lowered defaults**, mandatory cooling-off, real-money-specific confirmations.
3. Same explainability and risk layer, now with real consequences surfaced even more prominently.
Success: safe, informed, compliant transition — deliberately high-friction.

---

## 5. UX design principles for beginners

1. **One primary action per screen.** Never present five equally-weighted choices.
2. **Progressive disclosure.** Layer 1: the plain-language answer. Layer 2: the evidence. Layer 3: the raw data/chart. Most users never leave Layer 1.
3. **Plain language, no unexplained jargon.** First use of any term is a tappable definition. Maintain a controlled vocabulary; the agent is prompted to avoid unexplained finance jargon.
4. **Show confidence and uncertainty, always.** Every suggestion carries a confidence band and a "what could go wrong." Never a naked number.
5. **Make risk visible and pre-committed.** Risk limits are set once, shown persistently, and framed as protection the user chose.
6. **Reversibility and safety in the flow.** In paper, everything is undoable; confirmations scale with consequence. Destructive/consequential actions get friction, routine ones don't.
7. **Calm, not addictive.** No red-green dopamine loops, no "trade now" urgency, no streak pressure. Default cadence is daily/weekly, not per-tick. Numbers update, but the UI doesn't scream.
8. **Consistent surfaces.** A small, stable information hierarchy (Home / Agent / Portfolio / Learn / Settings) users can build a mental model of.
9. **Empty and loading states teach.** Instead of spinners and blanks, show what's coming and why.
10. **Accessibility first.** Color is never the only signal (colorblind-safe); large tap targets; screen-reader labels; readable defaults. Financial anxiety + poor accessibility compounds.
11. **Mobile-first, responsive.** Primary interaction is a phone in one hand.
12. **Honest microcopy.** "Simulated," "paper," "not advice," and benchmark context appear where they matter, not buried in a footer.

---

## 6. Core features and capabilities

### 6.1 MVP must-have features
(Full checklist in Appendix A.)

1. **Guided onboarding + risk/goals interview** → starter risk profile and funded paper account.
2. **Natural-language strategy agent** producing a plain-language market read + explained suggestions.
3. **Explained suggestions** with evidence chips, confidence, sizing, risk, and a falsifier.
4. **Conversational Q&A** grounded in the user's portfolio and live market context.
5. **Paper trading engine** with honest simulated fills for stocks + crypto (manual approve-to-execute).
6. **Deterministic risk & guardrail layer** enforcing user-set limits; can veto the agent.
7. **Portfolio view** with holdings, cash, allocation, performance-vs-benchmark, and drawdown.
8. **Decision journal** logging every suggestion, action, dismissal, and the context behind it.
9. **Watchlist + universe** of a curated, beginner-safe set of stocks and major crypto.
10. **Contextual education** (inline definitions + short explainers).
11. **Daily/weekly digest** (in-app + push/email).
12. **Explainability trace** ("why did the agent say this?") for every insight.
13. **Account + safety settings** (risk profile, notifications, pause everything).
14. **Honest performance reporting** (benchmark + drawdown, no cherry-picking).

### 6.2 Strong future features (post-MVP)

- **Bounded auto-mode** (agent executes within a provable envelope; §4.5, §13).
- **User-authored simple strategies** (natural-language → deterministic rule set) with **backtesting** (walk-forward, drawdown-forward).
- **Scenario / "what if" simulator** ("what if I'd followed every suggestion?", "what if the market drops 10%?").
- **Goal-based planning** (target-driven, not return-promising).
- **Richer sentiment/social ingestion** with source-quality weighting and manipulation detection.
- **Voice interface** for the agent.
- **Community / shared strategies** (heavily gated, no blind copy-trading).
- **Multi-language and localization.**
- **Tax-lot awareness** (essential before real money in many jurisdictions).
- **Real-money mode** with KYC, funding, broker/exchange integration, and elevated compliance (§16 Phase 4).
- **Model/agent transparency dashboard** (which data sources drove decisions over time).

### 6.3 Feature breakdown by UX area

| UX area | MVP features | Why it matters |
|---|---|---|
| **Onboarding** | Risk/goals interview, starter profile, paper funding, first explained read | Fast trust + first "aha"; sets safe defaults early |
| **Home / digest** | Today's read, what changed, 0–3 suggestions, learn card | The retention loop; high-signal, low-frequency |
| **Agent surface** | Chat Q&A, suggestion cards, explanation traces, sources | Core differentiation; where trust is built |
| **Portfolio** | Holdings, cash, allocation, perf-vs-benchmark, drawdown | Honest self-knowledge; anti-gambling framing |
| **Trading / execution** | Approve/modify/dismiss, paper order ticket, confirmations | Safe action-taking; human-in-the-loop |
| **Risk & safety** | Persistent limits display, kill switch, breach explanations | Fear reduction; structural safety |
| **Learn** | Inline definitions, contextual explainers, short tracks | Growth pillar; reduces support + churn |
| **Journal / history** | Decision log, outcomes, behavioral feedback | Reflection; distinguishes luck from process |
| **Settings** | Risk profile, notifications, data/privacy, pause-all | Control and consent |

---

## 7. AI strategy-agent concept and how it operates

### 7.1 Core concept

The agent is a **decision-support system with a natural-language surface**, not an autonomous trader
and not an oracle. It has three jobs, in priority order:
1. **Explain** the market and the user's situation in plain language.
2. **Propose** a small number of safe, sized, reversible options.
3. (Optionally, later) **Execute** within a provable risk envelope it cannot exceed.

Crucial design stance (inherited from the companion spec): **the AI explains and proposes; a
deterministic engine decides what's *allowed*, and the human decides what happens** (except in
explicitly-bounded auto-mode). The AI can be wrong without being dangerous, because it cannot breach
a limit.

### 7.2 The reasoning pipeline (conceptual)

```
Ingest → Normalize → Feature/Signal extraction → Candidate generation (deterministic)
      → LLM reasoning & explanation → Risk-layer validation (deterministic, hard veto)
      → Ranking & selection → Presentation (explained cards) → Human/auto decision → Journal
```

Key point: **candidate trade ideas are generated by transparent, mostly-deterministic logic**
(rules, screens, portfolio-fit checks). The LLM's role is to *reason about, rank, filter, and
explain* candidates in natural language — not to hallucinate order tickets from scratch. This keeps
suggestions auditable, testable, and safe, and confines the LLM to what it's good at (synthesis and
language) while keeping money-touching math deterministic.

### 7.3 What the agent must always attach to a suggestion
- **Plain-language rationale** (≤3 sentences up top).
- **Evidence** with source attribution (news item, fundamental metric, price/technical fact, sentiment reading), each traceable.
- **Confidence** (calibrated band, not false precision) and its basis.
- **Risk framing**: sizing math, cash/allocation impact, and a concrete worst-case.
- **A falsifier**: "what would change our mind."
- **Reversibility note** (paper; and, later, real-money consequence).

### 7.4 Guardrails on the agent's behavior (prompt + system level)
- Never promises profit, income, or "sure things"; never uses hype.
- Never gives regulated personalized advice; frames as education + optional, explained decision support.
- Never invents data; if a source is unavailable, it says so and lowers confidence.
- Refuses/deflects unsafe requests (leverage-maxing, "all-in", chasing losses) and explains why.
- Always defers to the deterministic risk layer; surfaces vetoes as teaching moments.
- Grounded strictly in retrieved, cited data (RAG over the user's portfolio + market feeds); no free-floating market claims.

### 7.5 Operating cadence
- **Scheduled runs** (e.g., pre-open, midday, post-close for stocks; a few times daily for crypto) generate the digest and candidate suggestions.
- **Event-triggered runs** on material news / large moves in held or watchlisted assets.
- **On-demand runs** for user questions.
Cadence is deliberately unhurried for beginners; high-frequency reaction is out of scope.

### 7.6 Trust & calibration mechanisms
- **Confidence calibration** tracked over time (are 60%-confidence calls right ~60% of the time?) and shown honestly.
- **Explanation faithfulness**: the explanation must reflect the actual candidate-generation inputs, not a post-hoc story. Achieved by generating explanations *from* the deterministic feature set that produced the candidate.
- **"Show your work"** always available: full trace from suggestion → candidate logic → source data.

---

# PART B — ARCHITECTURE

Architecture-first and platform-agnostic where it can be; opinionated where a default de-risks delivery.

## 8. Data sources and ingestion strategy

### 8.1 Source categories

| Category | Examples of data | Role in reasoning | MVP? |
|---|---|---|---|
| **Live/near-live market data** | Prices, OHLCV, volume, order book (crypto), quotes | Ground truth for positions, sizing, fills | ✅ |
| **Fundamentals** | Earnings, revenue, margins, valuation ratios, financial statements | Long-term rationale, valuation context | ✅ (equities) |
| **News** | Company/asset news, macro headlines, filings | Event awareness, "what changed" | ✅ |
| **Macro context** | Rates, CPI/inflation prints, employment, key calendar events | Regime framing, risk-on/off context | ✅ (lightweight) |
| **Sentiment** | Aggregated market sentiment, fear/greed style indices | Context, contrarian framing, never sole basis | ◐ (light MVP) |
| **Social signals** | Social/forum volume & tone on specific assets | Attention/mania detection, manipulation flags | ⨯ (post-MVP, heavily filtered) |
| **Corporate/asset events** | Dividends, splits, token unlocks, halvings, listings | Portfolio accuracy, event risk | ◐ |
| **Reference data** | Symbols, sectors, asset metadata, calendars | Normalization backbone | ✅ |

### 8.2 Provider strategy
- **Abstract every source behind an internal interface** (`MarketDataProvider`, `NewsProvider`, `FundamentalsProvider`, …) so providers are swappable and testable. Never let provider-specific shapes leak into business logic.
- Prefer 1–2 reliable providers per category at MVP over breadth. This repo already standardizes on FMP for fundamentals/quotes and Alpaca for paper trading/market data — reuse those primitives (see project memory).
- **Cost and rate-limit awareness** built into the provider layer (budgeting, backoff, caching).
- **Provenance is mandatory:** every datum carries source + timestamp so the explanation layer can cite it and the risk layer can reject stale data.

### 8.3 Ingestion patterns
- **Pull/scheduled** for fundamentals, macro, daily bars (cron-style jobs).
- **Streaming/webhook** for live prices where available; otherwise short-interval polling.
- **Event detection** layer flags material moves/news to trigger agent runs.
- **Normalization pipeline**: raw → canonical schema (symbols, currencies, timestamps to UTC, corporate-action adjustment) → feature store.
- **Freshness/staleness policy**: each feed has a max-age; stale data is flagged and *lowers agent confidence or blocks suggestions* rather than silently feeding decisions.

### 8.4 Data quality & safety
- Deduplication and conflict resolution across providers (e.g., price disagreement → use primary, flag divergence).
- **Sentiment/social manipulation resistance**: source-quality weighting, volume-anomaly detection, and a hard rule that social signals can never be the *sole* basis for a suggestion.
- Backfill + point-in-time correctness for anything feeding backtests (no lookahead bias). Store data as-of, not as-revised.
- Clear separation of **market data** (shared, cacheable) from **user data** (private, per-tenant).

### 8.5 Storage
- **Time-series store** for prices/features (e.g., Timescale/ClickHouse-style); **relational store** (PostgreSQL) for accounts, portfolios, orders, journal; **object store** for raw payloads/audit; **cache** (Redis) for hot quotes and computed features; **vector store** for RAG over news/docs the agent cites.

---

## 9. Backend architecture and service design

### 9.1 Recommended stack (opinionated default, swappable)
- **Language/runtime:** Python for data/AI/quant services (ecosystem + this repo's existing Python stack); a TypeScript/Node edge/BFF layer is acceptable if the team prefers one language toward the client. Recommendation: **Python services + a thin BFF** for the React app.
- **API:** REST + JSON for CRUD; **WebSocket/SSE** for live prices, agent-run progress, and streamed explanations.
- **Datastores:** PostgreSQL (system of record), Redis (cache/queues), a time-series DB (market/features), object storage (audit/raw), vector DB (RAG).
- **Async/orchestration:** a task queue/scheduler (e.g., Celery/RQ/Temporal-style) for ingestion jobs and agent runs.
- **Deployment:** containers; start modular-monolith, extract services only when justified.

### 9.2 Service decomposition (logical, not necessarily separate processes at MVP)

1. **Ingestion & Market Data Service** — providers, normalization, feature store, freshness.
2. **Fundamentals/News/Macro Service(s)** — category-specific ingestion + retrieval.
3. **Signal/Candidate Engine** — deterministic screens, portfolio-fit, candidate generation. *The money-math lives here, testable and versioned.*
4. **AI Orchestration Service** — RAG assembly, LLM calls, reasoning/explanation, ranking (see §12).
5. **Risk & Guardrail Service** — deterministic limit enforcement; the only path that can approve/veto an order for allowability. **Cannot be bypassed by the AI.**
6. **Paper Trading / Execution Engine** — simulated fills, positions, cash, P&L; broker/exchange adapters later.
7. **Portfolio & Accounting Service** — holdings, cash, allocation, performance, drawdown, benchmark.
8. **Journal / Audit Service** — append-only log of suggestions, decisions, executions, vetoes, data snapshots.
9. **Notification/Digest Service** — scheduled digests, push/email, event alerts.
10. **User/Account/Auth Service** — identity, profiles, risk settings, consent.
11. **BFF/API Gateway** — auth, aggregation, rate limiting, shaping responses for the React client.

### 9.3 Key architectural rules
- **Determinism where money moves.** Sizing, limit checks, and fills are pure, tested, versioned functions — never LLM output.
- **The risk layer sits between the agent and execution, always.** Suggestion → risk validation → (human/auto) approval → execution. No shortcut path exists in the code.
- **Everything money-touching is idempotent and logged.** Every order carries a client-side idempotency key; every state change is journaled.
- **Multi-tenant isolation from day one** even in paper (row-level security / tenant scoping) so real-money mode doesn't require a re-architecture (see companion doc [04-multi-tenancy-and-regulatory.md](../architecture/04-multi-tenancy-and-regulatory.md)).
- **Versioned strategy/agent artifacts.** Candidate logic, prompts, and model versions are versioned and attached to every decision for reproducibility.
- **Paper/real parity by interface.** The execution engine exposes the same interface for paper and real; only the adapter differs. This is what makes the eventual graduation safe.

### 9.4 Core data model (essential entities)
- `User`, `RiskProfile`, `Account` (paper|real), `Position`, `CashBalance`, `Order` (+ status, idempotency key), `Fill`, `Suggestion` (+ evidence, confidence, candidate ref, prompt/model version), `Decision` (approve/modify/dismiss + reason), `RiskLimit`, `RiskEvent` (breach/veto), `JournalEntry`, `Watchlist`, `AgentRun`, `DataSnapshot` (point-in-time inputs for a run).

---

## 10. Frontend architecture and UI structure

Frontend stack per the brief: **React + Zustand + TanStack Query** (mobile-first, responsive PWA).

### 10.1 Information hierarchy (top-level surfaces)
```
App
├── Home / Digest          (today's read, what changed, suggestions, learn card)
├── Agent                  (chat Q&A + suggestion cards + explanation traces)
├── Portfolio              (holdings, allocation, performance vs benchmark, drawdown)
│   └── Asset detail       (price, fundamentals, news, agent's view, actions)
├── Learn                  (contextual explainers + short tracks)
├── Journal / History      (decisions, outcomes, behavioral feedback)
└── Settings               (risk profile, notifications, privacy, pause-all, account)
```
Persistent chrome: a small bottom nav (Home / Agent / Portfolio / Learn), a **global safety indicator** (paper badge + kill switch reachable), and a notification bell.

### 10.2 Component architecture
- **Design system first**: a small set of primitives (Card, Chip, DisclosurePanel, ConfidenceBadge, SourceChip, RiskMeter, DefinitionTooltip, ActionButton) that encode the UX principles (progressive disclosure, confidence display, definitions). This enforces consistency and honesty at the component level.
- **Suggestion Card** is the flagship component: headline → evidence chips → confidence → sizing/risk → falsifier → actions, with layered disclosure built in.
- **Explanation Trace** component renders the "show your work" view (suggestion → candidate logic → sources).
- **Feature-based folder structure** (`features/agent`, `features/portfolio`, …) each owning its components, hooks, and query definitions.
- **Accessibility baked into primitives** (never color-only, ARIA labels, focus management, large targets).

### 10.3 UX for streaming and latency
- Agent responses and explanations **stream** (SSE/WS) so the user sees reasoning appear rather than waiting on a spinner.
- Skeletons that *describe what's loading*, optimistic UI only for clearly-reversible paper actions, and explicit "as of HH:MM" timestamps on all market data.

### 10.4 PWA / platform
- Start as a responsive PWA (fast iteration, one codebase); wrap for native later if push/store presence demands it. Push notifications for digests/alerts.

---

## 11. State management, API integration, client-side data flow

### 11.1 Division of responsibility (the key decision)
- **TanStack Query owns all server state** — portfolio, quotes, suggestions, journal, agent runs. It handles caching, background refetch, staleness, retries, and de-dupes requests. This is the bulk of the app's data.
- **Zustand owns ephemeral client/UI state** — current view, open disclosure panels, draft order edits, onboarding step, agent chat composer, kill-switch confirmation modal, feature flags, theme.
- **Rule:** never mirror server data into Zustand. If it comes from the backend, it lives in Query; Zustand references IDs/selection, not copies. This prevents the classic dual-source-of-truth bugs.

### 11.2 Data flow patterns
- **Reads:** components subscribe via typed query hooks (`usePortfolio`, `useSuggestions`, `useAgentRun`). Query keys are structured (`['portfolio', accountId]`, `['suggestions', accountId, {status}]`) for precise invalidation.
- **Live data:** a WebSocket/SSE layer pushes quote/agent updates; a thin adapter writes them into the Query cache (`queryClient.setQueryData`) so components have one consumption model regardless of transport.
- **Writes (mutations):** approving/modifying/dismissing a suggestion and placing paper orders are `useMutation` calls with **optimistic updates only where reversible**, and **server confirmation required** before showing an order as filled. Mutations carry idempotency keys.
- **Staleness/freshness:** market data queries use short `staleTime` + background refetch; account/journal data longer. Every market number renders with its "as of" timestamp from the payload.
- **Error/empty/loading states** are first-class per query, feeding the teaching-oriented states from §5.

### 11.3 API contract
- Typed client (OpenAPI-generated types or tRPC-style) shared with the BFF; the client never hand-rolls response shapes.
- The BFF shapes responses for the beginner UI (e.g., a suggestion arrives pre-assembled with evidence + confidence + sizing) so the client stays thin and consistent.

---

## 12. AI orchestration, reasoning flow, and explanation layers

### 12.1 Orchestration overview
The AI Orchestration Service coordinates a **bounded, auditable pipeline** per agent run:

```
1. Context assembly (RAG)
   - Pull user's portfolio, risk profile, holdings/watchlist
   - Retrieve fresh, cited data: prices, fundamentals, news, macro, sentiment (with provenance & freshness)
2. Deterministic candidate generation (Signal/Candidate Engine)
   - Screens, portfolio-fit checks, rebalancing needs, event flags → candidate actions with numeric features
3. LLM reasoning pass
   - Input: candidates + their features + retrieved evidence + user profile
   - Output: ranked, filtered candidates with plain-language rationale, confidence rationale, falsifier
   - Constrained to reason over provided candidates/evidence only (no invented ideas or data)
4. Risk-layer validation (deterministic, hard)
   - Each surviving candidate re-checked against user limits; violators dropped or downgraded to "blocked, here's why"
5. Ranking & selection
   - Keep top 0–3; enforce cadence/quantity caps to avoid overwhelm
6. Explanation assembly
   - Compose Suggestion objects: rationale + evidence chips (with sources) + confidence + sizing + falsifier + reversibility
7. Persist + present + journal
```

### 12.2 Why this shape
- **Determinism owns the money-math**, LLM owns language/synthesis → auditable, testable, safe.
- **RAG-grounding + "reason only over provided evidence"** minimizes hallucination and makes every claim citable.
- **Risk validation after the LLM** means the model can never talk its way past a limit.
- **Cadence/quantity caps** operationalize the "don't overwhelm beginners" principle at the pipeline level.

### 12.3 Explanation layers (three depths, matching UX progressive disclosure)
- **L1 — Plain answer:** the ≤3-sentence rationale a beginner reads.
- **L2 — Evidence:** the bulleted signals with source chips and confidence basis.
- **L3 — Full trace:** the candidate logic, numeric features, raw cited data, prompt/model version, and the risk checks applied. For power users, support, and audit.

### 12.4 Model strategy
- **Model-agnostic behind an interface.** Default to a strong hosted model for reasoning/explanation (per this environment, latest Claude models — see the `claude-api` skill for current IDs/params before building anything LLM-touching).
- **Prompt/version management:** system prompts, tool definitions, and model IDs are versioned artifacts, attached to every `AgentRun` for reproducibility.
- **Cost control:** cache retrieved context and stable computations; batch scheduled runs; reserve on-demand LLM calls for genuine user questions.
- **Guardrail prompting + output validation:** structured outputs validated against a schema (a suggestion must contain rationale, evidence refs, confidence, sizing, falsifier) — malformed outputs are rejected and retried, never shown.
- **Faithfulness:** explanations are generated *from* the deterministic candidate features, so the story matches the math.

### 12.5 Evaluation harness
- Offline eval set of market scenarios with expected safe behaviors (no profit-promising, correct veto surfacing, citation presence, jargon avoidance).
- **Confidence calibration tracking** in production.
- Red-team suite for unsafe prompts ("go all in", "guarantee me money", prompt injection via news content — since news is fed to the model, treat ingested text as untrusted and sandbox it).

---

## 13. Risk management, safety controls, execution guardrails

This is the product's structural spine, not a feature.

### 13.1 Layered controls
1. **User-set risk profile & limits** (max position size %, max asset-class exposure, max trades/period, cash floor, per-suggestion max, drawdown-pause threshold). Set at onboarding, editable, persistently displayed.
2. **Deterministic Risk & Guardrail Service** validates *every* order (agent-, human-, or auto-originated) against limits **before** execution. Enforced in code, not in prompts. A blocked action becomes an explained teaching moment, not a silent drop.
3. **Sizing engine** computes position sizes deterministically from the risk profile — the LLM never sizes trades.
4. **Cadence & quantity caps** prevent overtrading and overwhelm (max suggestions/day, cooldowns).
5. **Kill switch** — one tap pauses all automation and flags open suggestions; always reachable.
6. **Auto-pause triggers** — drawdown breach, abnormal volatility, stale/conflicting data, provider outage → automation halts and notifies.
7. **Anti-manipulation** — social/sentiment can't be sole basis; volume-anomaly and pump detection downgrade confidence.

### 13.2 Execution guardrails (paper, designed for real-money parity)
- Pre-trade checks (limits, buying power, universe allow-list, market-hours, min/max order size).
- Honest simulated fills (spread/slippage modeled; we state that paper flatters results).
- Post-trade reconciliation against the accounting service; discrepancies raise `RiskEvent`s (this repo already learned this lesson — see MorningCheck reconcile defects in project memory).
- Idempotency + append-only audit for every order lifecycle event.

### 13.3 Behavioral safety (beginner-specific)
- Cooling-off prompts on rapid repeated actions; loss-chasing detection with a gentle intervention.
- No dark patterns, streaks-to-trade, or urgency nudges.
- Honest performance framing (benchmark + drawdown) to prevent outcome-over-process thinking.

### 13.4 Real-money readiness (built now, activated later)
- Same risk interfaces for paper and real; real-money mode ships with **lower default limits, mandatory cooling-off, elevated confirmations, and suitability gating**.
- Nothing about graduating to real money should require re-architecting the risk layer — that's the whole point of building it structurally in Phase 1.

---

## 14. Performance, observability, monitoring

### 14.1 Performance targets (indicative)
- Digest/home load: <1s perceived (cached), fresh data streamed in.
- Agent on-demand answer: first token <2–3s, streamed.
- Order (paper) placement→confirmation: <1s.
- Live quote update latency: seconds, clearly timestamped.
Deliberately *not* optimizing for HFT-grade latency — inappropriate for the audience.

### 14.2 Observability
- **Structured logging** with correlation IDs across ingestion → candidate → agent → risk → execution → journal.
- **Metrics:** ingestion freshness/lag per source, agent run duration & cost, suggestion volume, veto rate, mutation success/latency, WS connection health.
- **Tracing** across the agent pipeline (which sources fed which suggestion, how long each stage took).
- **AI-specific monitoring:** hallucination/faithfulness flags, confidence calibration drift, guardrail-refusal rates, schema-validation failures, prompt-injection attempts from ingested content.
- **Data-quality monitors:** stale feeds, price divergence, missing fundamentals — feeding the freshness policy that gates suggestions.

### 14.3 Alerting & SLOs
- Page on: risk-layer bypass attempts, reconciliation discrepancies, execution engine errors, provider outages affecting held assets, auth anomalies.
- SLOs on data freshness, agent availability, and execution correctness (correctness > availability for money-touching paths).

### 14.4 Dashboards
- Ops dashboard (system health, provider status, queues).
- AI dashboard (calibration, cost, refusal/veto rates, source attribution).
- Product dashboard (activation, digest engagement, comprehension signals, churn).

---

## 15. Security, compliance, operational concerns

### 15.1 Security
- Standard auth (MFA-capable), least-privilege service accounts, secrets management (this repo keeps creds in `.env` — migrate to a proper secrets manager before real money).
- **Tenant isolation** enforced at the data layer (RLS/tenant scoping) from day one.
- Encryption in transit and at rest; PII minimization; separate storage for PII vs. market data.
- **Treat ingested external text (news/social) as untrusted** — sandbox it against prompt injection into the agent.
- Audit trail is append-only and tamper-evident.

### 15.2 Compliance (grows with mode)
- **Paper phase:** primarily consumer-protection, honest-marketing, and data-privacy (GDPR/CCPA-style) obligations. The critical rule: **do not stray into giving regulated personalized investment advice** — position the agent as education + decision support, with clear disclaimers, and get real legal review before launch.
- **Real-money phase (future):** KYC/AML, suitability, broker-dealer/RIA or partner arrangements, jurisdiction-by-jurisdiction licensing, best-execution, recordkeeping, and disclosure regimes. This is a major, gated undertaking — see companion [04-multi-tenancy-and-regulatory.md](../architecture/04-multi-tenancy-and-regulatory.md). **Do not enable real money without qualified legal/compliance counsel.**
- **Marketing guardrails:** no profit claims, no cherry-picked returns, mandatory risk disclosures, benchmark + drawdown context — enforced in copy review and in the product surfaces themselves.

### 15.3 Operational
- Disaster recovery + backups for the system of record and journal.
- Provider-outage runbooks (degrade gracefully: pause automation, mark data stale, tell users honestly).
- Incident response including AI-behavior incidents (a bad-but-blocked suggestion is a near-miss to review).
- Cost governance for data providers + LLM usage.
- Clear data retention & deletion policy honoring user rights.

---

# PART C — EXECUTION

## 16. Phased roadmap

### Phase 0 — Foundations & decisions (weeks 0–4)
- Lock positioning, disclaimers, and the "is/is not" contract; **early legal review** of the education-vs-advice line.
- Provider selection (reuse FMP + Alpaca paper from this repo), data schema, core data model.
- Design system primitives + the Suggestion Card spec.
- Define risk-limit model and the deterministic candidate/sizing interfaces.
**Exit:** signed-off scope, contracts, and the safety model on paper.

### Phase 1 — Safety & data spine (weeks 4–10) — *build this first*
- Ingestion + normalization for prices, fundamentals, news, light macro; freshness policy.
- **Deterministic Risk & Guardrail Service + sizing engine** (the spine).
- **Paper execution engine** with honest fills + reconciliation + append-only journal.
- Portfolio/accounting service (holdings, cash, perf-vs-benchmark, drawdown).
- Auth, accounts, tenant isolation.
**Exit:** you can place a limit-checked, journaled paper trade and see honest performance — *with no AI yet*. Safety proven before intelligence added.

### Phase 2 — The agent (weeks 10–18)
- Signal/candidate engine (deterministic idea generation).
- AI orchestration: RAG context assembly, reasoning pass, explanation assembly, schema validation.
- Suggestion Cards + explanation traces (L1/L2/L3) in the React app.
- Conversational grounded Q&A.
- Eval harness + red-team + calibration tracking.
**Exit:** end-to-end explained suggestions, human-approve-to-execute, fully traceable and safe.

### Phase 3 — Beginner experience & retention (weeks 18–26)
- Guided onboarding + risk/goals interview.
- Daily/weekly digest + notifications.
- Contextual education (definitions, explainers).
- Decision journal + behavioral feedback + honest performance reviews.
- Polish: accessibility, empty/loading states, microcopy, calm cadence.
**Exit:** a coherent, trustworthy beginner product ready for closed beta.

### Phase 4 — Trust-earning extensions (post-beta)
- Bounded auto-mode (only after the risk layer is battle-tested in beta).
- User-authored simple strategies + backtesting (walk-forward, drawdown-forward).
- Scenario simulator, goal planning, richer sentiment/social with manipulation defenses.

### Phase 5 — Real-money mode (major, gated, only with counsel)
- KYC/AML, suitability, funding, broker/exchange adapters (same execution interface, new adapter).
- Elevated compliance, disclosures, lowered defaults, cooling-off, jurisdiction rollout.
- Everything reuses the Phase 1 safety spine — no re-architecture.

### 16.1 What to build first, and why (the crux)
**Build the safety and data spine (Phase 1) before any AI.** The most common failure mode for this
class of product is a clever agent bolted onto a weak execution/risk core — impressive demos,
dangerous product. By proving that a limit-checked, reconciled, journaled paper trade works *with no
AI in the loop*, we guarantee the agent is always additive on top of a system that is already safe.
The AI then only ever *proposes* into a pipeline that is provably incapable of breaching a limit.
This ordering is also what makes the eventual real-money graduation a configuration + compliance
exercise rather than a rewrite.

Second priority is the **Suggestion Card + explanation trace**, because it is simultaneously the
product's core differentiator and the physical embodiment of its trust promise. Getting the
explanation layer right early forces the whole backend to produce auditable, cited, sized decisions —
which is exactly the discipline the rest of the system needs.

## 17. Open questions and implementation risks

### 17.1 Open product questions
- **Advice line:** exactly where does "education/decision support" end and "regulated advice" begin in our target jurisdictions? (Blocking; needs counsel.)
- **Auto-mode appetite:** do beginners actually want automation, or does it undermine the learning goal? Validate in beta before investing heavily.
- **Universe scope:** how curated should the beginner asset universe be at MVP? (Recommend: tight and safe.)
- **Monetization:** subscription vs. freemium vs. real-money-conversion — and how to monetize without creating overtrading incentives (must not compromise the no-dark-patterns principle).
- **Crypto handling:** 24/7 markets, custody, and volatility change cadence and risk defaults vs. equities.

### 17.2 Key implementation risks
- **AI hallucination / unfaithful explanations** → mitigated by deterministic candidates, RAG-grounding, schema validation, faithfulness-by-construction, and evals. Residual risk remains; monitor.
- **Prompt injection via ingested news/social** → treat ingested text as untrusted; sandbox; monitor.
- **Over-trust / automation bias** — users may over-rely on the agent. Mitigate with honest confidence, forced reflection, and calibration transparency.
- **Data provider reliability/cost** → abstraction, caching, graceful degradation, budgets.
- **Paper→real fidelity gap** — simulated fills flatter results; be explicit, model slippage, and reset expectations at graduation.
- **Regulatory misstep** — the highest-severity risk; gated behind counsel and Phase 5.
- **Beginner overwhelm creep** — feature pressure erodes simplicity over time; defend cadence/quantity caps and progressive disclosure as invariants.
- **Confidence calibration failure** — if stated confidence doesn't match reality, trust collapses; track and publish calibration honestly.

---

## Appendix A — MVP must-have checklist

- [ ] Guided onboarding + risk/goals interview → starter profile + funded paper account
- [ ] Deterministic risk & guardrail service (hard limit enforcement + veto)
- [ ] Deterministic sizing engine
- [ ] Paper execution engine (honest fills, reconciliation, idempotency)
- [ ] Append-only decision/audit journal
- [ ] Portfolio & accounting (holdings, cash, allocation, perf-vs-benchmark, drawdown)
- [ ] Ingestion: prices, fundamentals, news, light macro (+ freshness policy)
- [ ] Signal/candidate engine (deterministic idea generation)
- [ ] AI orchestration (RAG, reasoning, explanation assembly, schema validation)
- [ ] Suggestion Cards (L1/L2/L3 explanation, evidence chips, confidence, sizing, falsifier)
- [ ] Conversational grounded Q&A
- [ ] Watchlist + curated beginner universe (stocks + major crypto)
- [ ] Contextual education (inline definitions + explainers)
- [ ] Daily/weekly digest + notifications
- [ ] Settings (risk profile, notifications, privacy, pause-all/kill switch)
- [ ] Honest performance reporting (benchmark + drawdown; disclaimers)
- [ ] Observability + AI monitoring + calibration tracking
- [ ] Tenant isolation + auth + secrets management

## Appendix B — Feature matrix (MVP vs Future)

| Capability | MVP | Future |
|---|---|---|
| Explained suggestions (approve-to-execute) | ✅ | — |
| Conversational Q&A (grounded) | ✅ | + voice |
| Paper trading (stocks + major crypto) | ✅ | + real money |
| Deterministic risk layer + kill switch | ✅ | + real-money lower defaults |
| Contextual education | ✅ | + lesson tracks |
| Digest + notifications | ✅ | + smart event alerts |
| Bounded auto-mode | — | ✅ |
| User-authored strategies + backtesting | — | ✅ |
| Scenario / what-if simulator | — | ✅ |
| Social/sentiment (heavy) | light | ✅ (filtered) |
| Community / shared strategies | — | ✅ (gated) |
| Tax-lot awareness | — | ✅ (pre real money) |
| Real-money mode | — | ✅ (gated, Phase 5) |

## Appendix C — Glossary (sample of beginner terms the agent must be able to define in context)
Drawdown · Diversification · Position size · Limit vs market order · Volatility · Benchmark ·
Paper trading · Slippage · Allocation · Rebalancing · Confidence · Risk profile · Cash floor.

---

*This blueprint is a product/architecture document only — no code is prescribed. It is intended to
be read alongside the companion [alphadesk_saas_spec.md](alphadesk_saas_spec.md) and the architecture
notes under [docs/architecture/](../architecture/). Its central commitment: the AI explains and
proposes, a deterministic layer guarantees safety, the human stays in control, and the product earns
trust rather than promising profit.*
