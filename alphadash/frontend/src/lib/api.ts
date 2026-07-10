// Typed API client (S1.9). All response/request shapes come from the OpenAPI-generated
// `api-types.ts` (npm run gen:api) — never hand-written. Money stays string end to end.

import type { components } from "./api-types";

type Schemas = components["schemas"];
export type Health = { status: string; version: string; trading_mode: string };
export type Me = Schemas["MeResponse"];
export type AccountInfo = Schemas["AccountOut"];
export type Limits = Schemas["LimitsOut"];
export type Portfolio = Schemas["PortfolioOut"];
export type Performance = Schemas["PerformanceOut"];
export type OrderOut = Schemas["OrderOut"];
export type OrderResult = Schemas["OrderResult"];
export type OrderRequest = Schemas["OrderRequest"];
export type Quote = Schemas["QuoteOut"];
export type OnboardingStatus = Schemas["OnboardingStatusOut"];
export type OnboardingRequest = Schemas["OnboardingRequest"];
export type OnboardingResult = Schemas["OnboardingOut"];
export type LimitsUpdateRequest = Schemas["LimitsUpdateRequest"];
export type LimitsUpdateResult = Schemas["LimitsUpdateOut"];
export type Notification = Schemas["NotificationOut"];
export type Digest = Schemas["DigestOut"];
export type Journal = Schemas["JournalOut"];
export type JournalEntry = Schemas["JournalEntryOut"];
export type Nudge = Schemas["NudgeOut"];
export type Review = Schemas["ReviewOut"];
export type Strategy = Schemas["StrategyOut"];
export type Backtest = Schemas["BacktestOut"];
export type ShockRequest = Schemas["ShockRequest"];
export type ShockImpact = Schemas["ShockImpactOut"];
export type TradePreviewRequest = Schemas["TradePreviewRequest"];
export type TradePreview = Schemas["TradePreviewOut"];

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`/api${path}`, {
    credentials: "same-origin",
    ...init,
    // merged AFTER the init spread so callers' extra headers add to (not replace) the defaults
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!resp.ok) {
    let detail = `Request failed: ${resp.status}`;
    try {
      const body = await resp.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // non-JSON error body — keep the generic message
    }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export const api = {
  health: () => request<Health>("/health"),

  // auth
  register: (body: { email: string; password: string; display_name: string }) =>
    request<Me>("/auth/register", { method: "POST", body: JSON.stringify(body) }),
  login: (body: { email: string; password: string }) =>
    request<Me>("/auth/login", { method: "POST", body: JSON.stringify(body) }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  me: () => request<Me>("/auth/me"),

  // account
  account: () => request<AccountInfo>("/account"),
  limits: () => request<Limits>("/account/limits"),
  pause: () => request<AccountInfo>("/account/pause", { method: "POST" }),
  resume: () => request<AccountInfo>("/account/resume", { method: "POST" }),

  // portfolio
  portfolio: () => request<Portfolio>("/portfolio"),
  performance: (days = 90) => request<Performance>(`/portfolio/performance?days=${days}`),

  // orders
  orders: () => request<OrderOut[]>("/orders"),
  placeOrder: (body: OrderRequest, idempotencyKey: string) =>
    request<OrderResult>("/orders", {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Idempotency-Key": idempotencyKey },
    }),

  quote: (symbol: string) => request<Quote>(`/quotes/${encodeURIComponent(symbol)}`),

  // beginner experience (S3.x)
  onboardingStatus: () => request<OnboardingStatus>("/onboarding"),
  completeOnboarding: (body: OnboardingRequest) =>
    request<OnboardingResult>("/onboarding", { method: "POST", body: JSON.stringify(body) }),
  updateLimits: (body: LimitsUpdateRequest) =>
    request<LimitsUpdateResult>("/account/limits", { method: "PUT", body: JSON.stringify(body) }),
  runDigest: () => request<Digest>("/digest/run", { method: "POST" }),
  notifications: (unreadOnly = false) =>
    request<Notification[]>(`/notifications?unread_only=${unreadOnly}`),
  markNotificationRead: (id: string) =>
    request<Notification>(`/notifications/${id}/read`, { method: "POST" }),
  journal: (limit = 50) => request<Journal>(`/journal?limit=${limit}`),
  review: (days = 90) => request<Review>(`/portfolio/review?days=${days}`),

  // strategy lab (S4.2)
  strategies: () => request<Strategy[]>("/strategies"),
  draftStrategy: (text: string) =>
    request<Strategy>("/strategies/draft", { method: "POST", body: JSON.stringify({ text }) }),
  backtestStrategy: (id: string) =>
    request<Backtest>(`/strategies/${id}/backtest`, { method: "POST" }),
  activateStrategy: (id: string) =>
    request<Strategy>(`/strategies/${id}/activate`, { method: "POST" }),
  archiveStrategy: (id: string) =>
    request<Strategy>(`/strategies/${id}/archive`, { method: "POST" }),

  // what-if simulator (S4.3)
  whatIfShock: (body: ShockRequest) =>
    request<ShockImpact>("/whatif/shock", { method: "POST", body: JSON.stringify(body) }),
  whatIfTrade: (body: TradePreviewRequest) =>
    request<TradePreview>("/whatif/trade", { method: "POST", body: JSON.stringify(body) }),

  // agent + suggestions (S2.5/S2.6). Suggestion payloads follow the frozen S0.4 view-model.
  runAgent: () => request<AgentRunResult>("/agent/run", { method: "POST" }),
  suggestions: () => request<{ suggestions: SuggestionView[] }>("/suggestions"),
  approveSuggestion: (id: string) =>
    request<SuggestionDecision>(`/suggestions/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  modifySuggestion: (id: string, qty: string) =>
    request<SuggestionDecision>(`/suggestions/${id}/modify`, {
      method: "POST",
      body: JSON.stringify({ qty }),
    }),
  dismissSuggestion: (id: string, reason?: string) =>
    request<SuggestionDecision>(`/suggestions/${id}/dismiss`, {
      method: "POST",
      body: JSON.stringify({ reason: reason ?? null }),
    }),
  suggestionTrace: (id: string) => request<Trace>(`/suggestions/${id}/trace`),
};

// The suggestions endpoints intentionally serve the frozen S0.4 view-model (untyped in OpenAPI
// because it's a shared cross-layer contract) — typed here against the frontend contract file.
import type { Suggestion as SuggestionContract } from "../features/suggestions/types";

export type SuggestionView = SuggestionContract & { createdAt?: string | null };
export type AgentRunResult = {
  run_id: string;
  status: string;
  suggestions: SuggestionView[];
};
export type SuggestionDecision = {
  suggestion: SuggestionView;
  order: OrderOut | null;
  violations: { limit_type: string | null; message: string }[];
};
export type Trace = {
  suggestion_id: string;
  candidate_ref: string;
  signal_features: { claim: string; source: string; as_of: string }[];
  evidence: { claim: string; source: string; as_of: string; ref?: string | null }[];
  sizing: Record<string, unknown>;
  prompt_version: string;
  model_version: string;
  agent_run_id: string | null;
  snapshot_id: string | null;
  snapshot_as_of: string | null;
  risk_events: { event_type: string; detail: Record<string, unknown> }[];
};

export type ChatEvent =
  | { type: "token"; text: string }
  | { type: "sources"; citations: ChatCitation[] }
  | { type: "error"; message: string }
  | { type: "done" };
export type ChatCitation = {
  doc_id: string;
  title: string;
  source: string;
  url: string | null;
  published_at: string;
};

// Streaming chat (S2.7/S2.8): POST + parse SSE lines off the response body stream.
export async function streamChat(
  message: string,
  history: { role: "user" | "assistant"; content: string }[],
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch("/api/chat", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, history }),
    signal,
  });
  if (!resp.ok || !resp.body) {
    let detail = `Chat failed: ${resp.status}`;
    try {
      const body = await resp.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // keep generic message
    }
    throw new ApiError(resp.status, detail);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (line.startsWith("data: ")) {
        onEvent(JSON.parse(line.slice(6)) as ChatEvent);
      }
    }
  }
}
