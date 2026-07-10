import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";

import { BACKTEST, mockApi, renderWithProviders, STRATEGY } from "../../testUtils";
import { StrategyLab } from "./StrategyLab";

afterEach(() => vi.restoreAllMocks());

test("drafting shows the compiled rules back, word for word (faithfulness)", async () => {
  const user = userEvent.setup();
  let drafted = false;
  const calls = mockApi({
    "GET /strategies": () => ({ body: drafted ? [STRATEGY] : [] }),
    "POST /strategies/draft": () => {
      drafted = true;
      return { status: 201, body: STRATEGY };
    },
  });
  renderWithProviders(<StrategyLab />);

  expect(await screen.findByText(/No strategies yet/)).toBeInTheDocument(); // teaching empty state

  await user.type(
    screen.getByLabelText("Your strategy idea"),
    "Buy AAPL when above its 20 day average, sell at 10% profit or 5% loss",
  );
  await user.click(screen.getByRole("button", { name: "Draft strategy" }));

  expect(await screen.findByText(/The rules, exactly as code will run them:/)).toBeInTheDocument();
  expect(screen.getByText(/closes above its 20-day average/)).toBeInTheDocument();
  expect(screen.getByText(/still passes your safety limits/)).toBeInTheDocument();
  const post = calls.find((c) => c.key === "POST /strategies/draft");
  expect(JSON.parse(String(post!.init?.body)).text).toMatch(/20 day average/);
});

test("backtest renders walk-forward windows, buy&hold comparison, and caveats", async () => {
  const user = userEvent.setup();
  mockApi({
    "GET /strategies": () => ({ body: [STRATEGY] }),
    "POST /strategies/st1/backtest": () => ({ body: BACKTEST }),
  });
  renderWithProviders(<StrategyLab />);

  await user.click(await screen.findByRole("button", { name: "Run backtest" }));

  expect(await screen.findByText(/Walk-forward windows \(1 of 2 beat buy & hold\)/)).toBeInTheDocument();
  expect(screen.getByText(/\+7\.30%/)).toBeInTheDocument(); // strategy total
  expect(screen.getByText(/\+7\.70%/)).toBeInTheDocument(); // buy & hold beside it
  expect(screen.getByText(/9\.50%/)).toBeInTheDocument(); // max drawdown
  expect(screen.getByText(/too few to distinguish luck from edge/)).toBeInTheDocument();
  expect(screen.getByText(/does not predict future results/)).toBeInTheDocument();
});

test("activate is disabled until a backtest exists, then two-tap confirms", async () => {
  const user = userEvent.setup();
  let activated = false;
  mockApi({
    "GET /strategies": () => ({
      body: [activated ? { ...STRATEGY, status: "active", last_backtest: BACKTEST } : STRATEGY],
    }),
    "POST /strategies/st1/backtest": () => ({ body: BACKTEST }),
    "POST /strategies/st1/activate": () => {
      activated = true;
      return { body: { ...STRATEGY, status: "active", last_backtest: BACKTEST } };
    },
  });
  renderWithProviders(<StrategyLab />);

  const activate = await screen.findByRole("button", { name: "Activate" });
  expect(activate).toBeDisabled(); // no backtest yet

  await user.click(screen.getByRole("button", { name: "Run backtest" }));
  await screen.findByText(/Walk-forward windows/);
  expect(screen.getByRole("button", { name: "Activate" })).toBeEnabled();

  await user.click(screen.getByRole("button", { name: "Activate" }));
  await user.click(screen.getByRole("button", { name: "Confirm Activate?" }));
  expect(await screen.findByText("active")).toBeInTheDocument();
});

test("backend rejection (e.g. activation gate) surfaces as an alert", async () => {
  const user = userEvent.setup();
  mockApi({
    "GET /strategies": () => ({ body: [{ ...STRATEGY, last_backtest: BACKTEST }] }),
    "POST /strategies/st1/activate": () => ({
      status: 409,
      body: { detail: "backtest the strategy before activating it" },
    }),
  });
  renderWithProviders(<StrategyLab />);

  await user.click(await screen.findByRole("button", { name: "Activate" }));
  await user.click(screen.getByRole("button", { name: "Confirm Activate?" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/backtest the strategy/);
});
