import { Card } from "../ui/Card";
import { DefinitionTooltip } from "../ui/DefinitionTooltip";
import { space } from "../ui/tokens";

export function LearnScreen() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.lg }}>
      <h2 style={{ margin: 0 }}>Learn</h2>
      <Card>
        <p style={{ margin: 0 }}>
          A few ideas this app is built on. Tap any{" "}
          <DefinitionTooltip
            term="Underlined term"
            definition="Words like this open a plain-English definition wherever they appear."
          >
            underlined term
          </DefinitionTooltip>{" "}
          to see what it means.
        </p>
        <ul style={{ marginBottom: 0, paddingLeft: space.lg, lineHeight: 1.8 }}>
          <li>
            <DefinitionTooltip
              term="Drawdown"
              definition="How far your portfolio has fallen from its highest point, in percent. The number that tells you what losing feels like."
            >
              Drawdown
            </DefinitionTooltip>{" "}
            matters more than returns when you're learning.
          </li>
          <li>
            <DefinitionTooltip
              term="Benchmark"
              definition="A simple comparison like SPY (the S&P 500). If a strategy doesn't beat just buying the benchmark, the extra effort wasn't paying you."
            >
              Benchmark
            </DefinitionTooltip>{" "}
            — returns shown alone are marketing, not information.
          </li>
          <li>
            <DefinitionTooltip
              term="Position sizing"
              definition="How much of your money goes into one idea. Sizing, not stock picking, is what keeps one mistake from mattering too much."
            >
              Position sizing
            </DefinitionTooltip>{" "}
            is the main thing your risk limits control.
          </li>
        </ul>
      </Card>
    </div>
  );
}
