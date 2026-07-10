import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, ApiError, type OrderResult, type TradePreview } from "../../lib/api";
import { money } from "../../lib/format";
import { ActionButton } from "../../ui/ActionButton";
import { Card } from "../../ui/Card";
import { SourceChip } from "../../ui/SourceChip";
import { Term } from "../../ui/Term";
import { color, font, radius, space } from "../../ui/tokens";

// S1.12 manual paper order ticket — the Phase 1 exit gate. Quote (with provenance) previews the
// trade, Place order is a two-tap confirm (consequence-scaled), a risk veto renders as a teaching
// panel, and the Idempotency-Key makes accidental double-submits harmless.

const inputStyle = {
  width: "100%",
  boxSizing: "border-box" as const,
  padding: space.sm,
  border: `1px solid ${color.border}`,
  borderRadius: radius.md,
  fontSize: font.sizeMd,
  fontFamily: font.family,
};

const selectStyle = { ...inputStyle, background: color.surface };

function newIdempotencyKey(): string {
  return crypto.randomUUID();
}

export function OrderTicket() {
  const queryClient = useQueryClient();
  const [symbol, setSymbol] = useState("AAPL");
  const [assetClass, setAssetClass] = useState<"equity" | "crypto">("equity");
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [orderType, setOrderType] = useState<"market" | "limit">("market");
  const [qtyInput, setQtyInput] = useState("1");
  const [limitPrice, setLimitPrice] = useState("");
  const [idemKey, setIdemKey] = useState(newIdempotencyKey);
  const [result, setResult] = useState<OrderResult | null>(null);
  const [preview, setPreview] = useState<TradePreview | null>(null);

  // S4.3: check the trade against the risk gate + see the post-trade shape WITHOUT placing it.
  const previewTrade = useMutation({
    mutationFn: () =>
      api.whatIfTrade({ symbol, asset_class: assetClass, side, qty: qtyInput }),
    onSuccess: setPreview,
  });

  const quote = useQuery({
    queryKey: ["quote", symbol],
    queryFn: () => api.quote(symbol),
    enabled: symbol.length > 0,
    staleTime: 30_000,
  });

  const place = useMutation({
    mutationFn: () =>
      api.placeOrder(
        {
          symbol,
          asset_class: assetClass,
          side,
          order_type: orderType,
          qty: qtyInput,
          limit_price: orderType === "limit" ? limitPrice : null,
        },
        idemKey,
      ),
    onSuccess: (data) => {
      setResult(data);
      setIdemKey(newIdempotencyKey()); // next order = new intent = new key
      queryClient.invalidateQueries({ queryKey: ["portfolio"] });
      queryClient.invalidateQueries({ queryKey: ["orders"] });
      queryClient.invalidateQueries({ queryKey: ["performance"] });
    },
  });

  const estCost =
    quote.data && Number(qtyInput) > 0 ? Number(quote.data.price) * Number(qtyInput) : null;
  const placeError = place.error instanceof ApiError ? place.error.detail : place.error?.message;
  const filled = result?.order.status === "filled";
  const rejected = result?.order.status === "rejected";

  return (
    <Card as="section">
      <div style={{ display: "flex", flexDirection: "column", gap: space.md }}>
        <h3 style={{ margin: 0, fontSize: font.sizeLg }}>Place a paper trade</h3>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: space.md }}>
          <label style={{ display: "flex", flexDirection: "column", gap: space.xs }}>
            Symbol
            <input
              style={inputStyle}
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: space.xs }}>
            Asset class
            <select
              style={selectStyle}
              value={assetClass}
              onChange={(e) => setAssetClass(e.target.value as "equity" | "crypto")}
            >
              <option value="equity">Stock</option>
              <option value="crypto">Crypto</option>
            </select>
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: space.xs }}>
            Side
            <select
              style={selectStyle}
              value={side}
              onChange={(e) => setSide(e.target.value as "buy" | "sell")}
            >
              <option value="buy">Buy</option>
              <option value="sell">Sell</option>
            </select>
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: space.xs }}>
            Quantity
            <input
              style={inputStyle}
              inputMode="decimal"
              value={qtyInput}
              onChange={(e) => setQtyInput(e.target.value)}
            />
          </label>
          <div style={{ display: "flex", flexDirection: "column", gap: space.xs }}>
            <label htmlFor="order-type">Order type</label>
            <select
              id="order-type"
              style={selectStyle}
              value={orderType}
              onChange={(e) => setOrderType(e.target.value as "market" | "limit")}
            >
              <option value="market">Market</option>
              <option value="limit">Limit</option>
            </select>
            <span style={{ fontSize: font.sizeSm, color: color.textMuted }}>
              What's a <Term k="market order">market</Term> or{" "}
              <Term k="limit order">limit</Term> order?
            </span>
          </div>
          {orderType === "limit" && (
            <label style={{ display: "flex", flexDirection: "column", gap: space.xs }}>
              Limit price
              <input
                style={inputStyle}
                inputMode="decimal"
                value={limitPrice}
                onChange={(e) => setLimitPrice(e.target.value)}
              />
            </label>
          )}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: space.sm, flexWrap: "wrap" }}>
          {quote.data && (
            <>
              <span>
                Latest price: <strong>{money(quote.data.price)}</strong>
              </span>
              <SourceChip source={quote.data.source} asOf={quote.data.as_of} />
              {estCost != null && (
                <span style={{ color: color.textMuted }}>
                  ≈ {money(String(estCost))} {side === "buy" ? "cost" : "proceeds"} before slippage
                </span>
              )}
            </>
          )}
          {quote.isError && (
            <span style={{ color: color.danger }}>No quote available for {symbol}.</span>
          )}
        </div>

        <div style={{ display: "flex", gap: space.sm, flexWrap: "wrap" }}>
          <ActionButton
            label={previewTrade.isPending ? "Checking…" : "Preview impact"}
            intent="secondary"
            disabled={previewTrade.isPending || Number(qtyInput) <= 0}
            onClick={() => previewTrade.mutate()}
          />
          <ActionButton
            label={place.isPending ? "Placing…" : `${side === "buy" ? "Buy" : "Sell"} ${symbol}`}
            intent="primary"
            confirm
            disabled={place.isPending || !quote.data || Number(qtyInput) <= 0}
            onClick={() => place.mutate()}
          />
        </div>

        {preview && (
          <aside
            role="note"
            aria-label="Trade preview"
            style={{
              background: preview.allowed ? color.info : color.caution,
              color: preview.allowed ? color.infoText : color.cautionText,
              borderRadius: radius.md,
              padding: space.md,
              fontSize: font.sizeSm,
            }}
          >
            {preview.allowed ? (
              <>
                This trade would pass your safety rules. Afterwards: cash{" "}
                {money(preview.cash_after)} ({preview.cash_allocation_after_pct.toFixed(2)}%),{" "}
                {symbol} position {money(preview.position_value_after)} (
                {preview.position_allocation_after_pct.toFixed(2)}% of portfolio). Nothing has
                been placed.
              </>
            ) : (
              <>
                <strong>Your safety rules would block this trade:</strong>
                <ul style={{ margin: `${space.xs}px 0 0`, paddingLeft: space.lg }}>
                  {preview.violations.map((v, i) => (
                    <li key={i}>{v.message}</li>
                  ))}
                </ul>
              </>
            )}
          </aside>
        )}

        {placeError && (
          <p role="alert" style={{ margin: 0, color: color.danger, fontSize: font.sizeSm }}>
            {placeError}
          </p>
        )}

        {filled && result?.order.fill && (
          <aside
            role="status"
            style={{
              background: color.positive,
              color: color.positiveText,
              borderRadius: radius.md,
              padding: space.md,
              fontSize: font.sizeSm,
            }}
          >
            Filled: {result.order.side} {result.order.fill.qty} {result.order.symbol} @{" "}
            {money(result.order.fill.price)} (simulated — includes modeled slippage).
          </aside>
        )}

        {rejected && (
          <aside
            role="note"
            aria-label="Why this was blocked"
            style={{
              background: color.caution,
              color: color.cautionText,
              borderRadius: radius.md,
              padding: space.md,
              fontSize: font.sizeSm,
            }}
          >
            <strong>Not placed — your safety rules stepped in:</strong>
            {result!.violations.length > 0 ? (
              <ul style={{ margin: `${space.xs}px 0 0`, paddingLeft: space.lg }}>
                {result!.violations.map((v, i) => (
                  <li key={i}>{v.message}</li>
                ))}
              </ul>
            ) : (
              <p style={{ margin: `${space.xs}px 0 0` }}>{result!.order.rejected_reason}</p>
            )}
          </aside>
        )}
      </div>
    </Card>
  );
}
