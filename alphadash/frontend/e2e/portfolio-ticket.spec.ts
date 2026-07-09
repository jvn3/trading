import { expect, test } from "@playwright/test";

import { register, uniqueEmail } from "./helpers";

// UI coverage: PortfolioScreen (S1.11) + OrderTicket (S1.12, Phase 1 exit gate in the browser).

test("place a paper trade end-to-end: quote → confirm → fill → holdings update", async ({ page }) => {
  await register(page, uniqueEmail("ticket"));
  await page.getByRole("navigation", { name: "Primary" }).getByText("Portfolio").click();

  // Portfolio essentials: benchmark + drawdown framing visible
  await expect(page.getByText("Total value (simulated)")).toBeVisible();
  await expect(page.getByText(/SPY same period/)).toBeVisible();
  await expect(page.getByText("Max drawdown (90d)")).toBeVisible();

  // Quote preview with provenance
  await expect(page.getByText("Latest price:")).toBeVisible();
  await expect(page.getByText("$210.50", { exact: true })).toBeVisible();

  await page.getByLabel("Quantity").fill("2");
  await page.getByRole("button", { name: "Buy AAPL" }).click();
  await page.getByRole("button", { name: "Confirm Buy AAPL?" }).click();

  await expect(page.getByRole("status")).toContainText("Filled: buy 2 AAPL @ $210.61");
  // Holdings table reflects the fill
  await expect(page.getByRole("table").getByText("AAPL")).toBeVisible();
  await expect(page.getByRole("table").getByText("2", { exact: true })).toBeVisible();
});

test("risk veto renders as teaching note with limits listed", async ({ page }) => {
  await register(page, uniqueEmail("veto"));
  await page.getByRole("navigation", { name: "Primary" }).getByText("Portfolio").click();
  await expect(page.getByText("Latest price:")).toBeVisible();

  await page.getByLabel("Quantity").fill("10"); // ~21% of equity > 5% per-trade cap
  await page.getByRole("button", { name: "Buy AAPL" }).click();
  await page.getByRole("button", { name: "Confirm Buy AAPL?" }).click();

  const note = page.getByRole("note", { name: "Why this was blocked" });
  await expect(note).toContainText("safety rules stepped in");
  await expect(note).toContainText("per trade");
});
