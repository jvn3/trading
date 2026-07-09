import { ActionButton } from "../../ui/ActionButton";
import { Card } from "../../ui/Card";
import { Chip } from "../../ui/Chip";
import { ConfidenceBadge } from "../../ui/ConfidenceBadge";
import { DisclosurePanel } from "../../ui/DisclosurePanel";
import { SourceChip } from "../../ui/SourceChip";
import { color, font, space } from "../../ui/tokens";
import type { Suggestion } from "./types";

// S0.4 frozen behavior:
// - L1 always visible: headline, rationale, ConfidenceBadge.
// - L2 inside a DisclosurePanel: evidence (SourceChips + claims), ProposedOrder with cash impact
//   and allocation-after, worstCase, falsifier.
// - Actions are callbacks only — no backend calls in S0.4.
// - Blocked: blockedReason shown as a teaching note, Approve disabled (a veto is educational).
// - L3 (full trace) is S2.6's ExplanationTrace — labelled hook left below.
export interface SuggestionCardProps {
  suggestion: Suggestion;
  onApprove: (id: string) => void;
  onModify: (id: string) => void;
  onDismiss: (id: string) => void;
  onAsk: (id: string) => void;
}

export function SuggestionCard({
  suggestion,
  onApprove,
  onModify,
  onDismiss,
  onAsk,
}: SuggestionCardProps) {
  const s = suggestion;
  const blocked = s.status === "blocked";
  const order = s.proposedOrder;

  return (
    <Card as="article">
      <div style={{ display: "flex", flexDirection: "column", gap: space.md, fontFamily: font.family }}>
        {/* L1 — always visible */}
        <header style={{ display: "flex", flexDirection: "column", gap: space.sm }}>
          <div style={{ display: "flex", gap: space.sm, alignItems: "center", flexWrap: "wrap" }}>
            <Chip label={s.status} tone={blocked ? "caution" : "info"} />
            <ConfidenceBadge value={s.confidence} basis={s.confidenceBasis} />
          </div>
          <h3 style={{ margin: 0, fontSize: font.sizeLg, color: color.text }}>{s.headline}</h3>
          <p style={{ margin: 0, color: color.textMuted, fontSize: font.sizeMd }}>{s.rationale}</p>
        </header>

        {blocked && s.blockedReason && (
          <aside
            role="note"
            aria-label="Why this was blocked"
            style={{
              background: color.caution,
              color: color.cautionText,
              borderRadius: 10,
              padding: space.md,
              fontSize: font.sizeSm,
            }}
          >
            <strong>Blocked by your risk limits — here's the lesson:</strong> {s.blockedReason}
          </aside>
        )}

        {/* L2 — progressive disclosure */}
        <DisclosurePanel summary="Why we think this (evidence & details)">
          <div style={{ display: "flex", flexDirection: "column", gap: space.md }}>
            <section aria-label="Evidence">
              <h4 style={{ margin: `0 0 ${space.sm}px`, fontSize: font.sizeMd }}>Evidence</h4>
              <ul style={{ margin: 0, paddingLeft: space.lg, display: "flex", flexDirection: "column", gap: space.sm }}>
                {s.evidence.map((item, i) => (
                  <li key={i} style={{ fontSize: font.sizeSm, color: color.text }}>
                    {item.claim}{" "}
                    <SourceChip source={item.source} asOf={item.asOf} href={item.ref} />
                  </li>
                ))}
              </ul>
            </section>

            <section aria-label="Proposed order">
              <h4 style={{ margin: `0 0 ${space.sm}px`, fontSize: font.sizeMd }}>Proposed order</h4>
              <dl style={{ margin: 0, fontSize: font.sizeSm, display: "grid", gridTemplateColumns: "auto 1fr", gap: `${space.xs}px ${space.md}px` }}>
                <dt>Action</dt>
                <dd style={{ margin: 0 }}>
                  {order.side} {order.qty} {order.symbol} ({order.orderType}
                  {order.limitPrice ? ` @ ${order.limitPrice}` : ""})
                </dd>
                <dt>Cash impact</dt>
                <dd style={{ margin: 0 }}>{order.cashImpact}</dd>
                <dt>Allocation after</dt>
                <dd style={{ margin: 0 }}>{order.allocationAfterPct}% of portfolio</dd>
              </dl>
            </section>

            <section aria-label="Worst case">
              <h4 style={{ margin: `0 0 ${space.sm}px`, fontSize: font.sizeMd }}>Worst case</h4>
              <p style={{ margin: 0, fontSize: font.sizeSm }}>{s.worstCase}</p>
            </section>

            <section aria-label="What would change our mind">
              <h4 style={{ margin: `0 0 ${space.sm}px`, fontSize: font.sizeMd }}>
                What would change our mind
              </h4>
              <p style={{ margin: 0, fontSize: font.sizeSm }}>{s.falsifier}</p>
              <p style={{ margin: `${space.sm}px 0 0`, fontSize: font.sizeSm, color: color.textMuted }}>
                Reversibility: {s.reversibility}
              </p>
            </section>
          </div>
        </DisclosurePanel>

        {/* L3 hook — ExplanationTrace mounts here in S2.6. Intentionally empty in S0.4. */}
        <div data-slot="explanation-trace" hidden />

        <footer style={{ display: "flex", gap: space.sm, flexWrap: "wrap" }}>
          <ActionButton
            label="Approve"
            intent="primary"
            confirm
            disabled={blocked}
            onClick={() => onApprove(s.id)}
          />
          <ActionButton label="Modify" intent="secondary" onClick={() => onModify(s.id)} />
          <ActionButton label="Dismiss" intent="subtle" onClick={() => onDismiss(s.id)} />
          <ActionButton label="Ask" intent="subtle" onClick={() => onAsk(s.id)} />
        </footer>
      </div>
    </Card>
  );
}
