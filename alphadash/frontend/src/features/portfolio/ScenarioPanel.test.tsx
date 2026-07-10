import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";

import { mockApi, renderWithProviders, SHOCK_IMPACT } from "../../testUtils";
import { ScenarioPanel } from "./ScenarioPanel";

afterEach(() => vi.restoreAllMocks());

test("preset shock shows before/after, per-position damage, and pause verdict", async () => {
  const user = userEvent.setup();
  const calls = mockApi({ "POST /whatif/shock": () => ({ body: SHOCK_IMPACT }) });
  renderWithProviders(<ScenarioPanel />);

  await user.click(screen.getByRole("button", { name: "Stocks −20% (a bad year)" }));

  const result = await screen.findByRole("status", { name: "Scenario result" });
  expect(result).toHaveTextContent("$10,000.00");
  expect(result).toHaveTextContent("$9,160.00");
  expect(result).toHaveTextContent("-8.40%");
  expect(result).toHaveTextContent("AAPL: $4,210.00 → $3,370.00 (-20.00%)");
  expect(result).toHaveTextContent(/stays inside your 15% auto-pause threshold/);

  const post = calls.find((c) => c.key === "POST /whatif/shock");
  expect(JSON.parse(String(post!.init?.body))).toEqual({
    equity_pct: "-20",
    crypto_pct: "0",
    symbol_overrides: {},
  });
});

test("a shock past the drawdown threshold shows the auto-pause warning", async () => {
  const user = userEvent.setup();
  mockApi({
    "POST /whatif/shock": () => ({
      body: { ...SHOCK_IMPACT, equity_change_pct: "-18.00", would_trip_drawdown_pause: true },
    }),
  });
  renderWithProviders(<ScenarioPanel />);

  await user.click(screen.getByRole("button", { name: "2008-style: stocks −35%" }));
  expect(await screen.findByText("Auto-pause would trip")).toBeInTheDocument();
  expect(screen.getByText(/buying would stop automatically/)).toBeInTheDocument();
});

test("custom values run through the simulate button; API errors alert", async () => {
  const user = userEvent.setup();
  mockApi({
    "POST /whatif/shock": () => ({
      status: 422,
      body: { detail: "equity_pct must be between -95 and 100" },
    }),
  });
  renderWithProviders(<ScenarioPanel />);

  const input = screen.getByLabelText("Stocks move (%)");
  await user.clear(input);
  await user.type(input, "-99");
  await user.click(screen.getByRole("button", { name: "Simulate" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/between -95 and 100/);
});

test("empty portfolio teaches instead of showing an empty list", async () => {
  const user = userEvent.setup();
  mockApi({
    "POST /whatif/shock": () => ({
      body: { ...SHOCK_IMPACT, positions: [], equity_after: "10000.00", equity_change_pct: "0.00" },
    }),
  });
  renderWithProviders(<ScenarioPanel />);
  await user.click(screen.getByRole("button", { name: "Everything −10%" }));
  expect(await screen.findByText(/You hold no positions yet/)).toBeInTheDocument();
});
