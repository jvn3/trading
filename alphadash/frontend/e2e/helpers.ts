import { expect, type Page } from "@playwright/test";

let counter = 0;

export function uniqueEmail(prefix: string): string {
  counter += 1;
  return `${prefix}-${Date.now()}-${counter}@e2e.example`;
}

export const PASSWORD = "e2e-password-long";

export async function register(page: Page, email: string): Promise<void> {
  await page.goto("/");
  await page.getByText("New here? Create an account", { exact: false }).click();
  await page.getByLabel("Name").fill("E2E User");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("PAPER — simulated money")).toBeVisible();
}
