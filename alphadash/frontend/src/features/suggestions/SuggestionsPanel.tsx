import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, ApiError, type SuggestionDecision } from "../../lib/api";
import { money } from "../../lib/format";
import { ActionButton } from "../../ui/ActionButton";
import { Card } from "../../ui/Card";
import { color, font, radius, space } from "../../ui/tokens";
import { ExplanationTrace } from "./ExplanationTrace";
import { SuggestionCard } from "./SuggestionCard";

// S2.5 — SuggestionCards wired to live data. Approve/Modify/Dismiss hit the decisions API;
// approve executes through the paper engine (risk gate re-checked server-side).

function DecisionBanner({ result }: { result: SuggestionDecision }) {
  if (result.order && result.order.status === "filled") {
    return (
      <aside
        role="status"
        aria-label="Execution result"
        style={{
          background: color.positive, color: color.positiveText,
          borderRadius: radius.md, padding: space.md, fontSize: font.sizeSm,
        }}
      >
        Executed: {result.order.side} {result.order.fill?.qty} {result.order.symbol} @{" "}
        {money(result.order.fill?.price)} (simulated fill).
      </aside>
    );
  }
  if (result.violations.length > 0) {
    return (
      <aside
        role="note"
        aria-label="Execution blocked"
        style={{
          background: color.caution, color: color.cautionText,
          borderRadius: radius.md, padding: space.md, fontSize: font.sizeSm,
        }}
      >
        <strong>Not executed — your safety rules stepped in:</strong>
        <ul style={{ margin: `${space.xs}px 0 0`, paddingLeft: space.lg }}>
          {result.violations.map((v, i) => (
            <li key={i}>{v.message}</li>
          ))}
        </ul>
      </aside>
    );
  }
  return null;
}

export function SuggestionsPanel() {
  const queryClient = useQueryClient();
  const [lastDecision, setLastDecision] = useState<SuggestionDecision | null>(null);
  const [modifyFor, setModifyFor] = useState<string | null>(null);
  const [modifyQty, setModifyQty] = useState("");

  const suggestions = useQuery({
    queryKey: ["suggestions"],
    queryFn: () => api.suggestions().then((r) => r.suggestions),
  });

  const invalidate = (result: SuggestionDecision) => {
    setLastDecision(result);
    setModifyFor(null);
    queryClient.invalidateQueries({ queryKey: ["suggestions"] });
    queryClient.invalidateQueries({ queryKey: ["portfolio"] });
    queryClient.invalidateQueries({ queryKey: ["orders"] });
  };

  const runAgent = useMutation({
    mutationFn: api.runAgent,
    onSuccess: () => {
      setLastDecision(null);
      queryClient.invalidateQueries({ queryKey: ["suggestions"] });
    },
  });
  const approve = useMutation({ mutationFn: api.approveSuggestion, onSuccess: invalidate });
  const dismiss = useMutation({
    mutationFn: (id: string) => api.dismissSuggestion(id),
    onSuccess: invalidate,
  });
  const modify = useMutation({
    mutationFn: ({ id, qty }: { id: string; qty: string }) => api.modifySuggestion(id, qty),
    onSuccess: invalidate,
  });

  const active = (suggestions.data ?? []).filter((s) =>
    ["proposed", "blocked"].includes(s.status),
  );
  const decided = (suggestions.data ?? []).filter(
    (s) => !["proposed", "blocked"].includes(s.status),
  );
  const mutationError = [runAgent, approve, dismiss, modify]
    .map((m) => m.error)
    .find(Boolean);

  return (
    <section aria-label="Agent suggestions" style={{ display: "flex", flexDirection: "column", gap: space.lg }}>
      <div style={{ display: "flex", alignItems: "center", gap: space.md }}>
        <h3 style={{ margin: 0, fontSize: font.sizeLg }}>Today's suggestions</h3>
        <ActionButton
          label={runAgent.isPending ? "Thinking…" : "Get fresh suggestions"}
          intent="secondary"
          disabled={runAgent.isPending}
          onClick={() => runAgent.mutate()}
        />
      </div>

      {mutationError && (
        <p role="alert" style={{ margin: 0, color: color.danger, fontSize: font.sizeSm }}>
          {mutationError instanceof ApiError ? mutationError.detail : String(mutationError)}
        </p>
      )}
      {lastDecision && <DecisionBanner result={lastDecision} />}

      {suggestions.isLoading && <p>Loading suggestions…</p>}
      {suggestions.data && active.length === 0 && (
        <Card>
          <p style={{ margin: 0, color: color.textMuted }}>
            No open suggestions right now. The agent proposes at most 3 ideas at a time — and
            "no good ideas today" is a perfectly good answer. Run it to check again.
          </p>
        </Card>
      )}

      {active.map((s) => (
        <div key={s.id} style={{ display: "flex", flexDirection: "column", gap: space.sm }}>
          <SuggestionCard
            suggestion={s}
            onApprove={(id) => approve.mutate(id)}
            onModify={(id) => {
              setModifyFor(modifyFor === id ? null : id);
              setModifyQty(s.proposedOrder.qty);
            }}
            onDismiss={(id) => dismiss.mutate(id)}
            onAsk={() => {
              document.getElementById("chat-input")?.focus();
            }}
          />
          {modifyFor === s.id && (
            <Card>
              <div style={{ display: "flex", gap: space.sm, alignItems: "flex-end" }}>
                <label style={{ display: "flex", flexDirection: "column", gap: space.xs, fontSize: font.sizeSm }}>
                  New quantity
                  <input
                    aria-label="Modified quantity"
                    style={{
                      padding: space.sm, border: `1px solid ${color.border}`,
                      borderRadius: radius.md, fontFamily: font.family,
                    }}
                    inputMode="decimal"
                    value={modifyQty}
                    onChange={(e) => setModifyQty(e.target.value)}
                  />
                </label>
                <ActionButton
                  label="Execute modified"
                  intent="primary"
                  confirm
                  disabled={modify.isPending || Number(modifyQty) <= 0}
                  onClick={() => modify.mutate({ id: s.id, qty: modifyQty })}
                />
              </div>
            </Card>
          )}
          <ExplanationTrace suggestionId={s.id} />
        </div>
      ))}

      {decided.length > 0 && (
        <Card>
          <h4 style={{ margin: `0 0 ${space.sm}px`, fontSize: font.sizeMd }}>Recent decisions</h4>
          <ul style={{ margin: 0, paddingLeft: space.lg, fontSize: font.sizeSm, color: color.textMuted }}>
            {decided.slice(0, 5).map((s) => (
              <li key={s.id}>
                {s.status}: {s.headline}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </section>
  );
}
