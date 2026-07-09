import type { CSSProperties } from "react";
import { useState } from "react";

import { color, font, radius, space } from "./tokens";

// Frozen contract (S0.4). `confirm` = two-tap arm/confirm — confirmation scales with consequence.
export interface ActionButtonProps {
  label: string;
  intent: "primary" | "secondary" | "subtle" | "danger";
  onClick: () => void;
  disabled?: boolean;
  confirm?: boolean;
}

const INTENTS: Record<ActionButtonProps["intent"], CSSProperties> = {
  primary: { background: color.primary, color: "#ffffff", border: `1px solid ${color.primary}` },
  secondary: {
    background: color.surface,
    color: color.primary,
    border: `1px solid ${color.primary}`,
  },
  subtle: { background: "none", color: color.textMuted, border: "1px solid transparent" },
  danger: { background: color.danger, color: "#ffffff", border: `1px solid ${color.danger}` },
};

export function ActionButton({ label, intent, onClick, disabled, confirm }: ActionButtonProps) {
  const [armed, setArmed] = useState(false);

  const handleClick = () => {
    if (confirm && !armed) {
      setArmed(true);
      return;
    }
    setArmed(false);
    onClick();
  };

  return (
    <button
      type="button"
      disabled={disabled}
      onClick={handleClick}
      onBlur={() => setArmed(false)}
      style={{
        ...INTENTS[intent],
        borderRadius: radius.md,
        padding: `${space.sm}px ${space.lg}px`,
        fontSize: font.sizeMd,
        fontFamily: font.family,
        fontWeight: 600,
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1,
      }}
    >
      {armed ? `Confirm ${label}?` : label}
    </button>
  );
}
