import { expect, test } from "@playwright/test";

import { completeOnboarding, registerRaw, uniqueEmail } from "./helpers";

// UI coverage: OnboardingWizard (S3.1). The real backend applies the preset — nothing mocked.

test("new user is interviewed before the app; cautious answers yield the conservative profile", async ({
  page,
}) => {
  await registerRaw(page, uniqueEmail("onboard"));

  // Gate: no shell until the interview is done
  await expect(page.getByText("Three quick questions")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Primary" })).toHaveCount(0);

  // Submit is disabled until all three questions are answered
  const submit = page.getByRole("button", { name: "Set up my safety rules" });
  await expect(submit).toBeDisabled();

  await completeOnboarding(page, {
    experience: "I'm brand new",
    drop: "Sell — I'd want out",
    goal: "Not losing what I have",
  });

  // Landed in the shell with the paper badge
  await expect(page.getByText("PAPER — simulated money")).toBeVisible();

  // The conservative limits are live: Settings shows them
  await page.getByRole("navigation", { name: "Primary" }).getByText("Settings").click();
  await expect(page.getByLabel("Max single position (% of portfolio)")).toHaveValue("5");
  await expect(page.getByLabel("Max trades per week")).toHaveValue("2");
  await expect(page.getByLabel("Max in crypto (%)")).toHaveValue("0");
});

test("onboarded user goes straight to the app on next sign-in", async ({ page }) => {
  const email = uniqueEmail("reentry");
  await registerRaw(page, email);
  await completeOnboarding(page);
  await expect(page.getByText("PAPER — simulated money")).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("e2e-password-long");
  await page.getByRole("button", { name: "Sign in" }).click();

  // No interview the second time
  await expect(page.getByText("PAPER — simulated money")).toBeVisible();
  await expect(page.getByText("Three quick questions")).toHaveCount(0);
});
