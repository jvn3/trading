import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { App } from "./App";

afterEach(() => {
  vi.restoreAllMocks();
});

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

// S0.1 acceptance: the app renders and surfaces the backend's paper-mode health once loaded.
test("renders health from the backend", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ status: "ok", version: "0.0.1", trading_mode: "paper" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );

  renderApp();

  expect(screen.getByRole("heading", { name: "AlphaDash" })).toBeInTheDocument();
  expect(await screen.findByText(/mode:/)).toHaveTextContent("paper");
});
