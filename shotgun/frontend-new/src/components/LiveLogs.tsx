"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useIncidentStream } from "@/lib/useIncidentStream";

interface LogLine {
  id: number;
  time: string;
  arrow: "→" | "←" | "·" | "✓" | "+";
  text: string;
}

const KIRA_FEED: Omit<LogLine, "id" | "time">[] = [
  { arrow: "→", text: "kane · payload" },
  { arrow: "←", text: "kane · ack" },
  { arrow: "→", text: "kane · stage diff" },
  { arrow: "←", text: "kane · ready" },
  { arrow: "→", text: "kane · run check" },
  { arrow: "←", text: "kane · 200 OK" },
  { arrow: "✓", text: "verify passed" },
  { arrow: "+", text: "pr opened #482" },
  { arrow: "·", text: "watch listening" },
];

const KANE_FEED: Omit<LogLine, "id" | "time">[] = [
  { arrow: "←", text: "kiro · payload" },
  { arrow: "→", text: "kiro · ack" },
  { arrow: "←", text: "kiro · stage diff" },
  { arrow: "·", text: "exec checkout suite" },
  { arrow: "→", text: "kiro · ready" },
  { arrow: "·", text: "test_place_order" },
  { arrow: "→", text: "kiro · 200 OK" },
  { arrow: "✓", text: "passing flow" },
  { arrow: "·", text: "idle" },
];

const MAX_LINES = 7;
const TICK_MS = 700;
const START_T = 1.2;
const T_STEP = 0.7;

function arrowColor(a: LogLine["arrow"]): string {
  if (a === "✓") return "#4ade80";
  if (a === "+") return "#e85d1a";
  if (a === "→" || a === "←") return "#ffe4a8";
  return "rgba(255,255,255,0.4)";
}

function useFeed(feed: Omit<LogLine, "id" | "time">[]) {
  const [lines, setLines] = useState<LogLine[]>(() =>
    feed.slice(0, 3).map((l, i) => ({
      ...l,
      id: i,
      time: (START_T + i * T_STEP).toFixed(1) + "s",
    })),
  );
  const idx = useRef(3);
  const nextId = useRef(3);
  useEffect(() => {
    const interval = setInterval(() => {
      const line = feed[idx.current % feed.length];
      idx.current += 1;
      const id = nextId.current++;
      setLines((prev) => {
        const next = [
          ...prev,
          {
            ...line,
            id,
            time: (START_T + (id * T_STEP) % 60).toFixed(1) + "s",
          },
        ];
        return next.length > MAX_LINES ? next.slice(next.length - MAX_LINES) : next;
      });
    }, TICK_MS);
    return () => clearInterval(interval);
  }, [feed]);
  return lines;
}

export function LiveLogs({ runId }: { runId?: string | null } = {}) {
  const [active, setActive] = useState<"kiro" | "kane">("kiro");
  useEffect(() => {
    const id = setInterval(
      () => setActive((a) => (a === "kiro" ? "kane" : "kiro")),
      1400,
    );
    return () => clearInterval(id);
  }, []);

  // If runId is provided, derive real-time feeds from the orchestrator's
  // WebSocket. Otherwise show a single "waiting" line per column so the
  // user never sees stale canned data on a real run that just hasn't
  // emitted anything yet.
  const { events, connected } = useIncidentStream(runId ?? null);
  const { kiroFeed, kaneFeed } = useMemo(() => {
    if (!runId) {
      // No incident in scope at all — keep the demo feeds so the panel
      // still looks alive on the landing dashboard.
      return { kiroFeed: KIRA_FEED, kaneFeed: KANE_FEED };
    }
    if (events.length === 0) {
      const placeholder: Omit<LogLine, "id" | "time">[] = [
        { arrow: "·", text: connected ? "waiting for events…" : "connecting…" },
      ];
      return { kiroFeed: placeholder, kaneFeed: placeholder };
    }
    return splitEventsByAgent(events);
  }, [events, runId, connected]);

  return (
    <div className="rounded bg-black border border-white/10 p-3">
      <div className="grid grid-cols-2 gap-2">
        <LogColumn
          label="Kiro"
          avatar="/kira.jpg"
          feed={kiroFeed}
          active={active === "kiro"}
        />
        <LogColumn
          label="Kane"
          avatar="/kane.png"
          feed={kaneFeed}
          active={active === "kane"}
        />
      </div>
    </div>
  );
}

/**
 * Sort WebSocket events into Kiro vs Kane columns.
 *
 *   Kiro column:  patch, state_change=PATCH/SHIP/RECORD, pr_opened
 *   Kane column:  kane_step, kane_result, state_change=REPRODUCE/VERIFY/CONFIRM
 *
 * Each event is mapped to one of the column's existing arrow/text
 * vocab so visual styling never changes.
 */
function splitEventsByAgent(events: { event: string; state?: string; [k: string]: unknown }[]) {
  const kiro: Omit<LogLine, "id" | "time">[] = [];
  const kane: Omit<LogLine, "id" | "time">[] = [];

  for (const ev of events) {
    if (ev.event === "kane_step") {
      const step = String(ev.step || "step");
      const status = String(ev.status || "");
      let arrow: LogLine["arrow"] = "·";
      if (status === "passed") arrow = "✓";
      else if (status === "running") arrow = "→";
      else if (status === "failed") arrow = "·";
      kane.push({ arrow, text: `${step} · ${status || "run"}` });
    } else if (ev.event === "kane_result") {
      const passed = !!ev.passed;
      kane.push({
        arrow: passed ? "✓" : "·",
        text: `kane · ${passed ? "200 OK" : "red"}`,
      });
    } else if (ev.event === "patch") {
      kiro.push({ arrow: "→", text: `kiro · ${String(ev.branch || "stage diff")}` });
    } else if (ev.event === "pr_opened") {
      kiro.push({ arrow: "+", text: "pr opened" });
    } else if (ev.event === "awaiting_approval") {
      kiro.push({ arrow: "←", text: "kiro · awaiting decision" });
    } else if (ev.event === "state_change") {
      const s = String(ev.state || "");
      if (["PATCH", "SHIP", "RECORD"].includes(s)) {
        kiro.push({ arrow: "→", text: `kiro · ${s.toLowerCase()}` });
      } else if (["REPRODUCE", "VERIFY", "CONFIRM", "REVIEW"].includes(s)) {
        kane.push({ arrow: "→", text: `kane · ${s.toLowerCase()}` });
      } else if (s === "RESOLVED") {
        kiro.push({ arrow: "✓", text: "resolved" });
        kane.push({ arrow: "✓", text: "verify passed" });
      } else if (s === "ESCALATE") {
        kiro.push({ arrow: "·", text: "escalated" });
      }
    }
  }
  // Fall back to canned feeds if we somehow produced nothing — keeps
  // the panel visually populated.
  return {
    kiroFeed: kiro.length ? kiro : KIRA_FEED,
    kaneFeed: kane.length ? kane : KANE_FEED,
  };
}

function LogColumn({
  label,
  avatar,
  feed,
  active,
}: {
  label: string;
  avatar: string;
  feed: Omit<LogLine, "id" | "time">[];
  active: boolean;
}) {
  const lines = useFeed(feed);
  return (
    <div
      className="min-w-0 rounded p-2 transition-shadow"
      style={{
        boxShadow: active ? "inset 0 0 0 1px #e85d1a, 0 0 18px rgba(232,93,26,0.35)" : "inset 0 0 0 1px transparent",
        background: active ? "rgba(232,93,26,0.04)" : "transparent",
      }}
    >
      <div className="flex items-center gap-2 pb-2 mb-2 border-b border-white/10">
        <div className="h-5 w-5 rounded-full overflow-hidden border border-white/15 shrink-0">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={avatar}
            alt={label}
            className="w-full h-full object-cover"
          />
        </div>
        <span className="text-xs text-white truncate">{label}</span>
      </div>
      <ol
        className="space-y-1 text-[11px] leading-snug overflow-hidden"
        style={{ minHeight: `calc(${MAX_LINES} * 1.375 * 11px + ${MAX_LINES - 1} * 4px)` }}
      >
        {lines.map((l, i) => {
          const isLast = i === lines.length - 1;
          return (
            <li
              key={l.id}
              className="flex items-baseline gap-1.5 truncate"
              style={{
                opacity: isLast ? 1 : 0.7 - (lines.length - 1 - i) * 0.08,
              }}
            >
              <span className="text-white/40 shrink-0">{l.time}</span>
              <span
                className="shrink-0"
                style={{ color: arrowColor(l.arrow) }}
              >
                {l.arrow}
              </span>
              <span className="text-white truncate">{l.text}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
