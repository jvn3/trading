import { useQuery } from "@tanstack/react-query";

import { api } from "./lib/api";

// S0.1 placeholder screen: proves the React + Query + backend wiring end to end. The real app
// shell (nav, routing, safety indicator) arrives in S1.10.
export function App() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
  });

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: 24 }}>
      <h1>AlphaDash</h1>
      <p>Beginner strategy-agent product — paper trading first.</p>
      {isLoading && <p>Checking backend…</p>}
      {isError && <p>Backend unreachable. Is the API running on :8000?</p>}
      {data && (
        <p>
          Backend <strong>{data.status}</strong> · v{data.version} · mode:{" "}
          <strong>{data.trading_mode}</strong>
        </p>
      )}
    </main>
  );
}
