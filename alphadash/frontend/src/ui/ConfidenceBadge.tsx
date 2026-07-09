import type { CSSProperties } from "react";

import { color, font, radius, space } from "./tokens";

// Frozen contract (S0.4): renders band Low/Med/High + numeric + icon — never color-only.
export interface ConfidenceBadgeProps {
  value: number; // 0..1
  basis?: string;
}

export type ConfidenceBand = "Low" | "Medium" | "High";

// Band thresholds (frozen for tests): value < 0.4 → Low, < 0.7 → Medium, else High.
export function confidenceBand(value: number): ConfidenceBand {
  if (value < 0.4) return "Low";
  if (value < 0.7) return "Medium";
  return "High";
}

const BAND_STYLE: Record<ConfidenceBand, CSSProperties> = {
  Low: { background: color.caution, color: color.cautionText },
  Medium: { background: color.info, color: color.infoText },
  High: { background: color.positive, color: color.positiveText },
};

const BAND_ICON: Record<ConfidenceBand, string> = { Low: "◔", Medium: "◑", High: "◕" };

export function ConfidenceBadge({ value, basis }: ConfidenceBadgeProps) {
  const band = confidenceBand(value);
  const pct = Math.round(value * 100);
  return (
    <span
      role="status"
      aria-label={`Confidence: ${band}, ${pct} percent${basis ? `. Based on ${basis}` : ""}`}
      title={basis}
      style={{
        ...BAND_STYLE[band],
        display: "inline-flex",
        alignItems: "center",
        gap: space.xs,
        borderRadius: radius.pill,
        padding: `${space.xs}px ${space.sm}px`,
        fontSize: font.sizeSm,
        fontFamily: font.family,
        fontWeight: 600,
      }}
    >
      <span aria-hidden="true">{BAND_ICON[band]}</span>
      {band} confidence · {pct}%
    </span>
  );
}
