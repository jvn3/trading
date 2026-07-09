import type { CSSProperties } from "react";

import { color, font, radius, space } from "./tokens";

// Frozen contract (S0.4): text + icon, never color-only.
export interface RiskMeterProps {
  level: "low" | "moderate" | "elevated" | "high";
  label: string;
}

const LEVELS: Record<RiskMeterProps["level"], { style: CSSProperties; icon: string; text: string }> =
  {
    low: { style: { background: color.positive, color: color.positiveText }, icon: "▁", text: "Low risk" },
    moderate: { style: { background: color.info, color: color.infoText }, icon: "▃", text: "Moderate risk" },
    elevated: { style: { background: color.caution, color: color.cautionText }, icon: "▅", text: "Elevated risk" },
    high: { style: { background: color.dangerSubtle, color: color.danger }, icon: "▇", text: "High risk" },
  };

export function RiskMeter({ level, label }: RiskMeterProps) {
  const info = LEVELS[level];
  return (
    <span
      role="img"
      aria-label={`${label}: ${info.text}`}
      style={{
        ...info.style,
        display: "inline-flex",
        alignItems: "center",
        gap: space.xs,
        borderRadius: radius.sm,
        padding: `${space.xs}px ${space.sm}px`,
        fontSize: font.sizeSm,
        fontFamily: font.family,
        fontWeight: 600,
      }}
    >
      <span aria-hidden="true">{info.icon}</span>
      {info.text} — {label}
    </span>
  );
}
