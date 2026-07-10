import { useQuery } from "@tanstack/react-query";

import { api, type JournalEntry, type Nudge } from "../lib/api";
import { Card } from "../ui/Card";
import { Chip } from "../ui/Chip";
import { color, font, space } from "../ui/tokens";

// S3.4 decision journal: the append-only audit trail, rendered as a human timeline, with
// behavioral nudges (overtrading / loss-chasing) on top. Nudges teach; the risk layer blocks.

function describe(entry: JournalEntry): string {
  const p = entry.payload as Record<string, unknown>;
  switch (entry.entry_type) {
    case "decision": {
      const action = String(p.action ?? "decided");
      const reason = p.reason ? ` — "${String(p.reason)}"` : "";
      return `You ${action === "dismiss" ? "dismissed" : `chose to ${action}`} a suggestion${reason}`;
    }
    case "suggestion":
      return `The agent proposed: ${String(p.headline ?? "a trade idea")}`;
    case "order": {
      const event = String(p.event ?? "");
      if (event === "rejected") return `Order rejected: ${String(p.reason ?? "")}`;
      return `Order ${event || "recorded"}: ${String(p.side ?? "")} ${String(p.qty ?? "")} ${String(p.symbol ?? "")}`;
    }
    case "fill":
      return `Trade executed: ${String(p.side ?? "")} ${String(p.qty ?? "")} ${String(p.symbol ?? "")} @ ${String(p.price ?? "")}`;
    case "risk_event": {
      if (p.event === "pause" || p.event === "resume") {
        return p.event === "pause" ? "You paused all trading" : "You resumed trading";
      }
      return "Your safety rules stepped in";
    }
    case "note": {
      if (p.event === "onboarding") return `Onboarding set your profile to ${String(p.profile)}`;
      if (p.event === "limits_updated") {
        const loosened = (p.loosened as string[] | undefined) ?? [];
        return loosened.length
          ? `You edited your safety rules (loosened: ${loosened.join(", ")})`
          : "You edited your safety rules";
      }
      return "Note";
    }
    default:
      return entry.entry_type;
  }
}

const TONE: Record<string, "caution" | "info"> = { warn: "caution", info: "info" };

function NudgeBanner({ nudge }: { nudge: Nudge }) {
  return (
    <Card>
      <div style={{ display: "flex", gap: space.sm, alignItems: "flex-start" }}>
        <Chip
          label={nudge.kind === "overtrading" ? "Trading a lot" : "Chasing losses?"}
          tone={TONE[nudge.severity] ?? "info"}
          icon="⚠"
        />
        <p style={{ margin: 0 }}>{nudge.message}</p>
      </div>
    </Card>
  );
}

export function JournalScreen() {
  const journal = useQuery({ queryKey: ["journal"], queryFn: () => api.journal() });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.lg }}>
      <h2 style={{ margin: 0 }}>Journal</h2>
      <p style={{ margin: 0, color: color.textMuted, fontSize: font.sizeSm }}>
        Every suggestion, decision, trade and safety event — append-only, nothing can be edited
        or deleted. Your track record, honestly kept.
      </p>

      {journal.isLoading && <p>Loading your journal…</p>}
      {journal.isError && <p role="alert">Could not load the journal. Try again in a moment.</p>}

      {journal.data?.nudges.map((nudge) => (
        <NudgeBanner key={nudge.kind} nudge={nudge} />
      ))}

      {journal.data && journal.data.entries.length === 0 && (
        <Card>
          <p style={{ margin: 0, color: color.textMuted }}>
            Nothing here yet. Your first decision — approving, modifying or dismissing a
            suggestion, or placing a trade — starts the record.
          </p>
        </Card>
      )}

      {journal.data && journal.data.entries.length > 0 && (
        <Card padded={false}>
          <ol
            aria-label="Journal timeline"
            style={{ listStyle: "none", margin: 0, padding: 0 }}
          >
            {journal.data.entries.map((entry) => (
              <li
                key={entry.id}
                style={{
                  borderBottom: `1px solid ${color.border}`,
                  display: "flex",
                  flexDirection: "column",
                  gap: 2,
                  padding: space.md,
                }}
              >
                <span style={{ fontSize: font.sizeSm, color: color.textMuted }}>
                  {new Date(entry.created_at).toLocaleString()} · {entry.entry_type}
                </span>
                <span>{describe(entry)}</span>
              </li>
            ))}
          </ol>
        </Card>
      )}

      <p style={{ margin: 0, color: color.textMuted, fontSize: font.sizeSm }}>
        Paper account — simulated decisions, real habits. Not investment advice.
      </p>
    </div>
  );
}
