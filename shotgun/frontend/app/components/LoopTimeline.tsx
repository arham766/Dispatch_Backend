"use client";

import { LoopEvent } from "@/lib/useIncidentStream";
import { useEffect, useRef } from "react";

interface LoopTimelineProps {
  events: LoopEvent[];
}

const STATE_ICONS: Record<string, string> = {
  INTAKE: "📥",
  REPRODUCE: "🔍",
  PATCH: "🔧",
  VERIFY: "✅",
  DECIDE: "🤔",
  CONFIRM: "🔁",
  HUMAN_GATE: "🛡️",
  SHIP: "🚀",
  REVIEW: "🔎",
  REVIEW_DECIDE: "⚖️",
  RECORD: "💾",
  ESCALATE: "⚠️",
  RESOLVED: "✅",
  CALLING: "📞",
  AWAITING_DECISION: "⏳",
  DISMISSED: "🚫",
  STANDBY: "💤",
};

const STATE_COLORS: Record<string, string> = {
  INTAKE: "#6366f1",
  REPRODUCE: "#f59e0b",
  PATCH: "#8b5cf6",
  VERIFY: "#10b981",
  DECIDE: "#ef4444",
  CONFIRM: "#06b6d4",
  HUMAN_GATE: "#f97316",
  SHIP: "#3b82f6",
  REVIEW: "#8b5cf6",
  REVIEW_DECIDE: "#ef4444",
  RECORD: "#6366f1",
  ESCALATE: "#ef4444",
  RESOLVED: "#10b981",
};

export default function LoopTimeline({ events }: LoopTimelineProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events]);

  // Filter to meaningful events (state changes, patches, results)
  const meaningful = events.filter(
    (e) =>
      e.event === "state_change" ||
      e.event === "patch" ||
      e.event === "kane_result" ||
      e.event === "pr_opened" ||
      e.event === "review_result" ||
      e.event === "recorded" ||
      e.event === "escalated" ||
      e.event === "awaiting_approval" ||
      e.event === "done"
  );

  return (
    <div className="timeline-panel">
      <div className="panel-header">
        <h2>🔄 Loop Timeline</h2>
        <span className="event-count">{meaningful.length} events</span>
      </div>
      <div className="timeline-scroll" ref={scrollRef}>
        {meaningful.length === 0 && (
          <div className="timeline-empty">
            Waiting for incident…
          </div>
        )}
        {meaningful.map((ev, i) => (
          <TimelineEntry key={i} event={ev} index={i} isLast={i === meaningful.length - 1} />
        ))}
      </div>
    </div>
  );
}

function TimelineEntry({
  event: ev,
  index,
  isLast,
}: {
  event: LoopEvent;
  index: number;
  isLast: boolean;
}) {
  const state = ev.state || "";
  const icon = STATE_ICONS[state] || "⚡";
  const color = STATE_COLORS[state] || "#64748b";

  return (
    <div
      className={`timeline-entry ${isLast ? "timeline-entry-active" : ""}`}
      style={{ "--accent": color } as React.CSSProperties}
    >
      <div className="timeline-dot">
        <span className="timeline-icon">{icon}</span>
        {!isLast && <div className="timeline-line" />}
      </div>
      <div className="timeline-content">
        <div className="timeline-state" style={{ color }}>
          {state}
        </div>
        <EntryBody event={ev} />
      </div>
    </div>
  );
}

function EntryBody({ event: ev }: { event: LoopEvent }) {
  switch (ev.event) {
    case "state_change":
      return (
        <div className="timeline-detail">
          <p>{ev.message}</p>
          {ev.attempt && (
            <span className="badge badge-attempt">Attempt {ev.attempt}</span>
          )}
        </div>
      );

    case "kane_result":
      return (
        <div className="timeline-detail">
          <span className={`badge ${ev.passed ? "badge-pass" : "badge-fail"}`}>
            {ev.passed ? "✅ PASSED" : "❌ FAILED"}
          </span>
          <p>{ev.summary}</p>
          <span className="timeline-meta">{ev.duration?.toFixed(1)}s</span>
        </div>
      );

    case "patch":
      return (
        <div className="timeline-detail">
          <p>
            Branch: <code>{ev.branch}</code>
          </p>
          {ev.changed_files?.length > 0 && (
            <ul className="file-list">
              {ev.changed_files.map((f: string, i: number) => (
                <li key={i}>{f}</li>
              ))}
            </ul>
          )}
        </div>
      );

    case "pr_opened":
      return (
        <div className="timeline-detail">
          <a href={ev.pr_url} target="_blank" rel="noopener" className="pr-link">
            📝 View Pull Request →
          </a>
        </div>
      );

    case "review_result":
      return (
        <div className="timeline-detail">
          <span className={`badge ${ev.passed ? "badge-pass" : "badge-fail"}`}>
            {ev.passed ? "✅ No regressions" : "❌ Regressions found"}
          </span>
          <p>{ev.flows_run?.length} flows replayed</p>
        </div>
      );

    case "awaiting_approval":
      return (
        <div className="timeline-detail">
          <p>
            ✅ Fixed and verified — ran {ev.confirmation_runs}× green.
          </p>
          <p className="timeline-awaiting">Waiting for human approval…</p>
        </div>
      );

    case "recorded":
      return (
        <div className="timeline-detail">
          <p>Chain length: {ev.chain_length}</p>
        </div>
      );

    case "escalated":
      return (
        <div className="timeline-detail">
          <p className="text-red">{ev.reason}</p>
          <span className="timeline-meta">{ev.attempts} attempt(s)</span>
        </div>
      );

    case "done":
      return (
        <div className="timeline-detail">
          <span
            className={`badge ${
              ev.final_state === "RESOLVED" ? "badge-pass" : "badge-fail"
            }`}
          >
            {ev.final_state}
          </span>
        </div>
      );

    default:
      return <div className="timeline-detail"><p>{ev.message || ev.event}</p></div>;
  }
}
