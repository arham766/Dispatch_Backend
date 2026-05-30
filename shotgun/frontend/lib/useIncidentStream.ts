/**
 * Shotgun — WebSocket hook for live incident streaming.
 *
 * Connects to ws://.../incidents/{run_id}/ws and accumulates events
 * into local state. The very first message is a `snapshot` envelope
 * with a count of past events; everything after is either a replayed
 * past event or a live one — the UI doesn't have to care which.
 *
 * Reconnect strategy:
 *   - exponential backoff (1s, 2s, 4s, 8s, capped at 8s)
 *   - replays past events again on reconnect, so the timeline stays
 *     complete after a flaky network blip
 *   - auto-closes on `done` event
 */

import { useEffect, useRef, useState, useCallback } from "react";

export type LoopEvent = {
  event: string;
  state?: string;
  [k: string]: any;
};

const API = process.env.NEXT_PUBLIC_API || "http://localhost:8000";

// Every event the orchestrator emits that we want surfaced in the UI.
// (The `snapshot` envelope is consumed by the hook itself, not pushed.)
const KNOWN_EVENTS = new Set([
  "state_change",
  "kane_step",
  "kane_result",
  "patch",
  "awaiting_approval",
  "pr_opened",
  "review_result",
  "recorded",
  "escalated",
  "done",
]);

export function useIncidentStream(runId: string | null) {
  const [events, setEvents] = useState<LoopEvent[]>([]);
  const [snapshot, setSnapshot] = useState<{ past_event_count: number; state: string } | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const attemptsRef = useRef(0);
  const closedByDoneRef = useRef(false);

  useEffect(() => {
    if (!runId) return;

    // Reset on run change
    setEvents([]);
    setSnapshot(null);
    setError(null);
    closedByDoneRef.current = false;
    attemptsRef.current = 0;

    let cancelled = false;

    function connect() {
      if (cancelled) return;
      const wsUrl = `${API.replace(/^http/, "ws")}/incidents/${runId}/ws`;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        setError(null);
        attemptsRef.current = 0;
      };

      ws.onmessage = (e: MessageEvent) => {
        let ev: LoopEvent;
        try {
          ev = JSON.parse(e.data);
        } catch {
          return;
        }

        if (ev.event === "snapshot") {
          // Reset events on (re)connect — server replays full history.
          setSnapshot({
            past_event_count: ev.past_event_count ?? 0,
            state: ev.state ?? "",
          });
          setEvents([]);
          if (ev.orphaned) {
            setError(
              "This run was interrupted (backend restarted). Trigger a new one."
            );
          }
          return;
        }

        if (KNOWN_EVENTS.has(ev.event)) {
          setEvents((prev) => [...prev, ev]);
        }

        if (ev.event === "done") {
          closedByDoneRef.current = true;
          ws.close();
        }
      };

      ws.onerror = () => {
        setError("Connection lost — retrying…");
      };

      ws.onclose = () => {
        setConnected(false);
        if (closedByDoneRef.current || cancelled) return;
        const delay = Math.min(8000, 1000 * Math.pow(2, attemptsRef.current++));
        setTimeout(connect, delay);
      };
    }

    connect();

    return () => {
      cancelled = true;
      closedByDoneRef.current = true;
      wsRef.current?.close();
      setConnected(false);
    };
  }, [runId]);

  return { events, snapshot, connected, error };
}

export function useIncidentApi() {
  const [loading, setLoading] = useState(false);

  const triggerIncident = useCallback(async (payload: object): Promise<string> => {
    setLoading(true);
    try {
      const r = await fetch(`${API}/incidents`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await r.json();
      return data.run_id;
    } finally {
      setLoading(false);
    }
  }, []);

  const approveIncident = useCallback(async (runId: string): Promise<void> => {
    await fetch(`${API}/incidents/${runId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approve: true }),
    });
  }, []);

  const rejectIncident = useCallback(async (runId: string): Promise<void> => {
    await fetch(`${API}/incidents/${runId}/reject`, { method: "POST" });
  }, []);

  return { triggerIncident, approveIncident, rejectIncident, loading };
}
