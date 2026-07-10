// Test helpers: fetch mocking by "METHOD /path" and app rendering with providers + MemoryRouter.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

type Handler = (init?: RequestInit) => { status?: number; body?: unknown; sse?: unknown[] };
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
    const { status = 200, body, sse } = handler(init);
    if (sse) {
      const text = sse.map((e) => `data: ${JSON.stringify(e)}\n\n`).join("");
      return new Response(text, {
        status,
        headers: { "Content-Type": "text/event-stream" },
      });
    }
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

export const ME = { id: "u1", email: "t@example.com", display_name: "Tess", onboarded: true };
export const ME_FRESH = { ...ME, onboarded: false };
export const LIMITS = {
  max_position_pct: "10",
  max_asset_class_pct: { equity: "80", crypto: "10" },
  max_trades_per_week: 5,
  cash_floor_pct: "10",
  per_suggestion_max_pct: "5",
  drawdown_pause_pct: "15",
};
export const REVIEW = {
  performance: {
    points: [],
    return_pct: 1.0,
    benchmark_return_pct: 0.5,
    max_drawdown_pct: 2.5,
    current_drawdown_pct: 0.0,
    benchmark_symbol: "SPY",
  },
  trades: { closed_trades: 2, wins: 1, losses: 1, win_rate_pct: 50.0, small_sample: true },
  verdict: "You're ahead of SPY by 0.50 percentage points over this period.",
  disclaimers: [
    "This is a simulated paper account — no real money is at risk and real-world fills, fees and taxes would differ.",
    "Past performance (simulated or real) does not predict future results.",
    "This is not investment advice.",
  ],
};
export const DIGEST = {
  created: true,
  notification: {
    id: "n1",
    kind: "digest",
    title: "Your 2026-07-09 digest",
    body: "Portfolio value $10000.00 · 0 trade(s) in the last 24h · 1 open suggestion(s).",
    created_at: "2026-07-09T09:00:00+00:00",
    read_at: null,
    payload: {
      date: "2026-07-09",
      read: [
        {
          title: "Apple services revenue climbs",
          source: "stub-news",
          published_at: "2026-07-09T08:00:00+00:00",
          symbols: ["AAPL"],
          url: null,
        },
      ],
      what_changed: {
        equity: "10000.00000000",
        cash: "10000.00000000",
        fills_24h: [],
        risk_events_24h: [],
      },
      suggestions: [{ id: "s1", headline: "Consider a small buy of AAPL", confidence: "0.62" }],
      disclaimer: "Simulated paper account. Educational, not investment advice.",
    },
  },
};
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
export const BACKTEST = {
  strategy_id: "st1",
  windows: [
    {
      start: "2026-01-01",
      end: "2026-04-01",
      strategy_return_pct: 4.2,
      buy_hold_return_pct: 6.1,
      trades: 2,
    },
    {
      start: "2026-04-02",
      end: "2026-07-01",
      strategy_return_pct: 3.0,
      buy_hold_return_pct: 1.5,
      trades: 1,
    },
  ],
  total_return_pct: 7.3,
  buy_hold_return_pct: 7.7,
  benchmark_return_pct: 5.0,
  max_drawdown_pct: 9.5,
  closed_trades: 3,
  win_rate_pct: 66.67,
  windows_beating_buy_hold: 1,
  small_sample: true,
  days: 180,
  caveats: [
    "Only 3 closed trade(s) — far too few to distinguish luck from edge.",
    "Past performance (simulated or real) does not predict future results.",
  ],
};
export const STRATEGY = {
  id: "st1",
  name: "AAPL price above sma rule",
  source_text: "Buy AAPL when above its 20 day average, sell at 10% profit or 5% loss",
  status: "draft",
  params: {
    symbol: "AAPL",
    asset_class: "equity",
    entry: { kind: "price_above_sma", window: 20, threshold_pct: null },
    exit_condition: null,
    take_profit_pct: "10",
    stop_loss_pct: "5",
    size_pct: "5",
  },
  description:
    "Buy AAPL with 5% of the portfolio when the price closes above its 20-day average. Sell when the position is down 5% (stop loss) or the position is up 10% (take profit). Every trade still passes your safety limits before it can execute.",
  created_at: "2026-07-10T09:00:00+00:00",
  last_backtest: null,
};
export const SHOCK_IMPACT = {
  equity_before: "10000.00000000",
  equity_after: "9160.00",
  equity_change_pct: "-8.40",
  cash: "5790.00000000",
  positions: [
    {
      symbol: "AAPL",
      asset_class: "equity",
      value_before: "4210.00",
      value_after: "3370.00",
      applied_pct: "-20",
    },
  ],
  allocation_after_pct: { equity: 36.79, cash: 63.21 },
  would_trip_drawdown_pause: false,
  drawdown_pause_pct: "15",
};
export const QUOTE = {
  symbol: "AAPL",
  price: "210.50",
  as_of: "2026-07-01T14:30:00+00:00",
  source: "stub",
  is_stale: false,
};
