"use client";

import { useEffect, useState } from "react";
import { useIncidentStream, useIncidentApi } from "@/lib/useIncidentStream";
import LoopTimeline from "@/app/components/LoopTimeline";
import KaneScreen from "@/app/components/KaneScreen";
import PrCard from "@/app/components/PrCard";

const SEEDED_INCIDENT = {
  service: "checkout",
  symptom:
    "Checkout returns Internal Error on pay submit after last payment.js deploy",
  suspect_url: "http://localhost:3001/",
  repro_flow: "flows/checkout_test.md",
  recent_diff_hint: "payment.js",
  source: "manual",
};

export default function Home() {
  const [runId, setRunIdState] = useState<string | null>(null);
  const { events, connected } = useIncidentStream(runId);
  const { triggerIncident, approveIncident, loading } = useIncidentApi();

  // Read run_id from ?run= on first paint, mirror back to URL whenever it changes.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const seeded = params.get("run");
    if (seeded) setRunIdState(seeded);
  }, []);

  const setRunId = (id: string | null) => {
    setRunIdState(id);
    const url = new URL(window.location.href);
    if (id) url.searchParams.set("run", id);
    else url.searchParams.delete("run");
    window.history.replaceState({}, "", url.toString());
  };

  const last = events.length > 0 ? events[events.length - 1] : null;
  const awaiting = last?.event === "awaiting_approval";
  const prEvent = events.find((e) => e.event === "pr_opened");
  const isDone = events.some((e) => e.event === "done");
  const finalState = isDone
    ? events.find((e) => e.event === "done")?.final_state
    : null;

  async function handleTrigger() {
    const id = await triggerIncident(SEEDED_INCIDENT);
    setRunId(id);
  }

  async function handleApprove() {
    if (runId) {
      await approveIncident(runId);
    }
  }

  return (
    <div className="app-container">
      {/* Header */}
      <header className="app-header">
        <div className="header-left">
          <h1 className="app-title">
            <span className="title-icon">🎯</span>
            Shotgun
          </h1>
          <span className="app-subtitle">On-Call Copilot</span>
        </div>
        <div className="header-right">
          {connected && (
            <span className="connection-badge connected">
              <span className="connection-dot" /> Live
            </span>
          )}
          {runId && (
            <span className="run-badge">
              Run: <code>{runId}</code>
            </span>
          )}
        </div>
      </header>

      {/* Main content — split screen */}
      <main className="split-screen">
        {/* LEFT: Loop timeline */}
        <LoopTimeline events={events} />

        {/* RIGHT: Kane screen */}
        <KaneScreen events={events} />
      </main>

      {/* Footer controls */}
      <footer className="app-footer">
        {/* Trigger button */}
        {!runId && (
          <button
            className="btn btn-trigger"
            onClick={handleTrigger}
            disabled={loading}
          >
            <span className="btn-icon">🔔</span>
            {loading ? "Triggering…" : "Trigger Incident"}
          </button>
        )}

        {/* Approve button (human gate) */}
        {awaiting && (
          <div className="approval-section">
            <div className="approval-glow" />
            <p className="approval-text">
              ✅ Fixed and verified. Open the PR?
            </p>
            <button className="btn btn-approve" onClick={handleApprove}>
              <span className="btn-icon">✅</span>
              Open the PR
            </button>
          </div>
        )}

        {/* PR card */}
        {prEvent && (
          <PrCard
            prUrl={prEvent.pr_url}
            proofUrl={prEvent.proof_url}
            branch={events.find((e) => e.event === "patch")?.branch}
          />
        )}

        {/* Final status */}
        {isDone && !prEvent && (
          <div className={`final-banner ${finalState === "RESOLVED" ? "final-resolved" : "final-escalated"}`}>
            <span className="final-icon">
              {finalState === "RESOLVED" ? "✅" : "⚠️"}
            </span>
            <span>{finalState === "RESOLVED" ? "Resolved" : "Escalated"}</span>
          </div>
        )}
      </footer>
    </div>
  );
}
