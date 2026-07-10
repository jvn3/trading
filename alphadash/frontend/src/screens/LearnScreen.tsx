import { GLOSSARY } from "../lib/glossary";
import { Card } from "../ui/Card";
import { DefinitionTooltip } from "../ui/DefinitionTooltip";
import { color, font, space } from "../ui/tokens";

// S3.3: the full glossary lives here; the same definitions appear inline across the app via
// <Term>. One source of truth (lib/glossary.ts), everywhere a tap away.

export function LearnScreen() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.lg }}>
      <h2 style={{ margin: 0 }}>Learn</h2>
      <Card>
        <p style={{ margin: 0 }}>
          A few ideas this app is built on. Tap any{" "}
          <DefinitionTooltip
            term="Underlined term"
            definition="Words like this open a plain-English definition wherever they appear in the app."
          >
            underlined term
          </DefinitionTooltip>{" "}
          to see what it means — here and anywhere else it shows up.
        </p>
      </Card>
      <Card>
        <h3 style={{ margin: `0 0 ${space.sm}px`, fontSize: font.sizeLg }}>Glossary</h3>
        <dl style={{ margin: 0 }} aria-label="Glossary">
          {Object.entries(GLOSSARY).map(([term, definition]) => (
            <div key={term} style={{ marginBottom: space.md }}>
              <dt style={{ fontWeight: 700, textTransform: "capitalize" }}>{term}</dt>
              <dd style={{ margin: 0, color: color.textMuted }}>{definition}</dd>
            </div>
          ))}
        </dl>
      </Card>
      <p style={{ margin: 0, color: color.textMuted, fontSize: font.sizeSm }}>
        Education, not advice. Everything here applies to your simulated paper account.
      </p>
    </div>
  );
}
