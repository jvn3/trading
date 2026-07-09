import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";

import { mockApi, QUOTE, renderWithProviders } from "../../testUtils";
import { OrderTicket } from "./OrderTicket";

afterEach(() => vi.restoreAllMocks());

const FILLED_RESULT = {
  order: {
    id: "o1",
    symbol: "AAPL",
    asset_class: "equity",
    side: "buy",
    order_type: "market",
    qty: "1",
    limit_price: null,
    status: "filled",
    rejected_reason: null,
    created_at: "2026-07-09T00:00:00+00:00",
    fill: { qty: "1", price: "210.61", fee: "0", filled_at: "2026-07-09T00:00:00+00:00" },
  },
  violations: [],
  replayed: false,
};

const VETOED_RESULT = {
  order: { ...FILLED_RESULT.order, id: "o2", status: "rejected", fill: null,
           rejected_reason: "order is 21.05% of equity, limit is 5% per trade" },
  violations: [
    { limit_type: "per_suggestion_max_pct", message: "order is 21.05% of equity, limit is 5% per trade" },
  ],
  replayed: false,
};

// S1.12: quote preview with provenance, two-tap confirm, Idempotency-Key header sent.
test("places a paper trade: quote shown, confirm required, idempotency key sent, fill confirmed", async () => {
  const user = userEvent.setup();
  const calls = mockApi({
    "GET /quotes/AAPL": () => ({ body: QUOTE }),
    "POST /orders": () => ({ status: 201, body: FILLED_RESULT }),
  });
  renderWithProviders(<OrderTicket />);

  expect(await screen.findByText("$210.50")).toBeInTheDocument(); // quote preview
  expect(screen.getByText(/stub/)).toBeInTheDocument(); // provenance chip

  await user.click(screen.getByRole("button", { name: "Buy AAPL" }));
  expect(calls.some((c) => c.key === "POST /orders")).toBe(false); // armed, not sent
  await user.click(screen.getByRole("button", { name: "Confirm Buy AAPL?" }));

  expect(await screen.findByRole("status")).toHaveTextContent("Filled: buy 1 AAPL @ $210.61");
  const post = calls.find((c) => c.key === "POST /orders");
  const headers = post!.init!.headers as Record<string, string>;
  expect(headers["Idempotency-Key"]).toMatch(/[0-9a-f-]{36}/);
});

test("risk veto renders as a teaching note with each violation", async () => {
  const user = userEvent.setup();
  mockApi({
    "GET /quotes/AAPL": () => ({ body: QUOTE }),
    "POST /orders": () => ({ status: 201, body: VETOED_RESULT }),
  });
  renderWithProviders(<OrderTicket />);

  await screen.findByText("$210.50");
  await user.click(screen.getByRole("button", { name: "Buy AAPL" }));
  await user.click(screen.getByRole("button", { name: "Confirm Buy AAPL?" }));

  const note = await screen.findByRole("note", { name: "Why this was blocked" });
  expect(note).toHaveTextContent("your safety rules stepped in");
  expect(note).toHaveTextContent("limit is 5% per trade");
});
