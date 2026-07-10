import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";

import { Shell } from "./app/Shell";
import { AuthScreen } from "./features/auth/AuthScreen";
import { OnboardingWizard } from "./features/onboarding/OnboardingWizard";
import { PortfolioScreen } from "./features/portfolio/PortfolioScreen";
import { api, ApiError } from "./lib/api";
import { AgentScreen } from "./screens/AgentScreen";
import { HomeScreen } from "./screens/HomeScreen";
import { JournalScreen } from "./screens/JournalScreen";
import { LearnScreen } from "./screens/LearnScreen";
import { SettingsScreen } from "./screens/SettingsScreen";
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

  // S3.1: signed in but never interviewed → guided onboarding before anything else.
  if (!me.data.onboarded) {
    return <OnboardingWizard onDone={() => queryClient.invalidateQueries()} />;
  }

  const logout = async () => {
    await api.logout();
    queryClient.clear();
    // Full reload: guarantees zero client state (query cache, zustand, in-flight streams)
    // survives a sign-out — the reloaded app sees 401 and lands on the sign-in screen.
    window.location.assign("/");
  };

  return (
    <Routes>
      <Route element={<Shell onLogout={logout} />}>
        <Route index element={<HomeScreen />} />
        <Route path="agent" element={<AgentScreen />} />
        <Route path="portfolio" element={<PortfolioScreen />} />
        <Route path="journal" element={<JournalScreen />} />
        <Route path="learn" element={<LearnScreen />} />
        <Route path="settings" element={<SettingsScreen />} />
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
