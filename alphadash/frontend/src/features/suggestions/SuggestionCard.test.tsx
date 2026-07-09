import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";

import { blockedSuggestion, proposedSuggestion } from "./fixtures";
import { SuggestionCard } from "./SuggestionCard";

function renderCard(suggestion = proposedSuggestion) {
  const handlers = {
    onApprove: vi.fn(),
    onModify: vi.fn(),
    onDismiss: vi.fn(),
    onAsk: vi.fn(),
  };
  render(<SuggestionCard suggestion={suggestion} {...handlers} />);
  return handlers;
}

test("L1 is always visible: headline, rationale, confidence", () => {
  renderCard();
  expect(
    screen.getByRole("heading", { name: proposedSuggestion.headline }),
  ).toBeInTheDocument();
  expect(screen.getByText(proposedSuggestion.rationale)).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("Medium confidence · 62%");
});

test("L2 lives behind the DisclosurePanel: evidence, order, worst case, falsifier", async () => {
  const user = userEvent.setup();
  renderCard();

  expect(screen.queryByText(proposedSuggestion.worstCase)).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: /Why we think this/ }));

  expect(screen.getByText(proposedSuggestion.evidence[0].claim)).toBeInTheDocument();
  expect(screen.getByText(/FMP earnings/)).toBeInTheDocument();
  expect(screen.getByText(/buy 2 AAPL \(limit @ 210\.00\)/)).toBeInTheDocument();
  expect(screen.getByText("-420.00")).toBeInTheDocument();
  expect(screen.getByText("4.2% of portfolio")).toBeInTheDocument();
  expect(screen.getByText(proposedSuggestion.worstCase)).toBeInTheDocument();
  expect(screen.getByText(proposedSuggestion.falsifier)).toBeInTheDocument();
});

test("all four action callbacks fire with the suggestion id", async () => {
  const user = userEvent.setup();
  const handlers = renderCard();

  // Approve is consequence-scaled: first tap arms, second confirms.
  await user.click(screen.getByRole("button", { name: "Approve" }));
  await user.click(screen.getByRole("button", { name: "Confirm Approve?" }));
  await user.click(screen.getByRole("button", { name: "Modify" }));
  await user.click(screen.getByRole("button", { name: "Dismiss" }));
  await user.click(screen.getByRole("button", { name: "Ask" }));

  expect(handlers.onApprove).toHaveBeenCalledWith(proposedSuggestion.id);
  expect(handlers.onModify).toHaveBeenCalledWith(proposedSuggestion.id);
  expect(handlers.onDismiss).toHaveBeenCalledWith(proposedSuggestion.id);
  expect(handlers.onAsk).toHaveBeenCalledWith(proposedSuggestion.id);
});

test("blocked state disables Approve and teaches via blockedReason", async () => {
  const user = userEvent.setup();
  const handlers = renderCard(blockedSuggestion);

  const note = screen.getByRole("note", { name: "Why this was blocked" });
  expect(note).toHaveTextContent(blockedSuggestion.blockedReason!);

  const approve = screen.getByRole("button", { name: "Approve" });
  expect(approve).toBeDisabled();
  await user.click(approve);
  expect(handlers.onApprove).not.toHaveBeenCalled();

  // Other actions stay available — dismissing a blocked idea is still a decision.
  await user.click(screen.getByRole("button", { name: "Dismiss" }));
  expect(handlers.onDismiss).toHaveBeenCalledWith(blockedSuggestion.id);
});
