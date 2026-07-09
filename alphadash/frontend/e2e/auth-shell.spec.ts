import { expect, test } from "@playwright/test";

import { PASSWORD, register, uniqueEmail } from "./helpers";

// UI coverage: AuthScreen (S1.10) + Shell (paper badge, kill switch, bottom nav).

test("register → shell with paper badge; logout → sign-in; login again", async ({ page }) => {
  const email = uniqueEmail("auth");
  await register(page, email);

  // Shell essentials
  await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
  for (const label of ["Home", "Agent", "Portfolio", "Learn"]) {
    await expect(page.getByRole("navigation", { name: "Primary" }).getByText(label)).toBeVisible();
  }

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("PAPER — simulated money")).toBeVisible();
});

test("wrong password shows generic error, no user enumeration", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Email").fill("ghost@e2e.example");
  await page.getByLabel("Password").fill("wrong-password-x");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toHaveText("invalid email or password");
});

test("kill switch pauses (two-tap) and blocks buys, resume unblocks", async ({ page }) => {
  await register(page, uniqueEmail("kill"));

  await page.getByRole("button", { name: "Pause all" }).click();
  await page.getByRole("button", { name: "Confirm Pause all?" }).click();
  await expect(page.getByRole("button", { name: "Resume" })).toBeVisible();
  await expect(page.getByRole("banner")).toContainText("Paused");

  // A buy while paused gets vetoed with a teaching note
  await page.getByRole("navigation", { name: "Primary" }).getByText("Portfolio").click();
  await expect(page.getByText("Latest price:")).toBeVisible();
  await page.getByRole("button", { name: "Buy AAPL" }).click();
  await page.getByRole("button", { name: "Confirm Buy AAPL?" }).click();
  await expect(page.getByRole("note", { name: "Why this was blocked" })).toContainText("paused");

  await page.getByRole("button", { name: "Resume" }).click();
  await expect(page.getByRole("button", { name: "Pause all" })).toBeVisible();
});

test("learn screen definition tooltips open", async ({ page }) => {
  await register(page, uniqueEmail("learn"));
  await page.getByRole("navigation", { name: "Primary" }).getByText("Learn").click();
  await page.getByRole("button", { name: "Drawdown" }).click();
  await expect(page.getByRole("note")).toContainText("highest point");
});
