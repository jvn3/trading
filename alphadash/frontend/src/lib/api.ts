// Thin typed API client. Response shapes mirror the backend's frozen contracts; from S1.9 these
// types are generated from the OpenAPI schema rather than hand-written.

export interface Health {
  status: string;
  version: string;
  trading_mode: string;
}

async function getJson<T>(path: string): Promise<T> {
  const resp = await fetch(`/api${path}`);
  if (!resp.ok) {
    throw new Error(`Request failed: ${resp.status}`);
  }
  return (await resp.json()) as T;
}

export const api = {
  health: () => getJson<Health>("/health"),
};
