"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useIncidentStream, type LoopEvent } from "@/lib/useIncidentStream";

interface LogLine {
  id: number;
  time: string;
  arrow: "→" | "←" | "·" | "✓" | "+";
  text: string;
}

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

// ── Canned demo feeds (only used on pages without a live runId) ─────

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

// ── Cycling fake feed (no runId — landing page demo only) ─────────

function useFakeFeed(feed: Omit<LogLine, "id" | "time">[]) {
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

// ── Real-events feeds (runId present) ─────────────────────────────

interface RealLine extends LogLine {
  agent: "kiro" | "kane";
}

/**
 * Convert WebSocket events into per-column real-time log lines.
 * Each line is tagged with the actual elapsed seconds since the
 * incident's first known timestamp, and consecutive identical
 * (arrow, text) pairs in the same column are deduped.
 */
function buildRealFeeds(events: LoopEvent[]): {
  kiro: RealLine[];
  kane: RealLine[];
  currentlyDoing: string;
} {
  if (events.length === 0) {
    return { kiro: [], kane: [], currentlyDoing: "" };
  }

  const t0 = (events[0] as { ts?: number }).ts ?? Date.now() / 1000;

  const kiro: RealLine[] = [];
  const kane: RealLine[] = [];
  let nextId = 0;
  let currentlyDoing = "";

  function pushIfNew(col: RealLine[], line: Omit<RealLine, "id" | "time">, ts: number) {
    const last = col[col.length - 1];
    if (last && last.arrow === line.arrow && last.text === line.text) return;
    col.push({
      ...line,
      id: nextId++,
      time: `${(ts - t0).toFixed(1)}s`,
    });
  }

  for (const ev of events) {
    const ts = (ev as { ts?: number }).ts ?? Date.now() / 1000;
    if (ev.event === "kane_step") {
      const step = String(ev.step || "step");
      const status = String(ev.status || "");
      let arrow: LogLine["arrow"] = "·";
      if (status === "passed") arrow = "✓";
      else if (status === "running") arrow = "→";
      pushIfNew(
        kane,
        { arrow, text: `${step} · ${status || "run"}`, agent: "kane" },
        ts,
      );
      if (status === "running") {
        currentlyDoing = `Kane · ${step}`;
      }
    } else if (ev.event === "kane_result") {
      const passed = !!ev.passed;
      pushIfNew(
        kane,
        {
          arrow: passed ? "✓" : "·",
          text: `kane · ${passed ? "green" : "red"}`,
          agent: "kane",
        },
        ts,
      );
      currentlyDoing = passed ? "Kane verified the fix." : "Kane reproduced the bug.";
    } else if (ev.event === "patch") {
      pushIfNew(
        kiro,
        { arrow: "→", text: `kiro · ${String(ev.branch || "stage diff")}`, agent: "kiro" },
        ts,
      );
      currentlyDoing = `Kiro committed ${String(ev.branch || "the fix")}.`;
    } else if (ev.event === "pr_opened") {
      pushIfNew(kiro, { arrow: "+", text: "pr opened", agent: "kiro" }, ts);
      currentlyDoing = "Pull request is live.";
    } else if (ev.event === "awaiting_approval") {
      pushIfNew(
        kiro,
        { arrow: "←", text: "kiro · awaiting decision", agent: "kiro" },
        ts,
      );
      currentlyDoing = "Awaiting your decision.";
    } else if (ev.event === "state_change") {
      const s = String(ev.state || "");
      if (s === "INTAKE") currentlyDoing = "Incident received.";
      else if (s === "REPRODUCE") {
        currentlyDoing = "Capturing failing flow…";
        pushIfNew(kane, { arrow: "→", text: "kane · reproduce", agent: "kane" }, ts);
      } else if (s === "PATCH") {
        currentlyDoing = "Kiro is writing the fix…";
        pushIfNew(kiro, { arrow: "→", text: "kiro · patch", agent: "kiro" }, ts);
      } else if (s === "VERIFY") {
        currentlyDoing = "Kane is verifying the fix…";
        pushIfNew(kane, { arrow: "→", text: "kane · verify", agent: "kane" }, ts);
      } else if (s === "CONFIRM") {
        currentlyDoing = "Confirming, replaying the flow…";
        pushIfNew(kane, { arrow: "→", text: "kane · confirm", agent: "kane" }, ts);
      } else if (s === "SHIP") {
        currentlyDoing = "Opening the pull request…";
        pushIfNew(kiro, { arrow: "→", text: "kiro · ship", agent: "kiro" }, ts);
      } else if (s === "RECORD") {
        currentlyDoing = "Recording the run…";
        pushIfNew(kiro, { arrow: "→", text: "kiro · record", agent: "kiro" }, ts);
      } else if (s === "RESOLVED") {
        currentlyDoing = "✅ Resolved.";
        pushIfNew(kane, { arrow: "✓", text: "verify passed", agent: "kane" }, ts);
        pushIfNew(kiro, { arrow: "✓", text: "resolved", agent: "kiro" }, ts);
      } else if (s === "ESCALATE") {
        currentlyDoing = "Escalated.";
        pushIfNew(kiro, { arrow: "·", text: "escalated", agent: "kiro" }, ts);
      }
    }
  }

  // Trim each column to the last MAX_LINES so the panel doesn't grow.
  const trim = (xs: RealLine[]) =>
    xs.length > MAX_LINES ? xs.slice(xs.length - MAX_LINES) : xs;

  return {
    kiro: trim(kiro),
    kane: trim(kane),
    currentlyDoing,
  };
}

// ── Component ────────────────────────────────────────────────────

export function LiveLogs({ runId }: { runId?: string | null } = {}) {
  const [active, setActive] = useState<"kiro" | "kane">("kiro");
  useEffect(() => {
    const id = setInterval(
      () => setActive((a) => (a === "kiro" ? "kane" : "kiro")),
      1400,
    );
    return () => clearInterval(id);
  }, []);

  const { events, connected } = useIncidentStream(runId ?? null);

  // Tag each event with the time we received it so we get real elapsed
  // timings in the column instead of the synthetic cycle clock.
  const stampedEvents = useRealtimeStamps(events);

  const real = useMemo(
    () => buildRealFeeds(stampedEvents),
    [stampedEvents],
  );

  return (
    <div className="rounded bg-black border border-white/10 p-3">
      {/* Currently-doing header — only when a real run is in scope */}
      {runId ? (
        <div className="flex items-center justify-between pb-2 mb-2 border-b border-white/10">
          <span className="text-[11px] text-white truncate">
            {real.currentlyDoing || (connected ? "Waiting for events…" : "Connecting…")}
          </span>
          <span
            className="shrink-0 ml-2 inline-flex items-center gap-1 text-[10px] text-white/40 uppercase tracking-wider"
          >
            <span
              className="inline-block w-1.5 h-1.5 rounded-full"
              style={{ background: connected ? "#4ade80" : "#9c9c9c" }}
            />
            live
          </span>
        </div>
      ) : null}

      <div className="grid grid-cols-2 gap-2">
        <LogColumn
          label="Kiro"
          avatar="/kira.jpg"
          fixedFeed={runId ? real.kiro : null}
          fallbackFeed={KIRA_FEED}
          active={active === "kiro"}
        />
        <LogColumn
          label="Kane"
          avatar="/kane.png"
          fixedFeed={runId ? real.kane : null}
          fallbackFeed={KANE_FEED}
          active={active === "kane"}
        />
      </div>
    </div>
  );
}

/**
 * Decorate events with a `ts` (epoch seconds) the moment we observe
 * them, so the rendered times reflect when the backend really emitted
 * them — not when the array was built.
 */
function useRealtimeStamps(events: LoopEvent[]): (LoopEvent & { ts: number })[] {
  const tsRef = useRef(new Map<LoopEvent, number>());
  return useMemo(() => {
    const out: (LoopEvent & { ts: number })[] = [];
    for (const ev of events) {
      let ts = tsRef.current.get(ev);
      if (!ts) {
        ts = Date.now() / 1000;
        tsRef.current.set(ev, ts);
      }
      out.push({ ...ev, ts });
    }
    return out;
  }, [events]);
}

function LogColumn({
  label,
  avatar,
  fixedFeed,
  fallbackFeed,
  active,
}: {
  label: string;
  avatar: string;
  fixedFeed: RealLine[] | null;
  fallbackFeed: Omit<LogLine, "id" | "time">[];
  active: boolean;
}) {
  const cycledLines = useFakeFeed(fallbackFeed);
  // When a real feed is provided, render those lines directly (no
  // ticking, no cycling). The empty state shows a single "waiting…"
  // line so the column still has structure.
  let displayed: LogLine[];
  if (fixedFeed !== null) {
    displayed =
      fixedFeed.length > 0
        ? fixedFeed
        : [{ id: -1, time: "—", arrow: "·", text: "waiting…" }];
  } else {
    displayed = cycledLines;
  }

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
        {displayed.map((l, i) => {
          const isLast = i === displayed.length - 1;
          return (
            <li
              key={l.id}
              className="flex items-baseline gap-1.5 truncate"
              style={{
                opacity: isLast ? 1 : 0.7 - (displayed.length - 1 - i) * 0.08,
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
