import type { Suggestion } from "./types";

// Deterministic fixtures shared by the Gallery and tests. Mirrors the backend stub's anchor date.

export const proposedSuggestion: Suggestion = {
  id: "sug-proposed-1",
  headline: "Consider a small starter position in AAPL",
  rationale:
    "Apple's earnings beat expectations and services revenue keeps growing. This would be a small, easily reversible first step. It fits inside your balanced risk profile.",
  confidence: 0.62,
  confidenceBasis: "2 corroborating sources; earnings 6 days old",
  evidence: [
    {
      claim: "Q3 EPS of $1.64 beat consensus of $1.57",
      source: "FMP earnings",
      asOf: "2026-07-01T14:30:00Z",
      ref: "https://example.com/earnings",
    },
    {
      claim: "Services revenue grew 12% year over year",
      source: "10-Q filing",
      asOf: "2026-06-28T00:00:00Z",
    },
  ],
  proposedOrder: {
    symbol: "AAPL",
    side: "buy",
    qty: "2",
    orderType: "limit",
    limitPrice: "210.00",
    cashImpact: "-420.00",
    allocationAfterPct: 4.2,
  },
  worstCase:
    "If AAPL drops 10%, this position would lose about $42 — around 0.4% of your portfolio.",
  falsifier: "Services growth slowing below 8%, or a guidance cut next quarter.",
  reversibility: "High — liquid stock, can be sold any market day.",
  status: "proposed",
};

export const blockedSuggestion: Suggestion = {
  ...proposedSuggestion,
  id: "sug-blocked-1",
  headline: "Add to your BTC position",
  status: "blocked",
  blockedReason:
    "This would push crypto to 32% of your portfolio, above your 25% asset-class limit. Concentration is how beginners get hurt — the limit exists for exactly this moment.",
  proposedOrder: {
    symbol: "BTCUSD",
    side: "buy",
    qty: "0.01",
    orderType: "market",
    cashImpact: "-672.50",
    allocationAfterPct: 32,
  },
};
