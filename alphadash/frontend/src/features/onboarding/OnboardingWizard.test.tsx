import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";

import { mockApi, renderWithProviders } from "../../testUtils";
import { OnboardingWizard } from "./OnboardingWizard";

afterEach(() => vi.restoreAllMocks());

const STATUS = { onboarded: false, profiles: {} };
const RESULT = {
  profile: "conservative",
  onboarded: true,
  limits: {
    max_position_pct: "5",
    max_asset_class_pct: { equity: "60", crypto: "0" },
    max_trades_per_week: 2,
    cash_floor_pct: "30",
    per_suggestion_max_pct: "2",
    drawdown_pause_pct: "10",
  },
};

async function answerAll(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByLabelText("I'm brand new"));
  await user.click(screen.getByLabelText("Sell — I'd want out"));
  await user.click(screen.getByLabelText("Not losing what I have"));
}

test("submit stays disabled until every question is answered", async () => {
  const user = userEvent.setup();
  mockApi({ "GET /onboarding": () => ({ body: STATUS }) });
  renderWithProviders(<OnboardingWizard onDone={() => {}} />);

  const submit = await screen.findByRole("button", { name: "Set up my safety rules" });
  expect(submit).toBeDisabled();

  await user.click(screen.getByLabelText("I'm brand new"));
  await user.click(screen.getByLabelText("Sell — I'd want out"));
  expect(submit).toBeDisabled(); // 2 of 3

  await user.click(screen.getByLabelText("Not losing what I have"));
  expect(submit).toBeEnabled();
});

test("completing the interview posts answers and explains the resulting limits", async () => {
  const user = userEvent.setup();
  const calls = mockApi({
    "GET /onboarding": () => ({ body: STATUS }),
    "POST /onboarding": () => ({ body: RESULT }),
  });
  const onDone = vi.fn();
  renderWithProviders(<OnboardingWizard onDone={onDone} />);

  await answerAll(user);
  await user.click(screen.getByRole("button", { name: "Set up my safety rules" }));

  // Result screen teaches the applied limits
  expect(await screen.findByText(/Your safety rules:/)).toBeInTheDocument();
  expect(screen.getAllByText("conservative").length).toBeGreaterThan(0);
  expect(screen.getByText("5%")).toBeInTheDocument(); // max position
  expect(screen.getByText(/Not investment advice/)).toBeInTheDocument();

  const post = calls.find((c) => c.key === "POST /onboarding");
  expect(post).toBeTruthy();
  expect(JSON.parse(String(post!.init?.body))).toEqual({
    experience: "new",
    drop_reaction: "sell",
    goal: "preserve",
  });

  await user.click(screen.getByRole("button", { name: "Take me to my dashboard" }));
  expect(onDone).toHaveBeenCalled();
});

test("a backend rejection surfaces as an alert, not a silent failure", async () => {
  const user = userEvent.setup();
  mockApi({
    "GET /onboarding": () => ({ body: STATUS }),
    "POST /onboarding": () => ({ status: 422, body: { detail: "experience must be one of ..." } }),
  });
  renderWithProviders(<OnboardingWizard onDone={() => {}} />);

  await answerAll(user);
  await user.click(screen.getByRole("button", { name: "Set up my safety rules" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/experience must be/);
});
