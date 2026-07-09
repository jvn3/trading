import { useQuery } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { DisclosurePanel } from "../../ui/DisclosurePanel";
import { SourceChip } from "../../ui/SourceChip";
import { color, font, space } from "../../ui/tokens";

// S2.6 — L3 "show your work": deterministic candidate logic → source data → model metadata.
export function ExplanationTrace({ suggestionId }: { suggestionId: string }) {
  const trace = useQuery({
    queryKey: ["trace", suggestionId],
    queryFn: () => api.suggestionTrace(suggestionId),
  });

  return (
    <DisclosurePanel summary="Show your work (full trace)">
      {trace.isLoading && <p style={{ margin: 0 }}>Loading trace…</p>}
      {trace.isError && (
        <p role="alert" style={{ margin: 0, color: color.danger }}>
          Could not load the trace.
        </p>
      )}
      {trace.data && (
        <div style={{ display: "flex", flexDirection: "column", gap: space.md, fontSize: font.sizeSm }}>
          <section aria-label="Candidate logic">
            <h5 style={{ margin: `0 0 ${space.xs}px` }}>1. Deterministic signal</h5>
            <p style={{ margin: 0, color: color.textMuted }}>
              Rule <code>{trace.data.candidate_ref}</code> fired with these measured values — the
              idea existed before any AI wrote a word:
            </p>
            <ul style={{ margin: `${space.xs}px 0 0`, paddingLeft: space.lg }}>
              {trace.data.signal_features.map((f, i) => (
                <li key={i}>
                  <code>{f.claim}</code>
                </li>
              ))}
            </ul>
          </section>

          <section aria-label="Source data">
            <h5 style={{ margin: `0 0 ${space.xs}px` }}>2. Source data</h5>
            {trace.data.evidence.length === 0 && (
              <p style={{ margin: 0, color: color.textMuted }}>
                No external documents were cited for this one.
              </p>
            )}
            <ul style={{ margin: 0, paddingLeft: space.lg }}>
              {trace.data.evidence.map((e, i) => (
                <li key={i} style={{ marginBottom: space.xs }}>
                  {e.claim} <SourceChip source={e.source} asOf={e.as_of} href={e.ref ?? undefined} />
                </li>
              ))}
            </ul>
            {trace.data.snapshot_as_of && (
              <p style={{ margin: `${space.xs}px 0 0`, color: color.textMuted }}>
                Market snapshot taken {trace.data.snapshot_as_of} (id {trace.data.snapshot_id}) —
                the agent saw nothing newer.
              </p>
            )}
          </section>

          <section aria-label="Model metadata">
            <h5 style={{ margin: `0 0 ${space.xs}px` }}>3. Model &amp; prompt</h5>
            <p style={{ margin: 0, color: color.textMuted }}>
              Explanation written by <code>{trace.data.model_version}</code> under prompt{" "}
              <code>{trace.data.prompt_version}</code>, agent run{" "}
              <code>{trace.data.agent_run_id}</code>. Sizing was computed by the deterministic
              sizing engine, not the model.
            </p>
            {trace.data.risk_events.length > 0 && (
              <p style={{ margin: `${space.xs}px 0 0`, color: color.cautionText }}>
                Risk layer events: {trace.data.risk_events.map((e) => e.event_type).join(", ")}
              </p>
            )}
          </section>
        </div>
      )}
    </DisclosurePanel>
  );
}
