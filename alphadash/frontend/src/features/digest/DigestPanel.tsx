import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link } from "react-router-dom";

import { api } from "../../lib/api";
import { money } from "../../lib/format";
import { Card } from "../../ui/Card";
import { SourceChip } from "../../ui/SourceChip";
import { Term } from "../../ui/Term";
import { color, font, space } from "../../ui/tokens";

// S3.2: today's digest on Home. Generation is idempotent per day server-side, so fetching via
// POST /digest/run on mount is safe — a scheduler hitting the same endpoint wins the same digest.

type DigestPayload = {
  date: string;
  read: Array<{
    title: string;
    source: string;
    published_at: string;
    symbols: string[];
    url: string | null;
  }>;
  what_changed: {
    equity: string;
    cash: string;
    fills_24h: Array<{ symbol: string; side: string; qty: string; price: string }>;
    risk_events_24h: Array<{ event_type: string }>;
  };
  suggestions: Array<{ id: string; headline: string }>;
  disclaimer: string;
};

export function DigestPanel() {
  const queryClient = useQueryClient();
  const digest = useQuery({ queryKey: ["digest"], queryFn: api.runDigest });

  // A freshly created digest is also a new notification — refresh the bell.
  const created = digest.data?.created;
  useEffect(() => {
    if (created) queryClient.invalidateQueries({ queryKey: ["notifications"] });
  }, [created, queryClient]);

  if (digest.isLoading) {
    return (
      <Card>
        <p style={{ margin: 0, color: color.textMuted }}>
          Putting together today's read — checking your portfolio, recent news and any open
          suggestions…
        </p>
      </Card>
    );
  }
  if (digest.isError || !digest.data) {
    return (
      <Card>
        <p role="alert" style={{ margin: 0 }}>
          Couldn't load today's digest. The rest of the app still works — try again in a moment.
        </p>
      </Card>
    );
  }

  const payload = digest.data.notification.payload as DigestPayload;
  const changed = payload.what_changed;

  return (
    <Card>
      <h3 style={{ margin: `0 0 ${space.sm}px`, fontSize: font.sizeLg }}>
        Today's read · {payload.date}
      </h3>

      {payload.read.length === 0 ? (
        <p style={{ margin: `0 0 ${space.md}px`, color: color.textMuted }}>
          No fresh market notes yet today. Run the agent from the Agent tab to pull in the latest
          evidence — or enjoy the quiet; no news is a fine reason to do nothing.
        </p>
      ) : (
        <ul style={{ margin: `0 0 ${space.md}px`, paddingLeft: space.lg, lineHeight: 1.8 }}>
          {payload.read.map((item) => (
            <li key={item.title}>
              {item.title}{" "}
              <SourceChip source={item.source} asOf={item.published_at} />
            </li>
          ))}
        </ul>
      )}

      <h4 style={{ margin: `0 0 ${space.xs}px`, fontSize: font.sizeMd }}>What changed</h4>
      <p style={{ margin: `0 0 ${space.md}px` }}>
        Portfolio value <strong>{money(changed.equity)}</strong> · cash {money(changed.cash)} ·{" "}
        {changed.fills_24h.length === 0
          ? "no trades in the last 24h."
          : `${changed.fills_24h.length} trade(s) in the last 24h.`}
        {changed.risk_events_24h.length > 0 &&
          ` Your safety rules stepped in ${changed.risk_events_24h.length} time(s).`}
      </p>

      <h4 style={{ margin: `0 0 ${space.xs}px`, fontSize: font.sizeMd }}>Open suggestions</h4>
      {payload.suggestions.length === 0 ? (
        <p style={{ margin: 0, color: color.textMuted }}>
          None right now. The agent proposes at most 3 at a time, each with evidence and{" "}
          <Term k="confidence" /> — <Link to="/agent" style={{ color: color.primary }}>ask for fresh ones</Link>.
        </p>
      ) : (
        <ul style={{ margin: 0, paddingLeft: space.lg, lineHeight: 1.8 }}>
          {payload.suggestions.map((s) => (
            <li key={s.id}>
              <Link to="/agent" style={{ color: color.primary }}>
                {s.headline}
              </Link>
            </li>
          ))}
        </ul>
      )}

      <p style={{ margin: `${space.md}px 0 0`, color: color.textMuted, fontSize: font.sizeSm }}>
        {payload.disclaimer}
      </p>
    </Card>
  );
}
