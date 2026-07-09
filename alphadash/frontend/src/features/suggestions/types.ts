// FROZEN CONTRACT — S0.4 Suggestion view-model.
// This is the presentation contract the backend (S2.4) MUST produce, byte for byte.
// All monetary/quantity fields are strings (Decimal over the wire — never JS number).
// Changing anything here ripples to backend S2.4 — treat it as a shared contract.

export interface EvidenceItem {
  claim: string;
  source: string;
  asOf: string;
  ref?: string;
}

export interface ProposedOrder {
  symbol: string;
  side: "buy" | "sell";
  qty: string;
  orderType: "market" | "limit";
  limitPrice?: string;
  cashImpact: string;
  allocationAfterPct: number;
}

export type SuggestionStatus =
  | "proposed"
  | "approved"
  | "modified"
  | "dismissed"
  | "expired"
  | "blocked";

export interface Suggestion {
  id: string;
  headline: string; // L1
  rationale: string; // L1, <= 3 sentences
  confidence: number; // 0..1
  confidenceBasis: string;
  evidence: EvidenceItem[]; // L2
  proposedOrder: ProposedOrder; // L2
  worstCase: string; // L2
  falsifier: string; // "what would change our mind"
  reversibility: string;
  status: SuggestionStatus;
  blockedReason?: string; // present iff status === 'blocked' (risk-layer veto)
}
