# AlphaDash — beginner strategy-agent product

The beginner-facing surface of the platform described in
[docs/product/beginner_agent_product_blueprint.md](../docs/product/beginner_agent_product_blueprint.md).

Paper-trading first, stocks + crypto, safety-first. This is a **separate application** from the
personal `jay-trading` engine at [`src/jay_trading`](../src/jay_trading); it lives in the same repo
so it can reuse the existing provider / risk / executor primitives (wired in from S1.1 onward), but
it has its own dependency graph, lockfile, and tests. Nothing here touches the live personal system.

## Layout

```
alphadash/
├── backend/     # Python FastAPI BFF + services (own pyproject + uv.lock)
└── frontend/    # React + Vite + TypeScript + Zustand + TanStack Query
```

## Build order

**Live progress + per-session frozen contracts:** [BUILD_TRACKER.md](BUILD_TRACKER.md) — the single
source of truth. Update it (tick acceptance boxes, set status, fill `Landed:`) as work lands.

Sessions are defined in the blueprint's roadmap (§16). This scaffold is **S0.1** (done). Next:
S0.2 (schema/migrations), S0.3 (provider interfaces + stubs), S0.4 (design system).

## Quick start

Backend:
```
cd alphadash/backend
uv sync
uv run pytest
uv run uvicorn alphadash.main:app --reload --port 8000
```

Frontend:
```
cd alphadash/frontend
npm install
npm run test
npm run dev
```
