import { useRef, useState } from "react";

import { streamChat, type ChatCitation } from "../../lib/api";
import { ActionButton } from "../../ui/ActionButton";
import { Card } from "../../ui/Card";
import { SourceChip } from "../../ui/SourceChip";
import { color, font, radius, space } from "../../ui/tokens";

// S2.8 — streaming chat. Tokens render as they arrive; sources show under each answer.

type Turn = {
  role: "user" | "assistant";
  content: string;
  citations?: ChatCitation[];
  error?: string;
};

export function ChatPanel() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  const send = async () => {
    const message = input.trim();
    if (!message || busy) return;
    setInput("");
    setBusy(true);

    const history = turns
      .filter((t) => !t.error)
      .map((t) => ({ role: t.role, content: t.content }));
    setTurns((prev) => [...prev, { role: "user", content: message }, { role: "assistant", content: "" }]);

    const patchLast = (patch: (t: Turn) => Turn) =>
      setTurns((prev) => [...prev.slice(0, -1), patch(prev[prev.length - 1])]);

    try {
      await streamChat(message, history, (event) => {
        if (event.type === "token") {
          patchLast((t) => ({ ...t, content: t.content + event.text }));
        } else if (event.type === "sources") {
          patchLast((t) => ({ ...t, citations: event.citations }));
        } else if (event.type === "error") {
          patchLast((t) => ({ ...t, error: event.message }));
        }
        listRef.current?.scrollTo?.({ top: listRef.current.scrollHeight });
      });
    } catch (e) {
      patchLast((t) => ({ ...t, error: e instanceof Error ? e.message : String(e) }));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card as="section">
      <div style={{ display: "flex", flexDirection: "column", gap: space.md }}>
        <h3 style={{ margin: 0, fontSize: font.sizeLg }}>Ask about your portfolio</h3>
        <p style={{ margin: 0, fontSize: font.sizeSm, color: color.textMuted }}>
          Grounded in your paper account and cited market evidence. Educational — never advice.
        </p>

        <div
          ref={listRef}
          role="log"
          aria-live="polite"
          aria-label="Chat messages"
          style={{ display: "flex", flexDirection: "column", gap: space.sm, maxHeight: 360, overflowY: "auto" }}
        >
          {turns.map((turn, i) => (
            <div
              key={i}
              style={{
                alignSelf: turn.role === "user" ? "flex-end" : "flex-start",
                maxWidth: "85%",
                background: turn.role === "user" ? color.info : color.surfaceSubtle,
                color: turn.role === "user" ? color.infoText : color.text,
                borderRadius: radius.md,
                padding: `${space.sm}px ${space.md}px`,
                fontSize: font.sizeMd,
                whiteSpace: "pre-wrap",
              }}
            >
              {turn.content || (turn.role === "assistant" && !turn.error ? "…" : "")}
              {turn.error && (
                <span role="alert" style={{ color: color.danger, display: "block" }}>
                  {turn.error}
                </span>
              )}
              {turn.citations && turn.citations.length > 0 && (
                <span
                  style={{ display: "flex", gap: space.xs, flexWrap: "wrap", marginTop: space.sm }}
                  aria-label="Sources"
                >
                  {turn.citations.map((c, j) => (
                    <SourceChip
                      key={j}
                      source={`[${j + 1}] ${c.source}`}
                      asOf={c.published_at}
                      href={c.url ?? undefined}
                    />
                  ))}
                </span>
              )}
            </div>
          ))}
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            void send();
          }}
          style={{ display: "flex", gap: space.sm }}
        >
          <input
            id="chat-input"
            aria-label="Chat message"
            placeholder='Try "should I buy AAPL?" — you’ll get education, not orders'
            value={input}
            onChange={(e) => setInput(e.target.value)}
            style={{
              flex: 1, padding: space.sm, border: `1px solid ${color.border}`,
              borderRadius: radius.md, fontSize: font.sizeMd, fontFamily: font.family,
            }}
          />
          <ActionButton
            label={busy ? "Answering…" : "Send"}
            intent="primary"
            disabled={busy || input.trim().length === 0}
            onClick={() => void send()}
          />
        </form>
      </div>
    </Card>
  );
}
