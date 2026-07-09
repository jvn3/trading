import type { ReactNode } from "react";
import { useId, useState } from "react";

import { color, font, radius, space } from "./tokens";

// Frozen contract (S0.4): tappable inline definition — first-use glossary terms (S3.3 wires the
// glossary; the primitive is self-contained here).
export interface DefinitionTooltipProps {
  term: string;
  definition: string;
  children: ReactNode;
}

export function DefinitionTooltip({ term, definition, children }: DefinitionTooltipProps) {
  const [open, setOpen] = useState(false);
  const defId = useId();

  return (
    <span style={{ position: "relative", display: "inline-block" }}>
      <button
        type="button"
        aria-expanded={open}
        aria-describedby={open ? defId : undefined}
        onClick={() => setOpen((v) => !v)}
        style={{
          background: "none",
          border: "none",
          borderBottom: `1px dotted ${color.infoText}`,
          color: color.infoText,
          cursor: "help",
          fontSize: "inherit",
          fontFamily: "inherit",
          padding: 0,
        }}
      >
        {children}
      </button>
      {open && (
        <span
          id={defId}
          role="note"
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            zIndex: 10,
            minWidth: 220,
            background: color.surface,
            border: `1px solid ${color.border}`,
            borderRadius: radius.md,
            boxShadow: "0 4px 12px rgba(0,0,0,0.12)",
            padding: space.md,
            fontSize: font.sizeSm,
            fontFamily: font.family,
            color: color.text,
          }}
        >
          <strong>{term}:</strong> {definition}
        </span>
      )}
    </span>
  );
}
