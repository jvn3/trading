import { expect, test } from "@playwright/test";

import { register, uniqueEmail } from "./helpers";

// UI coverage: AgentScreen — SuggestionsPanel (S2.5), ExplanationTrace (S2.6), ChatPanel (S2.8).
// Backend runs the REAL pipeline (signals → sizing → fake LLM → risk gate) — nothing mocked
// in the browser.

test("agent run produces suggestion cards; trace shows the work; approve executes", async ({ page }) => {
  await register(page, uniqueEmail("agent"));
  await page.getByRole("navigation", { name: "Primary" }).getByText("Agent").click();

  await page.getByRole("button", { name: "Get fresh suggestions" }).click();

  // Suggestion card (L1) appears with confidence badge
  const firstCard = page.locator("article").first();
  await expect(firstCard).toContainText(/Consider a small buy of/, { timeout: 15_000 });
  await expect(firstCard.getByRole("status")).toContainText(/confidence/);

  // L2 disclosure
  await firstCard.getByRole("button", { name: /Why we think this/ }).click();
  await expect(firstCard.getByRole("heading", { name: "Evidence" })).toBeVisible();
  await expect(firstCard.getByRole("heading", { name: "Worst case" })).toBeVisible();

  // L3 trace — deterministic signal + model metadata
  await page.getByRole("button", { name: /Show your work/ }).first().click();
  await expect(page.getByText("1. Deterministic signal")).toBeVisible();
  await expect(page.getByText(/momentum:/).first()).toBeVisible();
  await expect(page.getByText(/fake-llm-1/)).toBeVisible();

  // Approve → two-tap → executed through the paper engine
  await firstCard.getByRole("button", { name: "Approve" }).click();
  await firstCard.getByRole("button", { name: "Confirm Approve?" }).click();
  await expect(page.getByRole("status", { name: "Execution result" })).toContainText(
    "Executed: buy",
    { timeout: 15_000 },
  );

  // The trade landed in the portfolio
  await page.getByRole("navigation", { name: "Primary" }).getByText("Portfolio").click();
  await expect(page.getByRole("table").locator("tr", { hasText: /AAPL|MSFT|BTCUSD/ }).first()).toBeVisible();
});

test("dismissing a suggestion records the decision", async ({ page }) => {
  await register(page, uniqueEmail("dismiss"));
  await page.getByRole("navigation", { name: "Primary" }).getByText("Agent").click();
  await page.getByRole("button", { name: "Get fresh suggestions" }).click();

  const firstCard = page.locator("article").first();
  await expect(firstCard).toContainText(/Consider a small/, { timeout: 15_000 });
  await firstCard.getByRole("button", { name: "Dismiss" }).click();

  await expect(page.getByText("Recent decisions")).toBeVisible();
  await expect(page.getByText(/dismissed:/)).toBeVisible();
});

test("chat streams a grounded, educational answer with disclaimer", async ({ page }) => {
  await register(page, uniqueEmail("chat"));
  await page.getByRole("navigation", { name: "Primary" }).getByText("Agent").click();
  // Seed evidence corpus through a run first
  await page.getByRole("button", { name: "Get fresh suggestions" }).click();
  await expect(page.locator("article").first()).toContainText(/Consider/, { timeout: 15_000 });

  await page.getByRole("textbox", { name: "Chat message" }).fill("Should I buy AAPL right now?");
  await page.getByRole("button", { name: "Send" }).click();

  const messages = page.getByLabel("Chat messages");
  await expect(messages).toContainText("not investment advice", { timeout: 15_000 });
  await expect(messages).toContainText(/depends on|bounded/);
});
