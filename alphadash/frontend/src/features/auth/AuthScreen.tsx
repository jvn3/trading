import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { api, ApiError } from "../../lib/api";
import { ActionButton } from "../../ui/ActionButton";
import { Card } from "../../ui/Card";
import { Chip } from "../../ui/Chip";
import { color, font, radius, space } from "../../ui/tokens";

// S1.10: sign-in / create-account gate. On success the parent refetches /auth/me.

const inputStyle = {
  width: "100%",
  boxSizing: "border-box" as const,
  padding: space.sm,
  border: `1px solid ${color.border}`,
  borderRadius: radius.md,
  fontSize: font.sizeMd,
  fontFamily: font.family,
};

export function AuthScreen({ onAuthed }: { onAuthed: () => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");

  const submit = useMutation({
    mutationFn: () =>
      mode === "login"
        ? api.login({ email, password })
        : api.register({ email, password, display_name: displayName }),
    onSuccess: onAuthed,
  });

  const error = submit.error instanceof ApiError ? submit.error.detail : submit.error?.message;

  return (
    <main
      style={{
        fontFamily: font.family,
        maxWidth: 420,
        margin: "10vh auto",
        padding: space.lg,
        display: "flex",
        flexDirection: "column",
        gap: space.lg,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: space.sm }}>
        <h1 style={{ margin: 0 }}>AlphaDash</h1>
        <Chip label="PAPER — simulated money" tone="info" />
      </div>
      <Card>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit.mutate();
          }}
          style={{ display: "flex", flexDirection: "column", gap: space.md }}
        >
          <h2 style={{ margin: 0, fontSize: font.sizeLg }}>
            {mode === "login" ? "Sign in" : "Create your account"}
          </h2>
          {mode === "register" && (
            <label style={{ display: "flex", flexDirection: "column", gap: space.xs }}>
              Name
              <input
                style={inputStyle}
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                required
              />
            </label>
          )}
          <label style={{ display: "flex", flexDirection: "column", gap: space.xs }}>
            Email
            <input
              style={inputStyle}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: space.xs }}>
            Password
            <input
              style={inputStyle}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={mode === "register" ? 10 : undefined}
              required
            />
          </label>
          {error && (
            <p role="alert" style={{ margin: 0, color: color.danger, fontSize: font.sizeSm }}>
              {error}
            </p>
          )}
          <ActionButton
            label={
              submit.isPending ? "Working…" : mode === "login" ? "Sign in" : "Create account"
            }
            intent="primary"
            disabled={submit.isPending}
            onClick={() => submit.mutate()}
          />
          <button
            type="button"
            onClick={() => setMode(mode === "login" ? "register" : "login")}
            style={{
              background: "none",
              border: "none",
              color: color.infoText,
              cursor: "pointer",
              fontSize: font.sizeSm,
              fontFamily: font.family,
            }}
          >
            {mode === "login"
              ? "New here? Create an account (paper money, no risk)"
              : "Already have an account? Sign in"}
          </button>
        </form>
      </Card>
      <p style={{ margin: 0, color: color.textMuted, fontSize: font.sizeSm }}>
        Simulated trading only. Nothing here is investment advice.
      </p>
    </main>
  );
}
