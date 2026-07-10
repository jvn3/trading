// S3.7 accessibility gate: every screen (not just the Gallery) passes axe.
// color-contrast is disabled because jsdom has no rendering engine — contrast is checked in the
// real-browser Playwright pass.

import { screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { axe } from "vitest-axe";

import { AuthedApp } from "./App";
import {
  ACCOUNT,
  DIGEST,
  EMPTY_PORTFOLIO,
  LIMITS,
  ME,
  ME_FRESH,
  mockApi,
  PERFORMANCE,
  renderWithProviders,
  REVIEW,
} from "./testUtils";

afterEach(() => vi.restoreAllMocks());

const BASE_ROUTES = {
  "GET /auth/me": () => ({ body: ME }),
  "GET /account": () => ({ body: ACCOUNT }),
  "GET /account/limits": () => ({ body: LIMITS }),
  "GET /portfolio": () => ({ body: EMPTY_PORTFOLIO }),
  "GET /portfolio/performance": () => ({ body: PERFORMANCE }),
  "GET /portfolio/review": () => ({ body: REVIEW }),
  "GET /notifications": () => ({ body: [DIGEST.notification] }),
  "POST /digest/run": () => ({ body: DIGEST }),
  "GET /journal": () => ({
    body: {
      entries: [
        {
          id: "j1",
          entry_type: "note",
          ref_id: "p1",
          payload: { event: "onboarding", profile: "balanced" },
          created_at: "2026-07-09T09:00:00+00:00",
        },
      ],
      nudges: [{ kind: "overtrading", severity: "info", message: "4 of 5 weekly trades used." }],
    },
  }),
  "GET /suggestions": () => ({ body: { suggestions: [] } }),
  "GET /quotes/AAPL": () => ({
    body: {
      symbol: "AAPL",
      price: "210.50",
      as_of: "2026-07-01T14:30:00+00:00",
      source: "stub",
      is_stale: false,
    },
  }),
};

async function expectNoViolations(container: HTMLElement) {
  const results = await axe(container, { rules: { "color-contrast": { enabled: false } } });
  expect(results).toHaveNoViolations();
}

const SCREENS: Array<{ route: string; ready: () => Promise<unknown> }> = [
  { route: "/", ready: () => screen.findByText(/Today's read/) },
  { route: "/portfolio", ready: () => screen.findByText(/Honest review/) },
  { route: "/journal", ready: () => screen.findByText(/append-only/) },
  { route: "/learn", ready: () => screen.findByText("Glossary") },
  { route: "/settings", ready: () => screen.findByLabelText(/Max single position/) },
  { route: "/agent", ready: () => screen.findByText(/Not\s+investment advice/) },
];

for (const { route, ready } of SCREENS) {
  test(`screen ${route} has no axe violations`, async () => {
    mockApi(BASE_ROUTES);
    const { container } = renderWithProviders(<AuthedApp />, { route });
    await ready();
    await expectNoViolations(container);
  }, 30000);
}

test("onboarding wizard has no axe violations", async () => {
  mockApi({
    "GET /auth/me": () => ({ body: ME_FRESH }),
    "GET /onboarding": () => ({ body: { onboarded: false, profiles: {} } }),
  });
  const { container } = renderWithProviders(<AuthedApp />);
  await screen.findByText("Three quick questions");
  await expectNoViolations(container);
}, 30000);
