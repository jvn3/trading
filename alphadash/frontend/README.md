# AlphaDash frontend

React + Vite + TypeScript. **Zustand** for ephemeral UI state, **TanStack Query** for all server
state (blueprint §11). Mobile-first, responsive.

```
npm install
npm run dev      # http://localhost:5173 (proxies /api -> http://localhost:8000)
npm run test     # vitest
npm run lint     # eslint
npm run build    # type-check + production build
```

## Conventions

- Server data → TanStack Query hooks. Never copy server data into Zustand.
- Zustand → view/selection/safety-UI flags only (see `src/app/store.ts`).
- API access goes through `src/lib/api.ts`; from S1.9 its types are generated from the backend
  OpenAPI schema.

The S0.1 `App` is a placeholder that proves the wiring. The real app shell (nav, routing, design
system) lands in S0.4 + S1.10.
