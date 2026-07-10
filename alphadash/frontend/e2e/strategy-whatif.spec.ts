import { expect, test } from "@playwright/test";

import { register, uniqueEmail } from "./helpers";

// UI coverage for Phase 4: StrategyLab (S4.2) and the what-if simulator (S4.3).
// Real backend: fake-LLM authoring, real walk-forward backtest on stub bars, real risk gate.

test("author → compiled rules → backtest → activate → agent suggests from the strategy", async ({
  page,
}) => {
  await register(page, uniqueEmail("lab"));

  // Strategy Lab is reachable from the Agent screen
  await page.getByRole("navigation", { name: "Primary" }).getByText("Agent").click();
  await page.getByRole("link", { name: "Strategy Lab →" }).click();
  await expect(page.getByText("No strategies yet", { exact: false })).toBeVisible();

  // Draft from plain language
  await page
    .getByLabel("Your strategy idea")
    .fill("Buy MSFT when price is above its 5 day average, sell at 8% profit or 4% loss");
  await page.getByRole("button", { name: "Draft strategy" }).click();

  // Faithfulness: the compiled rules are shown back before anything runs
  await expect(page.getByText("The rules, exactly as code will run them:")).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.getByText(/Buy MSFT with 5% of the portfolio/)).toBeVisible();
  await expect(page.getByText(/closes above its 5-day average/)).toBeVisible();

  // Activation is gated on a backtest
  await expect(page.getByRole("button", { name: "Activate" })).toBeDisabled();

  // Backtest: walk-forward windows + buy&hold comparison + caveats
  await page.getByRole("button", { name: "Run backtest" }).click();
  await expect(page.getByText(/Walk-forward windows/).first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/does not predict future results/)).toBeVisible();

  // Activate (two-tap)
  await page.getByRole("button", { name: "Activate" }).click();
  await page.getByRole("button", { name: "Confirm Activate?" }).click();
  await expect(page.getByText("active", { exact: true })).toBeVisible();

  // The active strategy now feeds the agent: run it and find a MSFT suggestion whose
  // trace points at the user strategy.
  await page.getByRole("navigation", { name: "Primary" }).getByText("Agent").click();
  await page.getByRole("button", { name: "Get fresh suggestions" }).click();
  const msftCard = page.locator("article").filter({ hasText: /buy of MSFT/ }).first();
  await expect(msftCard).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: /Show your work/ }).first().click();
  await expect(page.getByText(/user_strategy:/)).toBeVisible();
});

test("portfolio shock presets show honest damage and the auto-pause verdict", async ({
  page,
}) => {
  await register(page, uniqueEmail("shock"));

  // Build a real position first so the shock has something to bite
  await page.getByRole("navigation", { name: "Primary" }).getByText("Portfolio").click();
  await expect(page.getByText("Latest price:")).toBeVisible();
  await page.getByRole("button", { name: "Buy AAPL" }).click();
  await page.getByRole("button", { name: "Confirm Buy AAPL?" }).click();
  await expect(page.getByText(/Filled: buy/)).toBeVisible({ timeout: 15_000 });

  await page.getByRole("button", { name: "Stocks −20% (a bad year)" }).click();
  const result = page.getByRole("status", { name: "Scenario result" });
  await expect(result).toBeVisible({ timeout: 15_000 });
  await expect(result).toContainText("Your portfolio would go from");
  await expect(result).toContainText("AAPL:");
  await expect(result).toContainText(/auto-pause/);
});

test("trade preview blocks-in-advance exactly like the order path would", async ({ page }) => {
  await register(page, uniqueEmail("preview"));
  await page.getByRole("navigation", { name: "Primary" }).getByText("Portfolio").click();
  await expect(page.getByText("Latest price:")).toBeVisible();

  // 10 AAPL ≈ $2,105 on a $10k account → breaches the 5% per-trade cap
  await page.getByLabel("Quantity").fill("10");
  await page.getByRole("button", { name: "Preview impact" }).click();
  const preview = page.getByRole("note", { name: "Trade preview" });
  await expect(preview).toBeVisible({ timeout: 15_000 });
  await expect(preview).toContainText("would block this trade");
  await expect(preview).toContainText("limit is 5% per trade");

  // A small trade previews as allowed, and nothing was placed either way
  await page.getByLabel("Quantity").fill("1");
  await page.getByRole("button", { name: "Preview impact" }).click();
  await expect(preview).toContainText("would pass your safety rules", { timeout: 15_000 });
  await expect(preview).toContainText("Nothing has been placed");
});
