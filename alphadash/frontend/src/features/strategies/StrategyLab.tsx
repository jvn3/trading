import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, ApiError, type Backtest, type Strategy } from "../../lib/api";
import { pct } from "../../lib/format";
import { ActionButton } from "../../ui/ActionButton";
import { Card } from "../../ui/Card";
import { Chip } from "../../ui/Chip";
import { Term } from "../../ui/Term";
import { color, font, radius, space } from "../../ui/tokens";

// S4.2 Strategy Lab: plain-language idea → compiled deterministic rules (shown back before
// anything runs) → walk-forward backtest → activate. Active strategies only ever FEED the
// suggestion pipeline — every trade still needs your approval and passes the risk gate.

const th = {
  textAlign: "left" as const,
  padding: `${space.xs}px ${space.sm}px`,
  fontSize: font.sizeSm,
  color: color.textMuted,
  borderBottom: `1px solid ${color.border}`,
};
const td = { padding: `${space.xs}px ${space.sm}px`, fontSize: font.sizeSm };

function BacktestPanel({ results }: { results: Backtest }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.sm }}>
      <p style={{ margin: 0 }}>
        Over {results.days} days: strategy <strong>{pct(results.total_return_pct, true)}</strong>{" "}
        · just holding the symbol {pct(results.buy_hold_return_pct, true)} ·{" "}
        <Term k="benchmark">SPY</Term> {pct(results.benchmark_return_pct, true)} · max{" "}
        <Term k="drawdown" /> {pct(results.max_drawdown_pct)} · {results.closed_trades} closed
        trade(s)
        {results.win_rate_pct != null && <> · <Term k="win rate" /> {pct(results.win_rate_pct)}</>}
      </p>
      <table style={{ borderCollapse: "collapse" }}>
        <caption style={{ textAlign: "left", fontSize: font.sizeSm, fontWeight: 700 }}>
          Walk-forward windows ({results.windows_beating_buy_hold} of {results.windows.length}{" "}
          beat buy &amp; hold)
        </caption>
        <thead>
          <tr>
            <th style={th}>Window</th>
            <th style={th}>Strategy</th>
            <th style={th}>Buy &amp; hold</th>
            <th style={th}>Trades</th>
          </tr>
        </thead>
        <tbody>
          {results.windows.map((w) => (
            <tr key={w.start}>
              <td style={td}>
                {w.start} → {w.end}
              </td>
              <td style={td}>{pct(w.strategy_return_pct, true)}</td>
              <td style={td}>{pct(w.buy_hold_return_pct, true)}</td>
              <td style={td}>{w.trades}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {results.caveats.map((c) => (
        <p key={c} style={{ margin: 0, color: color.textMuted, fontSize: font.sizeSm }}>
          {c}
        </p>
      ))}
    </div>
  );
}

const STATUS_TONE = { draft: "neutral", active: "positive", archived: "neutral" } as const;

function StrategyCard({ strategy }: { strategy: Strategy }) {
  const queryClient = useQueryClient();
  const [backtest, setBacktest] = useState<Backtest | null>(null);
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["strategies"] });

  const runBacktest = useMutation({
    mutationFn: () => api.backtestStrategy(strategy.id),
    onSuccess: (data) => {
      setBacktest(data);
      invalidate();
    },
  });
  const activate = useMutation({
    mutationFn: () => api.activateStrategy(strategy.id),
    onSuccess: invalidate,
  });
  const archive = useMutation({
    mutationFn: () => api.archiveStrategy(strategy.id),
    onSuccess: invalidate,
  });
  const actionError = [runBacktest, activate, archive]
    .map((m) => (m.error instanceof ApiError ? m.error.detail : m.error?.message))
    .find(Boolean);

  const shown = backtest ?? (strategy.last_backtest as Backtest | null);

  return (
    <Card as="article">
      <div style={{ display: "flex", alignItems: "center", gap: space.sm, flexWrap: "wrap" }}>
        <h3 style={{ margin: 0, fontSize: font.sizeLg }}>{strategy.name}</h3>
        <Chip
          label={strategy.status}
          tone={STATUS_TONE[strategy.status as keyof typeof STATUS_TONE] ?? "neutral"}
        />
      </div>
      <p style={{ margin: `${space.sm}px 0 0`, color: color.textMuted, fontSize: font.sizeSm }}>
        You said: “{strategy.source_text}”
      </p>
      <p style={{ margin: `${space.sm}px 0` }}>
        <strong>The rules, exactly as code will run them:</strong> {strategy.description}
      </p>

      {shown && <BacktestPanel results={shown} />}

      {actionError && (
        <p role="alert" style={{ margin: `${space.sm}px 0 0`, color: color.danger }}>
          {actionError}
        </p>
      )}

      <div style={{ display: "flex", gap: space.sm, marginTop: space.md, flexWrap: "wrap" }}>
        <ActionButton
          label={runBacktest.isPending ? "Backtesting…" : "Run backtest"}
          intent="secondary"
          disabled={runBacktest.isPending}
          onClick={() => runBacktest.mutate()}
        />
        {strategy.status === "draft" && (
          <ActionButton
            label="Activate"
            intent="primary"
            confirm
            disabled={activate.isPending || !shown}
            onClick={() => activate.mutate()}
          />
        )}
        {strategy.status !== "archived" && (
          <ActionButton
            label="Archive"
            intent="subtle"
            disabled={archive.isPending}
            onClick={() => archive.mutate()}
          />
        )}
      </div>
    </Card>
  );
}

export function StrategyLab() {
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const strategies = useQuery({ queryKey: ["strategies"], queryFn: api.strategies });

  const draft = useMutation({
    mutationFn: () => api.draftStrategy(text),
    onSuccess: () => {
      setText("");
      queryClient.invalidateQueries({ queryKey: ["strategies"] });
    },
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.lg }}>
      <h2 style={{ margin: 0 }}>Strategy Lab</h2>
      <Card>
        <p style={{ margin: `0 0 ${space.sm}px` }}>
          Describe a simple rule in plain language. It gets compiled into exact, deterministic
          rules — shown back to you word for word — then backtested before it can go live. An
          active strategy only <em>suggests</em>; you still approve every trade, and your safety
          limits still apply.
        </p>
        <label htmlFor="strategy-text" style={{ fontWeight: 600 }}>
          Your strategy idea
        </label>
        <textarea
          id="strategy-text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={3}
          placeholder="e.g. Buy AAPL when the price is above its 20 day average, sell at 10% profit or 5% loss"
          style={{
            width: "100%",
            boxSizing: "border-box",
            border: `1px solid ${color.border}`,
            borderRadius: radius.md,
            fontFamily: font.family,
            fontSize: font.sizeMd,
            marginTop: space.xs,
            padding: space.sm,
          }}
        />
        {draft.isError && (
          <p role="alert" style={{ margin: `${space.sm}px 0 0`, color: color.danger }}>
            {draft.error instanceof ApiError ? draft.error.detail : "Could not draft that."}
          </p>
        )}
        <div style={{ marginTop: space.sm }}>
          <ActionButton
            label={draft.isPending ? "Compiling…" : "Draft strategy"}
            intent="primary"
            disabled={draft.isPending || text.trim().length < 5}
            onClick={() => draft.mutate()}
          />
        </div>
      </Card>

      {strategies.isLoading && <p>Loading your strategies…</p>}
      {strategies.isError && <p role="alert">Could not load strategies.</p>}
      {strategies.data && strategies.data.length === 0 && (
        <Card>
          <p style={{ margin: 0, color: color.textMuted }}>
            No strategies yet. Start with something simple — trend-following and dip-buying are
            the classics — and let the backtest tell you the honest news.
          </p>
        </Card>
      )}
      {strategies.data?.map((s) => (
        <StrategyCard key={s.id} strategy={s} />
      ))}

      <p style={{ margin: 0, color: color.textMuted, fontSize: font.sizeSm }}>
        Backtests are simulated on end-of-day data with modeled slippage. Paper account — not
        investment advice.
      </p>
    </div>
  );
}
