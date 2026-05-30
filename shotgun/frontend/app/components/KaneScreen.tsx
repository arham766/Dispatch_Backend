"use client";

import { LoopEvent } from "@/lib/useIncidentStream";
import { useEffect, useRef } from "react";

interface KaneScreenProps {
  events: LoopEvent[];
}

export default function KaneScreen({ events }: KaneScreenProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events]);

  // Get current state
  const stateEvents = events.filter((e) => e.event === "state_change");
  const currentState = stateEvents.length > 0
    ? stateEvents[stateEvents.length - 1].state ?? null
    : null;

  // Get Kane steps
  const steps = events.filter((e) => e.event === "kane_step");

  // Get latest Kane result
  const results = events.filter((e) => e.event === "kane_result");
  const latestResult = results.length > 0 ? results[results.length - 1] : null;

  // Check if done
  const isDone = events.some((e) => e.event === "done");
  const finalState = isDone
    ? events.find((e) => e.event === "done")?.final_state
    : null;

  return (
    <div className="kane-panel">
      <div className="panel-header">
        <h2>🎯 Kane Verifier</h2>
        <StatusBadge state={currentState} result={latestResult} isDone={isDone} />
      </div>

      {/* Status card */}
      <div className="kane-status-card">
        {!currentState && (
          <div className="kane-idle">
            <div className="kane-idle-icon">🔍</div>
            <p>Waiting for Kane to start…</p>
          </div>
        )}

        {currentState && !isDone && (
          <div className="kane-running">
            <div className="pulse-dot" />
            <span>
              {currentState === "REPRODUCE"
                ? "Reproducing the bug…"
                : currentState === "VERIFY"
                ? "Verifying the fix…"
                : currentState === "CONFIRM"
                ? "Running confirmation replays…"
                : currentState === "REVIEW"
                ? "Running regression suite…"
                : `State: ${currentState}`}
            </span>
          </div>
        )}

        {isDone && (
          <div className={`kane-final ${finalState === "RESOLVED" ? "kane-resolved" : "kane-escalated"}`}>
            <div className="kane-final-icon">
              {finalState === "RESOLVED" ? "✅" : "⚠️"}
            </div>
            <h3>{finalState === "RESOLVED" ? "Fix Verified!" : "Escalated"}</h3>
          </div>
        )}
      </div>

      {/* Latest result */}
      {latestResult && (
        <div className={`kane-result-card ${latestResult.passed ? "result-pass" : "result-fail"}`}>
          <div className="result-header">
            <span className="result-emoji">
              {latestResult.passed ? "✅" : "❌"}
            </span>
            <span className="result-status">
              {latestResult.passed ? "PASSED" : "FAILED"}
            </span>
            <span className="result-duration">
              {latestResult.duration?.toFixed(1)}s
            </span>
          </div>
          <p className="result-summary">{latestResult.summary}</p>
          {latestResult.test_url && (
            <a
              href={latestResult.test_url}
              target="_blank"
              rel="noopener"
              className="result-link"
            >
              View KaneAI trace →
            </a>
          )}
        </div>
      )}

      {/* Step log */}
      <div className="kane-steps" ref={scrollRef}>
        <div className="steps-header">
          <h3>📋 Step Log</h3>
          <span className="step-count">{steps.length} steps</span>
        </div>
        <div className="steps-list">
          {steps.length === 0 && (
            <div className="steps-empty">No steps yet…</div>
          )}
          {steps.map((step, i) => (
            <div key={i} className="step-entry">
              <span className="step-name">{step.step}</span>
              <span className={`step-status ${step.status === "passed" ? "step-pass" : ""}`}>
                {step.status}
              </span>
              {step.remark && (
                <span className="step-remark">{step.remark}</span>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* All results history */}
      {results.length > 1 && (
        <div className="kane-history">
          <h3>📊 Run History</h3>
          <div className="history-dots">
            {results.map((r, i) => (
              <div
                key={i}
                className={`history-dot ${r.passed ? "dot-pass" : "dot-fail"}`}
                title={`${r.passed ? "Pass" : "Fail"}: ${r.summary}`}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function StatusBadge({
  state,
  result,
  isDone,
}: {
  state: string | null;
  result: LoopEvent | null;
  isDone: boolean;
}) {
  if (isDone) {
    return <span className="status-badge status-done">DONE</span>;
  }
  if (!state) {
    return <span className="status-badge status-idle">IDLE</span>;
  }
  if (state === "REPRODUCE" || state === "VERIFY" || state === "CONFIRM" || state === "REVIEW") {
    return <span className="status-badge status-running">RUNNING</span>;
  }
  if (result && !result.passed) {
    return <span className="status-badge status-fail">FAILED</span>;
  }
  return <span className="status-badge status-active">{state}</span>;
}
