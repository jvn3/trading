import { Card } from "../ui/Card";
import { color, font, space } from "../ui/tokens";

export function AgentScreen() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.lg }}>
      <h2 style={{ margin: 0 }}>Agent</h2>
      <Card>
        <p style={{ margin: 0 }}>
          Your strategy agent lives here from Phase 2: 0–3 explained suggestions per day, each with
          evidence, a confidence band, the worst case, and what would change its mind.
        </p>
        <p style={{ margin: `${space.md}px 0 0`, color: color.textMuted, fontSize: font.sizeSm }}>
          The safety spine you're using now (risk limits, veto, journal, reconciliation) is exactly
          what the agent will be forced through — the AI proposes, the risk layer vetoes, you
          decide.
        </p>
      </Card>
    </div>
  );
}
