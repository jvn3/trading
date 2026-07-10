import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";

import { ACCOUNT, LIMITS, mockApi, renderWithProviders } from "../testUtils";
import { SettingsScreen } from "./SettingsScreen";

afterEach(() => vi.restoreAllMocks());

test("settings displays every limit with plain-language help", async () => {
  mockApi({
    "GET /account/limits": () => ({ body: LIMITS }),
    "GET /account": () => ({ body: ACCOUNT }),
  });
  renderWithProviders(<SettingsScreen />);

  expect(await screen.findByLabelText(/Max single position/)).toHaveValue("10");
  expect(screen.getByLabelText(/Cash floor/)).toHaveValue("10");
  expect(screen.getByLabelText(/Max trades per week/)).toHaveValue("5");
  expect(screen.getByLabelText(/Max in stocks/)).toHaveValue("80");
  expect(screen.getByLabelText(/Max in crypto/)).toHaveValue("10");
  expect(screen.getByText(/kill switch/)).toBeInTheDocument(); // pause explainer
  expect(screen.getByText(/Not\s+investment advice/)).toBeInTheDocument();
});

test("saving edited limits round-trips and warns when loosened", async () => {
  const user = userEvent.setup();
  const calls = mockApi({
    "GET /account/limits": () => ({ body: LIMITS }),
    "GET /account": () => ({ body: ACCOUNT }),
    "PUT /account/limits": () => ({
      body: {
        limits: { ...LIMITS, max_position_pct: "20" },
        profile: "custom",
        loosened: ["max_position_pct"],
      },
    }),
  });
  renderWithProviders(<SettingsScreen />);

  const input = await screen.findByLabelText(/Max single position/);
  await user.clear(input);
  await user.type(input, "20");

  // Two-tap confirm — consequence-scaled, same as trading actions
  await user.click(screen.getByRole("button", { name: "Save safety rules" }));
  await user.click(screen.getByRole("button", { name: "Confirm Save safety rules?" }));

  expect(await screen.findByRole("status")).toHaveTextContent(/custom/);
  expect(screen.getByText(/you loosened max_position_pct/)).toBeInTheDocument();

  const put = calls.find((c) => c.key === "PUT /account/limits");
  expect(JSON.parse(String(put!.init?.body)).max_position_pct).toBe("20");
});

test("a validation rejection from the API renders as an alert", async () => {
  const user = userEvent.setup();
  mockApi({
    "GET /account/limits": () => ({ body: LIMITS }),
    "GET /account": () => ({ body: ACCOUNT }),
    "PUT /account/limits": () => ({
      status: 422,
      body: { detail: "max_position_pct must be between 0 and 100" },
    }),
  });
  renderWithProviders(<SettingsScreen />);

  await screen.findByLabelText(/Max single position/);
  await user.click(screen.getByRole("button", { name: "Save safety rules" }));
  await user.click(screen.getByRole("button", { name: "Confirm Save safety rules?" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/between 0 and 100/);
});

test("paused account is visible in settings", async () => {
  mockApi({
    "GET /account/limits": () => ({ body: LIMITS }),
    "GET /account": () => ({ body: { ...ACCOUNT, paused: true } }),
  });
  renderWithProviders(<SettingsScreen />);
  expect(await screen.findByText("Currently paused")).toBeInTheDocument();
});
