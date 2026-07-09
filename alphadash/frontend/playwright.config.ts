import { defineConfig } from "@playwright/test";

// E2E stack (hermetic): FastAPI on :8710 (fresh sqlite, stub market data, fake LLM — no keys,
// no network) + Vite dev server on :5273 proxying /api to it. Every UI surface must have a spec
// under e2e/ (project rule as of Phase 2).

const API_PORT = 8710;
const WEB_PORT = 5273;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false, // single shared backend DB — specs create isolated users instead
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: [
        "bash -c '",
        "mkdir -p .e2e && rm -f .e2e/e2e.db && cd ../backend &&",
        `ALPHADASH_DATABASE_URL=sqlite:///../frontend/.e2e/e2e.db`,
        "ALPHADASH_CREATE_ALL=1 ALPHADASH_PROVIDERS=stub ALPHADASH_LLM_PROVIDER=fake",
        `uv run uvicorn alphadash.main:app --port ${API_PORT}'`,
      ].join(" "),
      url: `http://localhost:${API_PORT}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
    {
      command: `ALPHADASH_WEB_PORT=${WEB_PORT} ALPHADASH_API_TARGET=http://localhost:${API_PORT} npm run dev`,
      url: `http://localhost:${WEB_PORT}`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
    },
  ],
});
