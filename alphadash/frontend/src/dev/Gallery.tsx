import type { ReactNode } from "react";

import { blockedSuggestion, proposedSuggestion } from "../features/suggestions/fixtures";
import { SuggestionCard } from "../features/suggestions/SuggestionCard";
import { ActionButton } from "../ui/ActionButton";
import { Card } from "../ui/Card";
import { Chip } from "../ui/Chip";
import { ConfidenceBadge } from "../ui/ConfidenceBadge";
import { DefinitionTooltip } from "../ui/DefinitionTooltip";
import { DisclosurePanel } from "../ui/DisclosurePanel";
import { RiskMeter } from "../ui/RiskMeter";
import { SourceChip } from "../ui/SourceChip";
import { font, space } from "../ui/tokens";

// Dev-only gallery (S0.4): every primitive plus the SuggestionCard in proposed and blocked
// states. Not routed in the app shell — mounted manually or imported by tests.

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: space.md }}>
      <h2 style={{ margin: 0, fontSize: font.sizeLg }}>{title}</h2>
      {children}
    </section>
  );
}

const noop = () => undefined;

export function Gallery() {
  return (
    <main
      style={{
        fontFamily: font.family,
        padding: space.xl,
        display: "flex",
        flexDirection: "column",
        gap: space.xl,
        maxWidth: 720,
      }}
    >
      <h1 style={{ margin: 0 }}>AlphaDash UI Gallery</h1>

      <Section title="Card">
        <Card>Padded card content</Card>
        <Card padded={false}>Unpadded card content</Card>
      </Section>

      <Section title="Chip">
        <div style={{ display: "flex", gap: space.sm, flexWrap: "wrap" }}>
          <Chip label="neutral" />
          <Chip label="info" tone="info" />
          <Chip label="positive" tone="positive" />
          <Chip label="caution" tone="caution" icon="⚠" />
        </div>
      </Section>

      <Section title="ConfidenceBadge">
        <div style={{ display: "flex", gap: space.sm, flexWrap: "wrap" }}>
          <ConfidenceBadge value={0.25} basis="single stale source" />
          <ConfidenceBadge value={0.55} basis="two sources, one week old" />
          <ConfidenceBadge value={0.85} basis="three fresh corroborating sources" />
        </div>
      </Section>

      <Section title="SourceChip">
        <div style={{ display: "flex", gap: space.sm, flexWrap: "wrap" }}>
          <SourceChip source="FMP earnings" asOf="2026-07-01T14:30:00Z" />
          <SourceChip source="10-Q filing" asOf="2026-06-28T00:00:00Z" href="https://example.com" />
          <SourceChip source="FRED FEDFUNDS" asOf="2026-07-01T14:30:00Z" onClick={noop} />
        </div>
      </Section>

      <Section title="RiskMeter">
        <div style={{ display: "flex", gap: space.sm, flexWrap: "wrap" }}>
          <RiskMeter level="low" label="Starter position" />
          <RiskMeter level="moderate" label="Growth stock" />
          <RiskMeter level="elevated" label="Concentrated position" />
          <RiskMeter level="high" label="Crypto allocation" />
        </div>
      </Section>

      <Section title="DisclosurePanel">
        <DisclosurePanel summary="Why we think this">
          Progressive disclosure content — closed by default.
        </DisclosurePanel>
        <DisclosurePanel summary="Open by default" defaultOpen>
          Already-open content.
        </DisclosurePanel>
      </Section>

      <Section title="DefinitionTooltip">
        <p style={{ margin: 0 }}>
          Your{" "}
          <DefinitionTooltip
            term="Drawdown"
            definition="How far your portfolio has fallen from its highest point, in percent."
          >
            drawdown
          </DefinitionTooltip>{" "}
          stayed under 5% this month.
        </p>
      </Section>

      <Section title="ActionButton">
        <div style={{ display: "flex", gap: space.sm, flexWrap: "wrap" }}>
          <ActionButton label="Approve" intent="primary" confirm onClick={noop} />
          <ActionButton label="Modify" intent="secondary" onClick={noop} />
          <ActionButton label="Dismiss" intent="subtle" onClick={noop} />
          <ActionButton label="Sell everything" intent="danger" confirm onClick={noop} />
          <ActionButton label="Disabled" intent="primary" disabled onClick={noop} />
        </div>
      </Section>

      <Section title="SuggestionCard — proposed">
        <SuggestionCard
          suggestion={proposedSuggestion}
          onApprove={noop}
          onModify={noop}
          onDismiss={noop}
          onAsk={noop}
        />
      </Section>

      <Section title="SuggestionCard — blocked">
        <SuggestionCard
          suggestion={blockedSuggestion}
          onApprove={noop}
          onModify={noop}
          onDismiss={noop}
          onAsk={noop}
        />
      </Section>
    </main>
  );
}
