import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { axe } from "vitest-axe";

import { Gallery } from "../dev/Gallery";
import { ActionButton } from "./ActionButton";
import { confidenceBand, ConfidenceBadge } from "./ConfidenceBadge";
import { DefinitionTooltip } from "./DefinitionTooltip";
import { DisclosurePanel } from "./DisclosurePanel";
import { RiskMeter } from "./RiskMeter";

// --- ConfidenceBadge band thresholds (frozen: <0.4 Low, <0.7 Medium, else High) ---

test("confidenceBand thresholds", () => {
  expect(confidenceBand(0)).toBe("Low");
  expect(confidenceBand(0.39)).toBe("Low");
  expect(confidenceBand(0.4)).toBe("Medium");
  expect(confidenceBand(0.69)).toBe("Medium");
  expect(confidenceBand(0.7)).toBe("High");
  expect(confidenceBand(1)).toBe("High");
});

test("ConfidenceBadge shows band + numeric, never color-only", () => {
  render(<ConfidenceBadge value={0.62} basis="two sources" />);
  const badge = screen.getByRole("status");
  expect(badge).toHaveTextContent("Medium confidence · 62%");
  expect(badge).toHaveAccessibleName(/Confidence: Medium, 62 percent/);
});

test("RiskMeter conveys level as text, not color alone", () => {
  render(<RiskMeter level="elevated" label="Concentrated position" />);
  expect(screen.getByRole("img")).toHaveAccessibleName(
    "Concentrated position: Elevated risk",
  );
});

// --- DisclosurePanel open/close ---

test("DisclosurePanel opens and closes via its summary button", async () => {
  const user = userEvent.setup();
  render(<DisclosurePanel summary="Details">Hidden content</DisclosurePanel>);

  const toggle = screen.getByRole("button", { name: /Details/ });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByText("Hidden content")).not.toBeInTheDocument();

  await user.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByText("Hidden content")).toBeInTheDocument();

  await user.click(toggle);
  expect(screen.queryByText("Hidden content")).not.toBeInTheDocument();
});

test("DisclosurePanel respects defaultOpen", () => {
  render(
    <DisclosurePanel summary="Open" defaultOpen>
      Visible content
    </DisclosurePanel>,
  );
  expect(screen.getByText("Visible content")).toBeInTheDocument();
});

// --- DefinitionTooltip ---

test("DefinitionTooltip reveals the definition on tap", async () => {
  const user = userEvent.setup();
  render(
    <DefinitionTooltip term="Drawdown" definition="Fall from the peak.">
      drawdown
    </DefinitionTooltip>,
  );
  expect(screen.queryByRole("note")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "drawdown" }));
  expect(screen.getByRole("note")).toHaveTextContent("Drawdown: Fall from the peak.");
});

// --- ActionButton ---

test("ActionButton fires onClick; confirm variant requires a second tap", async () => {
  const user = userEvent.setup();
  const plain = vi.fn();
  const risky = vi.fn();
  render(
    <>
      <ActionButton label="Modify" intent="secondary" onClick={plain} />
      <ActionButton label="Approve" intent="primary" confirm onClick={risky} />
    </>,
  );

  await user.click(screen.getByRole("button", { name: "Modify" }));
  expect(plain).toHaveBeenCalledTimes(1);

  await user.click(screen.getByRole("button", { name: "Approve" }));
  expect(risky).not.toHaveBeenCalled(); // armed, not fired
  await user.click(screen.getByRole("button", { name: "Confirm Approve?" }));
  expect(risky).toHaveBeenCalledTimes(1);
});

test("ActionButton disabled never fires", async () => {
  const user = userEvent.setup();
  const fn = vi.fn();
  render(<ActionButton label="Approve" intent="primary" disabled onClick={fn} />);
  await user.click(screen.getByRole("button", { name: "Approve" }));
  expect(fn).not.toHaveBeenCalled();
});

// --- Accessibility: the whole gallery (every primitive + both card states) passes axe ---

test("Gallery has no axe violations", async () => {
  const { container } = render(<Gallery />);
  // color-contrast needs a real rendering engine; jsdom has no canvas, so axe can't compute it.
  const results = await axe(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(results).toHaveNoViolations();
}, 30000);
