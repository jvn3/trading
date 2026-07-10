import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, ApiError, type LimitsUpdateRequest } from "../lib/api";
import { ActionButton } from "../ui/ActionButton";
import { Card } from "../ui/Card";
import { Chip } from "../ui/Chip";
import { Term } from "../ui/Term";
import { color, font, radius, space } from "../ui/tokens";

// S3.6 settings: the six safety limits, persistently displayed and editable. Every trade is
// checked against these by code (S1.3) — editing them is editing what the risk layer enforces.
// The kill switch lives in the always-visible header (S1.10); this screen explains it.

const FIELD_LABELS: Array<{
  key: keyof Omit<LimitsUpdateRequest, "max_asset_class_pct" | "max_trades_per_week">;
  label: string;
  help: string;
}> = [
  {
    key: "max_position_pct",
    label: "Max single position (% of portfolio)",
    help: "No one idea gets to sink the ship.",
  },
  {
    key: "cash_floor_pct",
    label: "Cash floor (%)",
    help: "The share of your portfolio always kept in cash.",
  },
  {
    key: "per_suggestion_max_pct",
    label: "Max per trade (% of portfolio)",
    help: "Caps how big any single suggested trade can be.",
  },
  {
    key: "drawdown_pause_pct",
    label: "Auto-pause at drawdown (%)",
    help: "Buying stops automatically when your portfolio falls this far from its peak.",
  },
];

function numberInput(props: {
  id: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <input
      id={props.id}
      inputMode="decimal"
      value={props.value}
      onChange={(e) => props.onChange(e.target.value)}
      style={{
        border: `1px solid ${color.border}`,
        borderRadius: radius.sm,
        fontFamily: font.family,
        fontSize: font.sizeMd,
        padding: space.sm,
        width: 110,
      }}
    />
  );
}

export function SettingsScreen() {
  const queryClient = useQueryClient();
  const limits = useQuery({ queryKey: ["limits"], queryFn: api.limits });
  const account = useQuery({ queryKey: ["account"], queryFn: api.account });

  const [form, setForm] = useState<LimitsUpdateRequest | null>(null);
  useEffect(() => {
    if (limits.data && form === null) {
      const d = limits.data;
      setForm({
        max_position_pct: d.max_position_pct ?? "10",
        max_asset_class_pct: {
          equity: d.max_asset_class_pct["equity"] ?? "80",
          crypto: d.max_asset_class_pct["crypto"] ?? "10",
        },
        max_trades_per_week: d.max_trades_per_week ?? 5,
        cash_floor_pct: d.cash_floor_pct ?? "10",
        per_suggestion_max_pct: d.per_suggestion_max_pct ?? "5",
        drawdown_pause_pct: d.drawdown_pause_pct ?? "15",
      });
    }
  }, [limits.data, form]);

  const save = useMutation({
    mutationFn: (body: LimitsUpdateRequest) => api.updateLimits(body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["limits"] }),
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.lg }}>
      <h2 style={{ margin: 0 }}>Settings</h2>

      <Card>
        <h3 style={{ margin: `0 0 ${space.sm}px`, fontSize: font.sizeLg }}>Pause everything</h3>
        <p style={{ margin: 0 }}>
          The <strong>{account.data?.paused ? "Resume" : "Pause all"}</strong> button in the
          header is your kill switch: one tap (plus a confirm) halts all new buying — the agent
          stops proposing buys and the risk layer vetoes any buy order until you resume. Sells
          stay allowed, so you are never trapped in a position.
          {account.data?.paused && (
            <>
              {" "}
              <Chip label="Currently paused" tone="caution" icon="⏸" />
            </>
          )}
        </p>
      </Card>

      <Card>
        <h3 style={{ margin: `0 0 ${space.sm}px`, fontSize: font.sizeLg }}>Your safety rules</h3>
        <p style={{ margin: `0 0 ${space.md}px`, color: color.textMuted, fontSize: font.sizeSm }}>
          Enforced by code on every trade — including the agent's. Edit with intention:{" "}
          <Term k="position sizing" /> limits are what keep one mistake small.
        </p>

        {limits.isLoading && <p>Loading your limits…</p>}
        {limits.isError && <p role="alert">Could not load limits.</p>}

        {form && (
          <div style={{ display: "flex", flexDirection: "column", gap: space.md }}>
            {FIELD_LABELS.map((f) => (
              <div key={f.key} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <label htmlFor={`limit-${f.key}`} style={{ fontWeight: 600 }}>
                  {f.label}
                </label>
                <span style={{ color: color.textMuted, fontSize: font.sizeSm }}>{f.help}</span>
                {numberInput({
                  id: `limit-${f.key}`,
                  value: String(form[f.key]),
                  onChange: (v) => setForm({ ...form, [f.key]: v }),
                })}
              </div>
            ))}

            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <label htmlFor="limit-trades" style={{ fontWeight: 600 }}>
                Max trades per week
              </label>
              <span style={{ color: color.textMuted, fontSize: font.sizeSm }}>
                Churn protection. More activity rarely means better results.
              </span>
              <input
                id="limit-trades"
                inputMode="numeric"
                value={String(form.max_trades_per_week)}
                onChange={(e) =>
                  setForm({ ...form, max_trades_per_week: Number(e.target.value) || 0 })
                }
                style={{
                  border: `1px solid ${color.border}`,
                  borderRadius: radius.sm,
                  fontFamily: font.family,
                  fontSize: font.sizeMd,
                  padding: space.sm,
                  width: 110,
                }}
              />
            </div>

            <div style={{ display: "flex", gap: space.lg, flexWrap: "wrap" }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <label htmlFor="limit-equity" style={{ fontWeight: 600 }}>
                  Max in stocks (%)
                </label>
                {numberInput({
                  id: "limit-equity",
                  value: form.max_asset_class_pct["equity"],
                  onChange: (v) =>
                    setForm({
                      ...form,
                      max_asset_class_pct: { ...form.max_asset_class_pct, equity: v },
                    }),
                })}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <label htmlFor="limit-crypto" style={{ fontWeight: 600 }}>
                  Max in crypto (%)
                </label>
                {numberInput({
                  id: "limit-crypto",
                  value: form.max_asset_class_pct["crypto"],
                  onChange: (v) =>
                    setForm({
                      ...form,
                      max_asset_class_pct: { ...form.max_asset_class_pct, crypto: v },
                    }),
                })}
              </div>
            </div>

            {save.isError && (
              <p role="alert" style={{ margin: 0, color: color.danger }}>
                {save.error instanceof ApiError
                  ? save.error.detail
                  : "Could not save your limits."}
              </p>
            )}
            {save.isSuccess && (
              <div role="status">
                <p style={{ margin: 0 }}>
                  Saved. Your profile is now <strong>{save.data.profile}</strong>.
                </p>
                {save.data.loosened.length > 0 && (
                  <p style={{ margin: `${space.xs}px 0 0`, color: color.cautionText }}>
                    Heads up: you loosened {save.data.loosened.join(", ")}. More room means
                    bigger swings — make sure that's a decision, not a mood.
                  </p>
                )}
              </div>
            )}

            <div>
              <ActionButton
                label="Save safety rules"
                intent="primary"
                confirm
                disabled={save.isPending}
                onClick={() => save.mutate(form)}
              />
            </div>
          </div>
        )}
      </Card>

      <p style={{ margin: 0, color: color.textMuted, fontSize: font.sizeSm }}>
        Paper account — simulated money. Limits apply to every order, human or agent. Not
        investment advice.
      </p>
    </div>
  );
}
