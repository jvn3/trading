import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { NavLink, Outlet } from "react-router-dom";

import { api } from "../lib/api";
import { ActionButton } from "../ui/ActionButton";
import { Chip } from "../ui/Chip";
import { color, font, space } from "../ui/tokens";

// S1.10 app shell: persistent safety header (paper badge + kill switch, blueprint §13.1) and
// bottom navigation. Screens render into <Outlet/>.

const NAV = [
  { to: "/", label: "Home", icon: "⌂" },
  { to: "/agent", label: "Agent", icon: "✦" },
  { to: "/portfolio", label: "Portfolio", icon: "▤" },
  { to: "/learn", label: "Learn", icon: "✎" },
];

export function Shell({ onLogout }: { onLogout: () => void }) {
  const queryClient = useQueryClient();
  const account = useQuery({ queryKey: ["account"], queryFn: api.account });
  const paused = account.data?.paused ?? false;

  const togglePause = useMutation({
    mutationFn: () => (paused ? api.resume() : api.pause()),
    onSuccess: (data) => queryClient.setQueryData(["account"], data),
  });

  return (
    <div
      style={{
        fontFamily: font.family,
        color: color.text,
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        maxWidth: 760,
        margin: "0 auto",
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          gap: space.sm,
          padding: `${space.md}px ${space.lg}px`,
          borderBottom: `1px solid ${color.border}`,
          position: "sticky",
          top: 0,
          background: color.surface,
          zIndex: 5,
        }}
      >
        <strong style={{ fontSize: font.sizeLg }}>AlphaDash</strong>
        <Chip label="PAPER — simulated money" tone="info" icon="🛈" />
        {paused && <Chip label="Paused" tone="caution" icon="⏸" />}
        <span style={{ flex: 1 }} />
        <ActionButton
          label={paused ? "Resume" : "Pause all"}
          intent={paused ? "secondary" : "danger"}
          confirm={!paused}
          disabled={togglePause.isPending || account.isLoading}
          onClick={() => togglePause.mutate()}
        />
        <ActionButton label="Sign out" intent="subtle" onClick={onLogout} />
      </header>

      <main style={{ flex: 1, padding: space.lg, paddingBottom: 96 }}>
        <Outlet />
      </main>

      <nav
        aria-label="Primary"
        style={{
          position: "fixed",
          bottom: 0,
          left: 0,
          right: 0,
          display: "flex",
          justifyContent: "center",
          gap: space.xl,
          padding: `${space.sm}px ${space.lg}px`,
          borderTop: `1px solid ${color.border}`,
          background: color.surface,
        }}
      >
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            style={({ isActive }) => ({
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              gap: 2,
              textDecoration: "none",
              fontSize: font.sizeSm,
              fontWeight: isActive ? 700 : 400,
              color: isActive ? color.primary : color.textMuted,
            })}
          >
            <span aria-hidden="true">{item.icon}</span>
            {item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
