import { screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { mockApi, renderWithProviders, REVIEW } from "../../testUtils";
import { ReviewCard } from "./ReviewCard";

afterEach(() => vi.restoreAllMocks());

test("review always frames return against benchmark and drawdown, with disclaimers", async () => {
  mockApi({ "GET /portfolio/review": () => ({ body: REVIEW }) });
  renderWithProviders(<ReviewCard />);

  expect(await screen.findByText(/ahead of SPY/)).toBeInTheDocument(); // verdict
  expect(screen.getByText("+1.00%")).toBeInTheDocument(); // your return...
  expect(screen.getByText("+0.50%")).toBeInTheDocument(); // ...never without the benchmark
  expect(screen.getByText("2.50%")).toBeInTheDocument(); // max drawdown
  expect(screen.getByText(/small sample/)).toBeInTheDocument();
  expect(screen.getByText(/does not predict future results/)).toBeInTheDocument();
  expect(screen.getByText(/This is not investment advice/)).toBeInTheDocument();
});

test("no-history review shows the honest 'no verdict' message", async () => {
  mockApi({
    "GET /portfolio/review": () => ({
      body: {
        ...REVIEW,
        trades: { closed_trades: 0, wins: 0, losses: 0, win_rate_pct: null, small_sample: true },
        verdict: "Not enough history yet for an honest verdict.",
      },
    }),
  });
  renderWithProviders(<ReviewCard />);
  expect(await screen.findByText(/Not enough history yet/)).toBeInTheDocument();
  // win rate omitted entirely rather than shown as a fake 0%
  expect(screen.queryByText(/win rate/)).not.toBeInTheDocument();
});
