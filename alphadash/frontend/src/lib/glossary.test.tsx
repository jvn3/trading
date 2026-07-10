import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";

import { Term } from "../ui/Term";
import { GLOSSARY } from "./glossary";

test("every glossary definition is substantial plain language", () => {
  for (const [term, definition] of Object.entries(GLOSSARY)) {
    expect(term.length, term).toBeGreaterThan(2);
    expect(definition.length, term).toBeGreaterThan(30); // no lazy one-worders
    expect(definition, term).not.toMatch(/TODO|TBD/i);
  }
});

test("Term renders a tappable definition from the glossary", async () => {
  const user = userEvent.setup();
  render(<Term k="drawdown" />);

  await user.click(screen.getByRole("button", { name: "drawdown" }));
  expect(screen.getByRole("note")).toHaveTextContent(/fallen from its highest point/);
});

test("Term supports custom child text while keeping the canonical definition", async () => {
  const user = userEvent.setup();
  render(<Term k="benchmark">SPY</Term>);
  await user.click(screen.getByRole("button", { name: "SPY" }));
  expect(screen.getByRole("note")).toHaveTextContent(/S&P 500/);
});
