"use client";

import { useMemo } from "react";
import type { LoopEvent } from "@/lib/useIncidentStream";

/**
 * Notifications stream — shows which side-effects fired for an incident.
 *
 * Reads the same WebSocket event list the timeline uses, then derives
 * "we sent an email about X" / "we called the on-call about Y" lines
 * by mapping each state transition to the notification it triggers in
 * `backend/app/notifications.py`.
 *
 * Design: same palette + spacing as LiveLogs so the right rail reads
 * as a single connected panel.
 */

type NotificationItem = {
  id: string;
  kind: "email" | "call" | "system";
  title: string;
  subtitle: string;
  time: string;
};

const EMAIL_TRIGGERS: Record<string, { title: string; subtitle: string }> = {
  incident_created: {
    title: "Email · incident received",
    subtitle: "we're on it — replied to oncall@",
  },
  kane_red_confirmed: {
    title: "Email · bug reproduced",
    subtitle: "Kane went red, Kiro is fixing now",
  },
  kane_green: {
    title: "Email · fix verified",
    subtitle: "approve to open the PR",
  },
  pr_opened: {
    title: "Email · PR opened",
    subtitle: "with Kane proof attached",
  },
  escalated: {
    title: "Email · escalated",
    subtitle: "loop could not converge",
  },
};

const VOICE_TRIGGERS = new Set([
  "kane_red_confirmed",
  "kane_green",
  "pr_opened",
  "escalated",
]);

function fmt(seconds: number): string {
  if (seconds < 60) return seconds.toFixed(1) + "s";
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

function deriveNotifications(events: LoopEvent[]): NotificationItem[] {
  const out: NotificationItem[] = [];
  let firstTs: number | null = null;
  let nextId = 0;

  function push(item: Omit<NotificationItem, "id">) {
    out.push({ id: `n${nextId++}`, ...item });
  }

  for (const ev of events) {
    const state = String(ev.state || "");
    const now = Date.now() / 1000;
    if (firstTs === null) firstTs = now;
    const t = fmt(now - firstTs);

    // The backend's notification trigger is keyed off the same event
    // kinds that drive the timeline, so we derive notifications from
    // state transitions instead of re-fetching a separate stream.
    if (ev.event === "state_change") {
      if (state === "INTAKE") {
        push({
          kind: "email",
          title: EMAIL_TRIGGERS.incident_created.title,
          subtitle: EMAIL_TRIGGERS.incident_created.subtitle,
          time: t,
        });
      }
    } else if (ev.event === "kane_result" && ev.passed === false) {
      const k = EMAIL_TRIGGERS.kane_red_confirmed;
      push({ kind: "email", title: k.title, subtitle: k.subtitle, time: t });
      if (VOICE_TRIGGERS.has("kane_red_confirmed")) {
        push({
          kind: "call",
          title: "Call · briefing the on-call",
          subtitle: "agent reads the Kane verdict",
          time: t,
        });
      }
    } else if (ev.event === "awaiting_approval") {
      const k = EMAIL_TRIGGERS.kane_green;
      push({ kind: "email", title: k.title, subtitle: k.subtitle, time: t });
      push({
        kind: "call",
        title: "Call · awaiting your decision",
        subtitle: "say 'ship it' or 'stand down'",
        time: t,
      });
    } else if (ev.event === "pr_opened") {
      const k = EMAIL_TRIGGERS.pr_opened;
      push({ kind: "email", title: k.title, subtitle: k.subtitle, time: t });
      push({
        kind: "call",
        title: "Call · PR is live",
        subtitle: typeof ev.pr_url === "string" ? "link in your email" : "—",
        time: t,
      });
    } else if (ev.event === "escalated") {
      const k = EMAIL_TRIGGERS.escalated;
      push({ kind: "email", title: k.title, subtitle: k.subtitle, time: t });
    }
  }
  return out;
}

function arrowFor(kind: NotificationItem["kind"]): string {
  if (kind === "email") return "✉";
  if (kind === "call") return "☎";
  return "·";
}

function colorFor(kind: NotificationItem["kind"]): string {
  if (kind === "email") return "#ffe4a8";
  if (kind === "call") return "#e85d1a";
  return "rgba(255,255,255,0.4)";
}

export function Notifications({ events }: { events: LoopEvent[] }) {
  const items = useMemo(() => deriveNotifications(events), [events]);

  return (
    <div className="rounded bg-black border border-white/10 p-3">
      <div className="flex items-center justify-between pb-2 mb-2 border-b border-white/10">
        <span className="text-xs text-white">Notifications</span>
        <span className="text-[10px] text-white/40 uppercase tracking-wider">
          email · voice
        </span>
      </div>

      {items.length === 0 ? (
        <p className="text-[11px] text-white/40 leading-snug py-2">
          We&apos;ll send an email and call your on-call as the loop
          progresses.
        </p>
      ) : (
        <ol className="space-y-1.5 text-[11px] leading-snug">
          {items.map((n) => (
            <li
              key={n.id}
              className="flex items-baseline gap-2"
            >
              <span className="text-white/40 shrink-0 font-mono">{n.time}</span>
              <span
                className="shrink-0"
                style={{ color: colorFor(n.kind) }}
              >
                {arrowFor(n.kind)}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-white truncate">{n.title}</span>
                <span className="block text-white/40 truncate text-[10px]">
                  {n.subtitle}
                </span>
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
