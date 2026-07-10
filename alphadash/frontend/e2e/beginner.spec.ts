import { expect, test } from "@playwright/test";

import { register, uniqueEmail } from "./helpers";

// UI coverage for the S3.x beginner experience: DigestPanel + NotificationsBell (S3.2),
// JournalScreen with nudges (S3.4), ReviewCard (S3.5), SettingsScreen (S3.6). Real backend —
// signals → fake LLM → risk gate → paper fills. Nothing mocked in the browser.

test("home shows today's digest; the bell carries it as an unread notification", async ({
  page,
}) => {
  await register(page, uniqueEmail("digest"));

  // Digest generates on first visit to Home
  await expect(page.getByText(/Today's read/)).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("What changed")).toBeVisible();
  await expect(page.getByText("Open suggestions")).toBeVisible();
  await expect(page.getByText(/Simulated paper account/)).toBeVisible();

  // The same digest lands in the notification feed, unread
  await page.getByRole("button", { name: /Notifications \(1 unread\)/ }).click();
  await expect(page.getByText(/digest/).first()).toBeVisible();

  // Tapping marks it read — the badge clears
  await page.getByRole("region", { name: "Notification list" }).getByRole("button").first().click();
  await expect(page.getByRole("button", { name: "Notifications", exact: true })).toBeVisible();
});

test("journal records the story: onboarding, a dismissal, a fill — append-only", async ({
  page,
}) => {
  await register(page, uniqueEmail("journal"));

  // Generate a suggestion and dismiss it
  await page.getByRole("navigation", { name: "Primary" }).getByText("Agent").click();
  await page.getByRole("button", { name: "Get fresh suggestions" }).click();
  const firstCard = page.locator("article").first();
  await expect(firstCard).toContainText(/Consider a small/, { timeout: 15_000 });
  await firstCard.getByRole("button", { name: "Dismiss" }).click();
  await expect(page.getByText(/dismissed:/)).toBeVisible();

  // Place a real paper trade
  await page.getByRole("navigation", { name: "Primary" }).getByText("Portfolio").click();
  await expect(page.getByText("Latest price:")).toBeVisible();
  await page.getByRole("button", { name: "Buy AAPL" }).click();
  await page.getByRole("button", { name: "Confirm Buy AAPL?" }).click();
  await expect(page.getByText(/Filled: buy/)).toBeVisible({ timeout: 15_000 });

  // The journal tells the whole story
  await page.getByRole("navigation", { name: "Primary" }).getByText("Journal").click();
  await expect(page.getByText(/append-only/)).toBeVisible();
  await expect(page.getByText(/Onboarding set your profile to balanced/)).toBeVisible();
  await expect(page.getByText(/You dismissed a suggestion/)).toBeVisible();
  await expect(page.getByText(/Trade executed: buy 1 AAPL/)).toBeVisible();
});

test("portfolio carries the honest review: benchmark, drawdown, disclaimers", async ({
  page,
}) => {
  await register(page, uniqueEmail("review"));
  await page.getByRole("navigation", { name: "Primary" }).getByText("Portfolio").click();

  await expect(page.getByText("Honest review (90 days)")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/Your return:/)).toBeVisible();
  await expect(page.getByText(/same period:/).first()).toBeVisible(); // benchmark never missing
  await expect(page.getByText(/Max drawdown:/)).toBeVisible(); // drawdown row
  await expect(page.getByText(/does not predict future results/)).toBeVisible();
  await expect(page.getByText(/This is not investment advice/)).toBeVisible();
});

test("settings edits limits with a loosening warning; values persist", async ({ page }) => {
  await register(page, uniqueEmail("settings"));
  await page.getByRole("navigation", { name: "Primary" }).getByText("Settings").click();

  const position = page.getByLabel("Max single position (% of portfolio)");
  await expect(position).toHaveValue("10"); // balanced default, persistently displayed
  await position.fill("20");

  await page.getByRole("button", { name: "Save safety rules" }).click();
  await page.getByRole("button", { name: "Confirm Save safety rules?" }).click();

  await expect(page.getByRole("status")).toContainText("custom");
  await expect(page.getByText(/you loosened max_position_pct/)).toBeVisible();

  // Persisted across a reload
  await page.reload();
  await page.getByRole("navigation", { name: "Primary" }).getByText("Settings").click();
  await expect(page.getByLabel("Max single position (% of portfolio)")).toHaveValue("20");
});

test("pause halts the agent's buys end-to-end (kill switch verified)", async ({ page }) => {
  await register(page, uniqueEmail("halt"));

  await page.getByRole("button", { name: "Pause all" }).click();
  await page.getByRole("button", { name: "Confirm Pause all?" }).click();
  await expect(page.getByRole("button", { name: "Resume" })).toBeVisible();

  // Agent still runs, but proposes no buys while paused. A fresh account has no positions to
  // trim either, so the run comes back empty — with the honest "no good ideas" teaching copy.
  await page.getByRole("navigation", { name: "Primary" }).getByText("Agent").click();
  await page.getByRole("button", { name: "Get fresh suggestions" }).click();
  await expect(page.getByText(/no good ideas today/)).toBeVisible({ timeout: 15_000 });
  await expect(page.locator("article").filter({ hasText: /Consider a small buy/ })).toHaveCount(0);
});
