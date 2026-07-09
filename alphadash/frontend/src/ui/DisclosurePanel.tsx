import type { ReactNode } from "react";
import { useId, useState } from "react";

import { color, font, radius, space } from "./tokens";

// Frozen contract (S0.4): THE progressive-disclosure primitive (L1 → L2).
export interface DisclosurePanelProps {
  summary: string;
  defaultOpen?: boolean;
  children: ReactNode;
}

export function DisclosurePanel({ summary, defaultOpen = false, children }: DisclosurePanelProps) {
  const [open, setOpen] = useState(defaultOpen);
  const panelId = useId();

  return (
    <div style={{ border: `1px solid ${color.border}`, borderRadius: radius.md }}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          gap: space.sm,
          background: color.surfaceSubtle,
          color: color.text,
          border: "none",
          borderRadius: open ? `${radius.md}px ${radius.md}px 0 0` : radius.md,
          padding: `${space.sm}px ${space.md}px`,
          fontSize: font.sizeMd,
          fontFamily: font.family,
          fontWeight: 600,
          cursor: "pointer",
          textAlign: "left",
        }}
      >
        <span aria-hidden="true">{open ? "▾" : "▸"}</span>
        {summary}
      </button>
      {open && (
        <div id={panelId} role="region" aria-label={summary} style={{ padding: space.md }}>
          {children}
        </div>
      )}
    </div>
  );
}
