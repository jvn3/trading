import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";

import { AgentScreen } from "../../screens/AgentScreen";
import { mockApi, renderWithProviders } from "../../testUtils";
import { proposedSuggestion, blockedSuggestion } from "./fixtures";

afterEach(() => vi.restoreAllMocks());

const TRACE = {
  suggestion_id: proposedSuggestion.id,
  candidate_ref: "momentum:AAPL",
  signal_features: [{ claim: "return_20d_pct = 8.32", source: "signal:momentum", as_of: "2026-07-09" }],
  evidence: [{ claim: "[1] Apple headline", source: "Reuters", as_of: "2026-07-08", ref: null }],
  sizing: { qty: "2" },
  prompt_version: "s2.3-v1",
  model_version: "fake-llm-1",
  agent_run_id: "run1",
  snapshot_id: "snap1",
  snapshot_as_of: "2026-07-09T12:00:00+00:00",
  risk_events: [],
};

const FILLED_DECISION = {
  suggestion: { ...proposedSuggestion, status: "approved" },
  order: {
    id: "o1", symbol: "AAPL", asset_class: "equity", side: "buy", order_type: "market",
    qty: "2", limit_price: null, status: "filled", rejected_reason: null,
    created_at: "2026-07-09T00:00:00+00:00",
    fill: { qty: "2", price: "210.61", fee: "0", filled_at: "2026-07-09T00:00:00+00:00" },
  },
  violations: [],
};

function agentRoutes(extra = {}) {
  return {
    "GET /suggestions": () => ({ body: { suggestions: [proposedSuggestion, blockedSuggestion] } }),
    [`GET /suggestions/${proposedSuggestion.id}/trace`]: () => ({ body: TRACE }),
    [`GET /suggestions/${blockedSuggestion.id}/trace`]: () => ({ body: { ...TRACE, suggestion_id: blockedSuggestion.id } }),
    ...extra,
  };
}

// --- S2.5: live SuggestionCards ---

test("renders live suggestions; blocked one disables Approve and teaches", async () => {
  mockApi(agentRoutes());
  renderWithProviders(<AgentScreen />);

  expect(await screen.findByText(proposedSuggestion.headline)).toBeInTheDocument();
  expect(screen.getByText(blockedSuggestion.headline)).toBeInTheDocument();

  const approveButtons = screen.getAllByRole("button", { name: "Approve" });
  expect(approveButtons.some((b) => (b as HTMLButtonElement).disabled)).toBe(true);
  expect(screen.getByRole("note", { name: "Why this was blocked" })).toHaveTextContent(
    blockedSuggestion.blockedReason!,
  );
});

test("approve flows through decisions API and reports the fill", async () => {
  const user = userEvent.setup();
  const calls = mockApi(
    agentRoutes({
      [`POST /suggestions/${proposedSuggestion.id}/approve`]: () => ({ body: FILLED_DECISION }),
    }),
  );
  renderWithProviders(<AgentScreen />);
  await screen.findByText(proposedSuggestion.headline);

  const approve = screen
    .getAllByRole("button", { name: "Approve" })
    .find((b) => !(b as HTMLButtonElement).disabled)!;
  await user.click(approve); // arm
  await user.click(screen.getByRole("button", { name: "Confirm Approve?" }));

  expect(await screen.findByRole("status", { name: "Execution result" })).toHaveTextContent(
    "Executed: buy 2 AAPL @ $210.61",
  );
  expect(calls.some((c) => c.key === `POST /suggestions/${proposedSuggestion.id}/approve`)).toBe(true);
});

test("run agent button triggers a fresh run", async () => {
  const user = userEvent.setup();
  const calls = mockApi(
    agentRoutes({
      "POST /agent/run": () => ({ body: { run_id: "r1", status: "completed", suggestions: [] } }),
    }),
  );
  renderWithProviders(<AgentScreen />);
  await screen.findByText(proposedSuggestion.headline);
  await user.click(screen.getByRole("button", { name: "Get fresh suggestions" }));
  await waitFor(() => expect(calls.some((c) => c.key === "POST /agent/run")).toBe(true));
});

// --- S2.6: trace ---

test("explanation trace shows candidate logic, sources, and model metadata", async () => {
  const user = userEvent.setup();
  mockApi(agentRoutes());
  renderWithProviders(<AgentScreen />);
  await screen.findByText(proposedSuggestion.headline);

  await user.click(screen.getAllByRole("button", { name: /Show your work/ })[0]);
  expect(await screen.findByText("return_20d_pct = 8.32")).toBeInTheDocument();
  expect(screen.getByText(/momentum:AAPL/)).toBeInTheDocument();
  expect(screen.getByText(/fake-llm-1/)).toBeInTheDocument();
  expect(screen.getByText(/s2\.3-v1/)).toBeInTheDocument();
});

// --- S2.8: chat streaming ---

test("chat streams tokens and shows sources", async () => {
  const user = userEvent.setup();
  mockApi(
    agentRoutes({
      "POST /chat": () => ({
        sse: [
          { type: "token", text: "Whether to buy " },
          { type: "token", text: "depends on your risk limits. " },
          { type: "token", text: "This is not investment advice." },
          {
            type: "sources",
            citations: [
              { doc_id: "d1", title: "Apple headline", source: "Reuters", url: "https://example.com/a", published_at: "2026-07-08T00:00:00+00:00" },
            ],
          },
          { type: "done" },
        ],
      }),
    }),
  );
  renderWithProviders(<AgentScreen />);
  await screen.findByText(proposedSuggestion.headline);

  await user.type(screen.getByLabelText("Chat message"), "should I buy AAPL?");
  await user.click(screen.getByRole("button", { name: "Send" }));

  await waitFor(() =>
    expect(screen.getByLabelText("Chat messages")).toHaveTextContent(
      "Whether to buy depends on your risk limits. This is not investment advice.",
    ),
  );
  expect(screen.getByLabelText("Sources")).toHaveTextContent("[1] Reuters");
});

test("chat surfaces stream errors inline", async () => {
  const user = userEvent.setup();
  mockApi(
    agentRoutes({
      "POST /chat": () => ({
        sse: [{ type: "error", message: "provider unavailable" }, { type: "done" }],
      }),
    }),
  );
  renderWithProviders(<AgentScreen />);
  await screen.findByText(proposedSuggestion.headline);

  await user.type(screen.getByLabelText("Chat message"), "hello");
  await user.click(screen.getByRole("button", { name: "Send" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("provider unavailable");
});
