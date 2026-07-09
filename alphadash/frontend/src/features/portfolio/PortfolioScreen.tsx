import { useQuery } from "@tanstack/react-query";

import { api } from "../../lib/api";
import { money, pct, qty } from "../../lib/format";
import { Card } from "../../ui/Card";
import { color, font, space } from "../../ui/tokens";
import { OrderTicket } from "../orders/OrderTicket";

// S1.11 portfolio screen: holdings, allocation, and performance — always framed against the
// benchmark and with drawdown visible (honest-performance rule).

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 130 }}>
      <span style={{ fontSize: font.sizeSm, color: color.textMuted }}>{label}</span>
      <strong style={{ fontSize: font.sizeLg }}>{value}</strong>
      {sub && <span style={{ fontSize: font.sizeSm, color: color.textMuted }}>{sub}</span>}
    </div>
  );
}

const th = {
  textAlign: "left" as const,
  padding: `${space.xs}px ${space.sm}px`,
  fontSize: font.sizeSm,
  color: color.textMuted,
  borderBottom: `1px solid ${color.border}`,
};
const td = { padding: `${space.sm}px`, fontSize: font.sizeMd };

export function PortfolioScreen() {
  const portfolio = useQuery({ queryKey: ["portfolio"], queryFn: api.portfolio });
  const performance = useQuery({
    queryKey: ["performance", 90],
    queryFn: () => api.performance(90),
  });

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: space.lg }}>
      <h2 style={{ margin: 0 }}>Portfolio</h2>

      {portfolio.isLoading && <p>Loading your portfolio…</p>}
      {portfolio.isError && <p role="alert">Could not load portfolio. Is the API running?</p>}

      {portfolio.data && (
        <Card>
          <div style={{ display: "flex", gap: space.xl, flexWrap: "wrap" }}>
            <Stat label="Total value (simulated)" value={money(portfolio.data.equity)} />
            <Stat label="Cash" value={money(portfolio.data.cash)} />
            {performance.data && (
              <>
                <Stat
                  label="Your return (90d)"
                  value={pct(performance.data.return_pct, true)}
                  sub={`${performance.data.benchmark_symbol} same period: ${pct(performance.data.benchmark_return_pct, true)}`}
                />
                <Stat
                  label="Max drawdown (90d)"
                  value={pct(performance.data.max_drawdown_pct)}
                  sub={`current: ${pct(performance.data.current_drawdown_pct)}`}
                />
              </>
            )}
          </div>
        </Card>
      )}

      {portfolio.data && (
        <Card>
          <h3 style={{ margin: `0 0 ${space.md}px`, fontSize: font.sizeLg }}>Allocation</h3>
          <div style={{ display: "flex", gap: space.lg, flexWrap: "wrap" }}>
            {Object.entries(portfolio.data.allocation_pct).map(([bucket, share]) => (
              <Stat key={bucket} label={bucket} value={pct(share)} />
            ))}
          </div>
        </Card>
      )}

      {portfolio.data && (
        <Card padded={false}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <caption
              style={{
                textAlign: "left",
                padding: space.md,
                fontSize: font.sizeLg,
                fontWeight: 700,
              }}
            >
              Holdings
            </caption>
            <thead>
              <tr>
                <th style={th}>Symbol</th>
                <th style={th}>Qty</th>
                <th style={th}>Avg cost</th>
                <th style={th}>Value</th>
                <th style={th}>Unrealized P/L</th>
                <th style={th}>% of portfolio</th>
              </tr>
            </thead>
            <tbody>
              {portfolio.data.positions.length === 0 && (
                <tr>
                  <td style={{ ...td, color: color.textMuted }} colSpan={6}>
                    No holdings yet — place your first paper trade below. It's simulated money;
                    this is the safe place to learn.
                  </td>
                </tr>
              )}
              {portfolio.data.positions.map((p) => (
                <tr key={p.symbol} style={{ borderTop: `1px solid ${color.border}` }}>
                  <td style={td}>
                    <strong>{p.symbol}</strong>{" "}
                    <span style={{ color: color.textMuted, fontSize: font.sizeSm }}>
                      {p.asset_class}
                    </span>
                  </td>
                  <td style={td}>{qty(p.quantity)}</td>
                  <td style={td}>{money(p.avg_cost)}</td>
                  <td style={td}>{money(p.market_value)}</td>
                  <td
                    style={{
                      ...td,
                      color: Number(p.unrealized_pl) >= 0 ? color.positiveText : color.danger,
                    }}
                  >
                    {money(p.unrealized_pl)}
                  </td>
                  <td style={td}>{pct(p.allocation_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      <OrderTicket />

      <p style={{ margin: 0, color: color.textMuted, fontSize: font.sizeSm }}>
        Paper account — simulated fills with modeled slippage. Performance always shown against{" "}
        {performance.data?.benchmark_symbol ?? "a benchmark"} with drawdown. Not investment advice.
      </p>
    </div>
  );
}
