import { color, font, radius, space } from "./tokens";

// Frozen contract (S0.4): provenance chip — where a claim came from and when it was true.
export interface SourceChipProps {
  source: string;
  asOf: string; // ISO
  href?: string;
  onClick?: () => void;
}

function formatAsOf(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export function SourceChip({ source, asOf, href, onClick }: SourceChipProps) {
  const label = (
    <>
      <span aria-hidden="true">🔎</span> {source}{" "}
      <span style={{ color: color.textMuted }}>as of {formatAsOf(asOf)}</span>
    </>
  );
  const style = {
    display: "inline-flex",
    alignItems: "center",
    gap: space.xs,
    background: color.surfaceSubtle,
    border: `1px solid ${color.border}`,
    borderRadius: radius.pill,
    padding: `${space.xs}px ${space.sm}px`,
    fontSize: font.sizeSm,
    fontFamily: font.family,
    color: color.text,
    textDecoration: "none",
    cursor: href || onClick ? "pointer" : "default",
  } as const;

  if (href) {
    return (
      <a href={href} target="_blank" rel="noreferrer" onClick={onClick} style={style}>
        {label}
      </a>
    );
  }
  if (onClick) {
    return (
      <button type="button" onClick={onClick} style={{ ...style, borderStyle: "solid" }}>
        {label}
      </button>
    );
  }
  return <span style={style}>{label}</span>;
}
