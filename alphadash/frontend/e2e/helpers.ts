import { expect, type Page } from "@playwright/test";

let counter = 0;

export function uniqueEmail(prefix: string): string {
  counter += 1;
  return `${prefix}-${Date.now()}-${counter}@e2e.example`;
}

export const PASSWORD = "e2e-password-long";

// Answers that map to the "balanced" preset — keeps post-onboarding behavior identical to the
// Phase 2 registration defaults, so agent/portfolio specs see the same limits as before.
export const BALANCED_ANSWERS = {
  experience: "I've dabbled a bit",
  drop: "Wait it out",
  goal: "Learning how this works",
};

export async function completeOnboarding(
  page: Page,
  answers: { experience: string; drop: string; goal: string } = BALANCED_ANSWERS,
): Promise<void> {
  await expect(page.getByText("Three quick questions")).toBeVisible();
  await page.getByLabel(answers.experience).click();
  await page.getByLabel(answers.drop).click();
  await page.getByLabel(answers.goal).click();
  await page.getByRole("button", { name: "Set up my safety rules" }).click();
  await expect(page.getByText(/Your safety rules:/)).toBeVisible();
  await page.getByRole("button", { name: "Take me to my dashboard" }).click();
}

export async function register(page: Page, email: string): Promise<void> {
  await page.goto("/");
  await page.getByText("New here? Create an account", { exact: false }).click();
  await page.getByLabel("Name").fill("E2E User");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  // S3.1: every fresh account goes through the guided interview first.
  await completeOnboarding(page);
  await expect(page.getByText("PAPER — simulated money")).toBeVisible();
}

// Registration without completing onboarding — for specs that test the wizard itself.
export async function registerRaw(page: Page, email: string): Promise<void> {
  await page.goto("/");
  await page.getByText("New here? Create an account", { exact: false }).click();
  await page.getByLabel("Name").fill("E2E User");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
}
