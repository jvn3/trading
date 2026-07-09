// Test helpers: fetch mocking by "METHOD /path" and app rendering with providers + MemoryRouter.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

type Handler = (init?: RequestInit) => { status?: number; body: unknown };
export type Routes = Record<string, Handler>;

export function mockApi(routes: Routes) {
  const calls: Array<{ key: string; init?: RequestInit }> = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = typeof input === "string" ? input : (input as Request).url;
    const path = url.replace(/^https?:\/\/[^/]+/, "").replace(/^\/api/, "").split("?")[0];
    const key = `${init?.method ?? "GET"} ${path}`;
    calls.push({ key, init });
    const handler = routes[key];
    if (!handler) {
      return new Response(JSON.stringify({ detail: `no mock for ${key}` }), { status: 404 });
    }
    const { status = 200, body } = handler(init);
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  });
  return calls;
}

export function renderWithProviders(ui: ReactNode, { route = "/" } = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

export const ME = { id: "u1", email: "t@example.com", display_name: "Tess" };
export const ACCOUNT = {
  id: "a1",
  mode: "paper",
  base_currency: "USD",
  starting_equity: "10000.00000000",
  paused: false,
  trading_mode: "paper",
};
export const EMPTY_PORTFOLIO = {
  equity: "10000.00000000",
  cash: "10000.00000000",
  positions: [],
  allocation_pct: { cash: 100 },
};
export const PERFORMANCE = {
  points: [{ day: "2026-07-08", equity: "10100.00", benchmark_equity: "10050.00" }],
  return_pct: 1.0,
  benchmark_return_pct: 0.5,
  max_drawdown_pct: 2.5,
  current_drawdown_pct: 0.0,
  benchmark_symbol: "SPY",
};
export const QUOTE = {
  symbol: "AAPL",
  price: "210.50",
  as_of: "2026-07-01T14:30:00+00:00",
  source: "stub",
  is_stale: false,
};
