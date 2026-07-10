import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { api, ApiError, type ShockImpact } from "../../lib/api";
import { money, pct } from "../../lib/format";
import { ActionButton } from "../../ui/ActionButton";
import { Card } from "../../ui/Card";
import { Chip } from "../../ui/Chip";
import { Term } from "../../ui/Term";
import { color, font, radius, space } from "../../ui/tokens";

// S4.3 what-if simulator: preset and custom market shocks applied to YOUR portfolio, in the
// same terms the safety rules use. Read-only — nothing is placed, ever.

const PRESETS = [
  { label: "Stocks −20% (a bad year)", equity: "-20", crypto: "0" },
  { label: "2008-style: stocks −35%", equity: "-35", crypto: "-35" },
  { label: "Crypto winter: −60%", equity: "0", crypto: "-60" },
  { label: "Everything −10%", equity: "-10", crypto: "-10" },
];

export function ScenarioPanel() {
  const [equityPct, setEquityPct] = useState("-20");
  const [cryptoPct, setCryptoPct] = useState("0");
  const [impact, setImpact] = useState<ShockImpact | null>(null);

  const run = useMutation({
    mutationFn: (body: { equity_pct: string; crypto_pct: string }) =>
      api.whatIfShock({ ...body, symbol_overrides: {} }),
    onSuccess: setImpact,
  });

  const inputStyle = {
    border: `1px solid ${color.border}`,
    borderRadius: radius.sm,
    fontFamily: font.family,
    fontSize: font.sizeMd,
    padding: space.sm,
    width: 90,
  };

  return (
    <Card as="section">
      <h3 style={{ margin: `0 0 ${space.sm}px`, fontSize: font.sizeLg }}>
        What if the market moved?
      </h3>
      <p style={{ margin: `0 0 ${space.md}px`, color: color.textMuted, fontSize: font.sizeSm }}>
        Stress-test your portfolio without touching it. Losses only feel abstract until you see
        your own numbers.
      </p>

      <div style={{ display: "flex", gap: space.sm, flexWrap: "wrap", marginBottom: space.md }}>
        {PRESETS.map((preset) => (
          <ActionButton
            key={preset.label}
            label={preset.label}
            intent="secondary"
            disabled={run.isPending}
            onClick={() => {
              setEquityPct(preset.equity);
              setCryptoPct(preset.crypto);
              run.mutate({ equity_pct: preset.equity, crypto_pct: preset.crypto });
            }}
          />
        ))}
      </div>

      <div style={{ display: "flex", gap: space.lg, alignItems: "flex-end", flexWrap: "wrap" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <label htmlFor="shock-equity">Stocks move (%)</label>
          <input
            id="shock-equity"
            inputMode="decimal"
            value={equityPct}
            onChange={(e) => setEquityPct(e.target.value)}
            style={inputStyle}
          />
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <label htmlFor="shock-crypto">Crypto moves (%)</label>
          <input
            id="shock-crypto"
            inputMode="decimal"
            value={cryptoPct}
            onChange={(e) => setCryptoPct(e.target.value)}
            style={inputStyle}
          />
        </div>
        <ActionButton
          label={run.isPending ? "Simulating…" : "Simulate"}
          intent="primary"
          disabled={run.isPending}
          onClick={() => run.mutate({ equity_pct: equityPct, crypto_pct: cryptoPct })}
        />
      </div>

      {run.isError && (
        <p role="alert" style={{ margin: `${space.md}px 0 0`, color: color.danger }}>
          {run.error instanceof ApiError ? run.error.detail : "Simulation failed."}
        </p>
      )}

      {impact && (
        <div role="status" aria-label="Scenario result" style={{ marginTop: space.md }}>
          <p style={{ margin: 0 }}>
            Your portfolio would go from <strong>{money(impact.equity_before)}</strong> to{" "}
            <strong>{money(impact.equity_after)}</strong> ({pct(impact.equity_change_pct, true)}
            ). Cash of {money(impact.cash)} is unaffected — that's what a{" "}
            <Term k="cash floor" /> buys you.
          </p>
          {impact.positions.length > 0 && (
            <ul style={{ margin: `${space.sm}px 0`, paddingLeft: space.lg, lineHeight: 1.7 }}>
              {impact.positions.map((p) => (
                <li key={p.symbol}>
                  {p.symbol}: {money(p.value_before)} → {money(p.value_after)} (
                  {pct(p.applied_pct, true)})
                </li>
              ))}
            </ul>
          )}
          {impact.positions.length === 0 && (
            <p style={{ margin: `${space.sm}px 0`, color: color.textMuted }}>
              You hold no positions yet, so only your cash is at stake — nothing to shock.
            </p>
          )}
          {impact.would_trip_drawdown_pause ? (
            <p style={{ margin: 0 }}>
              <Chip label="Auto-pause would trip" tone="caution" icon="⏸" /> A{" "}
              <Term k="drawdown" /> this size crosses your {impact.drawdown_pause_pct}% pause
              threshold — buying would stop automatically until you resumed.
            </p>
          ) : (
            <p style={{ margin: 0, color: color.textMuted, fontSize: font.sizeSm }}>
              This move stays inside your {impact.drawdown_pause_pct ?? "—"}% auto-pause
              threshold.
            </p>
          )}
        </div>
      )}
    </Card>
  );
}
