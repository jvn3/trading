import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";

import { NotificationsBell } from "../../app/NotificationsBell";
import { DIGEST, mockApi, renderWithProviders } from "../../testUtils";
import { DigestPanel } from "./DigestPanel";

afterEach(() => vi.restoreAllMocks());

test("digest renders today's read with provenance, what changed, and open suggestions", async () => {
  mockApi({ "POST /digest/run": () => ({ body: DIGEST }) });
  renderWithProviders(<DigestPanel />);

  expect(await screen.findByText(/Today's read · 2026-07-09/)).toBeInTheDocument();
  expect(screen.getByText("Apple services revenue climbs")).toBeInTheDocument();
  expect(screen.getByText(/stub-news/)).toBeInTheDocument(); // provenance chip
  expect(screen.getByText(/no trades in the last 24h/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Consider a small buy of AAPL" })).toBeInTheDocument();
  expect(screen.getByText(/not investment advice/)).toBeInTheDocument();
});

test("digest teaches when there is nothing to read", async () => {
  const empty = {
    ...DIGEST,
    notification: {
      ...DIGEST.notification,
      payload: { ...DIGEST.notification.payload, read: [], suggestions: [] },
    },
  };
  mockApi({ "POST /digest/run": () => ({ body: empty }) });
  renderWithProviders(<DigestPanel />);

  expect(await screen.findByText(/no news is a fine reason to do nothing/)).toBeInTheDocument();
  expect(screen.getByText(/None right now/)).toBeInTheDocument();
});

test("digest failure shows an alert instead of a spinner forever", async () => {
  mockApi({ "POST /digest/run": () => ({ status: 500, body: { detail: "boom" } }) });
  renderWithProviders(<DigestPanel />);
  expect(await screen.findByRole("alert")).toHaveTextContent(/Couldn't load today's digest/);
});

// --- Notifications bell ---

test("bell shows unread count and marks a notification read on tap", async () => {
  const user = userEvent.setup();
  let readCalled = false;
  mockApi({
    "GET /notifications": () => ({
      body: readCalled
        ? [{ ...DIGEST.notification, read_at: "2026-07-09T10:00:00+00:00" }]
        : [DIGEST.notification],
    }),
    "POST /notifications/n1/read": () => {
      readCalled = true;
      return { body: { ...DIGEST.notification, read_at: "2026-07-09T10:00:00+00:00" } };
    },
  });
  renderWithProviders(<NotificationsBell />);

  const bell = await screen.findByRole("button", { name: "Notifications (1 unread)" });
  await user.click(bell);
  expect(screen.getByText("Your 2026-07-09 digest", { exact: false })).toBeInTheDocument();

  await user.click(screen.getByText("Your 2026-07-09 digest", { exact: false }));
  expect(await screen.findByRole("button", { name: "Notifications" })).toBeInTheDocument();
});

test("bell explains an empty feed", async () => {
  const user = userEvent.setup();
  mockApi({ "GET /notifications": () => ({ body: [] }) });
  renderWithProviders(<NotificationsBell />);
  await user.click(await screen.findByRole("button", { name: "Notifications" }));
  expect(screen.getByText(/daily digest and any behavioral nudges/)).toBeInTheDocument();
});
