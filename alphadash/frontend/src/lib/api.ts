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
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
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
};
