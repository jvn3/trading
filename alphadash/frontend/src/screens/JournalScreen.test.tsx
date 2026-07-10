import { screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { mockApi, renderWithProviders } from "../testUtils";
import { JournalScreen } from "./JournalScreen";

afterEach(() => vi.restoreAllMocks());

const ENTRIES = [
  {
    id: "j3",
    entry_type: "decision",
    ref_id: "d1",
    payload: { suggestion_id: "s1", action: "dismiss", reason: "not today" },
    created_at: "2026-07-09T10:05:00+00:00",
  },
  {
    id: "j2",
    entry_type: "fill",
    ref_id: "f1",
    payload: { order_id: "o1", symbol: "AAPL", side: "buy", qty: "1", price: "210.61" },
    created_at: "2026-07-09T10:00:00+00:00",
  },
  {
    id: "j1",
    entry_type: "note",
    ref_id: "p1",
    payload: { event: "onboarding", profile: "balanced" },
    created_at: "2026-07-09T09:00:00+00:00",
  },
];

test("journal renders a human timeline of decisions, trades and notes", async () => {
  mockApi({
    "GET /journal": () => ({ body: { entries: ENTRIES, nudges: [] } }),
  });
  renderWithProviders(<JournalScreen />);

  expect(await screen.findByText(/You dismissed a suggestion — "not today"/)).toBeInTheDocument();
  expect(screen.getByText(/Trade executed: buy 1 AAPL @ 210.61/)).toBeInTheDocument();
  expect(screen.getByText(/Onboarding set your profile to balanced/)).toBeInTheDocument();
  expect(screen.getByText(/append-only/)).toBeInTheDocument(); // teaching copy
});

test("behavioral nudges render as banners above the timeline", async () => {
  mockApi({
    "GET /journal": () => ({
      body: {
        entries: ENTRIES,
        nudges: [
          {
            kind: "overtrading",
            severity: "warn",
            message: "You've made 5 of your 5 trades this week.",
          },
          {
            kind: "loss_chasing",
            severity: "warn",
            message: "You bought shortly after selling at a loss.",
          },
        ],
      },
    }),
  });
  renderWithProviders(<JournalScreen />);

  expect(await screen.findByText(/5 of your 5 trades/)).toBeInTheDocument();
  expect(screen.getByText("Trading a lot")).toBeInTheDocument();
  expect(screen.getByText("Chasing losses?")).toBeInTheDocument();
  expect(screen.getByText(/bought shortly after selling at a loss/)).toBeInTheDocument();
});

test("empty journal teaches instead of showing a blank page", async () => {
  mockApi({ "GET /journal": () => ({ body: { entries: [], nudges: [] } }) });
  renderWithProviders(<JournalScreen />);
  expect(await screen.findByText(/Your first decision/)).toBeInTheDocument();
});
