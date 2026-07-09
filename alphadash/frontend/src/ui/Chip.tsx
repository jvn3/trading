import type { CSSProperties, ReactNode } from "react";

import { color, font, radius, space } from "./tokens";

// Frozen contract (S0.4):
export interface ChipProps {
  label: string;
  tone?: "neutral" | "info" | "positive" | "caution";
  icon?: ReactNode;
}

const TONES: Record<NonNullable<ChipProps["tone"]>, CSSProperties> = {
  neutral: { background: color.surfaceSubtle, color: color.text },
  info: { background: color.info, color: color.infoText },
  positive: { background: color.positive, color: color.positiveText },
  caution: { background: color.caution, color: color.cautionText },
};

export function Chip({ label, tone = "neutral", icon }: ChipProps) {
  return (
    <span
      style={{
        ...TONES[tone],
        display: "inline-flex",
        alignItems: "center",
        gap: space.xs,
        borderRadius: radius.pill,
        padding: `${space.xs}px ${space.sm}px`,
        fontSize: font.sizeSm,
        fontFamily: font.family,
      }}
    >
      {icon != null && <span aria-hidden="true">{icon}</span>}
      {label}
    </span>
  );
}
