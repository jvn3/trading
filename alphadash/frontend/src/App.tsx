import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { Shell } from "./app/Shell";
import { AuthScreen } from "./features/auth/AuthScreen";
import { PortfolioScreen } from "./features/portfolio/PortfolioScreen";
import { api, ApiError } from "./lib/api";
import { AgentScreen } from "./screens/AgentScreen";
import { HomeScreen } from "./screens/HomeScreen";
import { LearnScreen } from "./screens/LearnScreen";
import { font } from "./ui/tokens";

// S1.10: auth gate + app shell + routes. Exported without a router so tests can drive it with
// MemoryRouter; the default export wraps BrowserRouter for the real app.

export function AuthedApp() {
  const queryClient = useQueryClient();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: api.me,
    retry: (count, error) => !(error instanceof ApiError && error.status === 401) && count < 2,
  });

  if (me.isLoading) {
    return <main style={{ fontFamily: font.family, padding: 24 }}>Loading…</main>;
  }

  if (me.isError || !me.data) {
    return <AuthScreen onAuthed={() => queryClient.invalidateQueries({ queryKey: ["me"] })} />;
  }

  const logout = async () => {
    await api.logout();
    queryClient.clear();
    queryClient.invalidateQueries({ queryKey: ["me"] });
  };

  return (
    <Routes>
      <Route element={<Shell onLogout={logout} />}>
        <Route index element={<HomeScreen />} />
        <Route path="agent" element={<AgentScreen />} />
        <Route path="portfolio" element={<PortfolioScreen />} />
        <Route path="learn" element={<LearnScreen />} />
      </Route>
    </Routes>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <AuthedApp />
    </BrowserRouter>
  );
}
