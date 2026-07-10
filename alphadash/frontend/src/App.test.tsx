import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";

import { AuthedApp } from "./App";
import {
  ACCOUNT,
  DIGEST,
  EMPTY_PORTFOLIO,
  ME,
  ME_FRESH,
  mockApi,
  PERFORMANCE,
  renderWithProviders,
  REVIEW,
} from "./testUtils";

afterEach(() => vi.restoreAllMocks());

// --- S1.10 shell ---

test("unauthenticated users see the sign-in screen with the paper disclaimer", async () => {
  mockApi({ "GET /auth/me": () => ({ status: 401, body: { detail: "not signed in" } }) });
  renderWithProviders(<AuthedApp />);
  expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  expect(screen.getByText(/Simulated trading only/)).toBeInTheDocument();
});

test("authenticated shell shows paper badge, kill switch, and bottom nav", async () => {
  mockApi({
    "GET /auth/me": () => ({ body: ME }),
    "GET /account": () => ({ body: ACCOUNT }),
    "GET /portfolio": () => ({ body: EMPTY_PORTFOLIO }),
    "GET /notifications": () => ({ body: [] }),
    "POST /digest/run": () => ({ body: DIGEST }),
  });
  renderWithProviders(<AuthedApp />);

  expect(await screen.findByText("PAPER — simulated money")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Pause all" })).toBeInTheDocument();
  const nav = screen.getByRole("navigation", { name: "Primary" });
  for (const label of ["Home", "Agent", "Portfolio", "Journal", "Learn", "Settings"]) {
    expect(nav).toHaveTextContent(label);
  }
});

test("a signed-in user who never onboarded is routed to the interview first", async () => {
  mockApi({
    "GET /auth/me": () => ({ body: ME_FRESH }),
    "GET /onboarding": () => ({ body: { onboarded: false, profiles: {} } }),
  });
  renderWithProviders(<AuthedApp />);
  expect(await screen.findByText("Three quick questions")).toBeInTheDocument();
  // The shell is NOT rendered — onboarding gates it
  expect(screen.queryByRole("navigation", { name: "Primary" })).not.toBeInTheDocument();
});

test("kill switch pauses via two-tap confirm and flips to Resume", async () => {
  const user = userEvent.setup();
  const calls = mockApi({
    "GET /auth/me": () => ({ body: ME }),
    "GET /account": () => ({ body: ACCOUNT }),
    "GET /portfolio": () => ({ body: EMPTY_PORTFOLIO }),
    "GET /notifications": () => ({ body: [] }),
    "POST /digest/run": () => ({ body: DIGEST }),
    "POST /account/pause": () => ({ body: { ...ACCOUNT, paused: true } }),
  });
  renderWithProviders(<AuthedApp />);

  await user.click(await screen.findByRole("button", { name: "Pause all" }));
  expect(calls.some((c) => c.key === "POST /account/pause")).toBe(false); // armed only
  await user.click(screen.getByRole("button", { name: "Confirm Pause all?" }));

  expect(await screen.findByRole("button", { name: "Resume" })).toBeInTheDocument();
  expect(screen.getByText("Paused")).toBeInTheDocument();
  expect(calls.some((c) => c.key === "POST /account/pause")).toBe(true);
});

// --- S1.11 portfolio screen ---

const HOLDINGS_PORTFOLIO = {
  equity: "10139.00",
  cash: "7999.00",
  positions: [
    {
      symbol: "AAPL",
      asset_class: "equity",
      quantity: "10.00000000",
      avg_cost: "100.05000000",
      market_value: "1100.00",
      unrealized_pl: "99.50",
      allocation_pct: 10.85,
    },
  ],
  allocation_pct: { equity: 10.85, cash: 78.89 },
};

test("portfolio screen renders holdings, allocation, benchmark and drawdown", async () => {
  mockApi({
    "GET /auth/me": () => ({ body: ME }),
    "GET /account": () => ({ body: ACCOUNT }),
    "GET /portfolio": () => ({ body: HOLDINGS_PORTFOLIO }),
    "GET /portfolio/performance": () => ({ body: PERFORMANCE }),
    "GET /portfolio/review": () => ({ body: REVIEW }),
    "GET /notifications": () => ({ body: [] }),
    "GET /quotes/AAPL": () => ({ body: { symbol: "AAPL", price: "110.00", as_of: "2026-07-08T00:00:00+00:00", source: "stub", is_stale: false } }),
  });
  renderWithProviders(<AuthedApp />, { route: "/portfolio" });

  expect(await screen.findByText("AAPL")).toBeInTheDocument();
  expect(screen.getByText("$10,139.00")).toBeInTheDocument(); // equity
  // Return + drawdown appear in the stat tiles AND the S3.5 honest-review card
  expect(screen.getAllByText("+1.00%").length).toBeGreaterThan(0); // return
  expect(screen.getByText(/SPY same period: \+0\.50%/)).toBeInTheDocument(); // benchmark framing
  expect(screen.getAllByText("2.50%").length).toBeGreaterThan(0); // max drawdown
  expect(screen.getByText("Allocation")).toBeInTheDocument();
});
