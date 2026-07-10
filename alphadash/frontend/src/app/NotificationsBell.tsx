import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../lib/api";
import { color, font, radius, space } from "../ui/tokens";

// S3.2: header notification feed. Badge shows the unread count; the panel lists digests and
// nudges; tapping an item marks it read.

export function NotificationsBell() {
  const [open, setOpen] = useState(false);
  const queryClient = useQueryClient();
  const notifications = useQuery({
    queryKey: ["notifications"],
    queryFn: () => api.notifications(),
  });

  const markRead = useMutation({
    mutationFn: (id: string) => api.markNotificationRead(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });

  const items = notifications.data ?? [];
  const unread = items.filter((n) => !n.read_at).length;

  return (
    <span style={{ position: "relative" }}>
      <button
        type="button"
        aria-label={`Notifications${unread ? ` (${unread} unread)` : ""}`}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        style={{
          background: "none",
          border: `1px solid ${color.border}`,
          borderRadius: radius.md,
          cursor: "pointer",
          fontSize: font.sizeMd,
          padding: `${space.xs}px ${space.sm}px`,
        }}
      >
        <span aria-hidden="true">🔔</span>
        {unread > 0 && (
          <strong style={{ marginLeft: 4, color: color.danger }}>{unread}</strong>
        )}
      </button>
      {open && (
        <div
          role="region"
          aria-label="Notification list"
          style={{
            position: "absolute",
            right: 0,
            top: "110%",
            zIndex: 20,
            width: 320,
            maxHeight: 400,
            overflowY: "auto",
            background: color.surface,
            border: `1px solid ${color.border}`,
            borderRadius: radius.md,
            boxShadow: "0 4px 12px rgba(0,0,0,0.12)",
            padding: space.sm,
          }}
        >
          {items.length === 0 && (
            <p style={{ margin: space.sm, color: color.textMuted, fontSize: font.sizeSm }}>
              Nothing yet. Your daily digest and any behavioral nudges will land here.
            </p>
          )}
          {items.map((n) => (
            <button
              key={n.id}
              type="button"
              onClick={() => !n.read_at && markRead.mutate(n.id)}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                background: n.read_at ? "none" : color.info,
                border: "none",
                borderBottom: `1px solid ${color.border}`,
                borderRadius: radius.sm,
                cursor: "pointer",
                fontFamily: font.family,
                padding: space.sm,
              }}
            >
              <strong style={{ display: "block", fontSize: font.sizeSm }}>
                {n.title}
                {!n.read_at && <span aria-label="unread"> •</span>}
              </strong>
              <span style={{ fontSize: font.sizeSm, color: color.textMuted }}>{n.body}</span>
            </button>
          ))}
        </div>
      )}
    </span>
  );
}
