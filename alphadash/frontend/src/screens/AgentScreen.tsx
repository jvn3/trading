import { Link } from "react-router-dom";

import { ChatPanel } from "../features/chat/ChatPanel";
import { SuggestionsPanel } from "../features/suggestions/SuggestionsPanel";
import { color, font, space } from "../ui/tokens";

// Phase 2: live agent — suggestions with evidence + veto teaching (S2.5/S2.6) and grounded,
// cited chat (S2.8). The AI proposes; the risk layer vetoes; the human disposes.
// S4.2 adds the Strategy Lab: user-authored rules that feed this same pipeline.
export function AgentScreen() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.xl }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: space.md }}>
        <h2 style={{ margin: 0 }}>Agent</h2>
        <Link to="/strategies" style={{ color: color.primary, fontSize: font.sizeSm }}>
          Strategy Lab →
        </Link>
      </div>
      <SuggestionsPanel />
      <ChatPanel />
      <p style={{ margin: 0, color: color.textMuted, fontSize: font.sizeSm }}>
        Suggestions are simulated paper trades generated from deterministic signals and explained
        by an AI. Every one passes your risk limits before you see an Approve button. Not
        investment advice.
      </p>
    </div>
  );
}
