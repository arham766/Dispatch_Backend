/**
 * Dispatch — Live incident WebSocket subscription.
 *
 * Connects to ws://<api>/incidents/{run_id}/ws. The first message is a
 * `snapshot` envelope; everything after is a replayed past event or a
 * live one — the hook normalizes both into the same `events` array.
 *
 * Auto-reconnect with exponential backoff (1s, 2s, 4s, 8s), capped at
 * 8s. The server replays past events on every reconnect, so the
 * timeline stays complete even after a flaky network blip.
 */

import { useEffect, useRef, useState } from "react";
import { API_BASE } from "./useAuth";

export type LoopEvent = {
  event: string;
  state?: string;
  [k: string]: unknown;
};

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
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const attemptsRef = useRef(0);
  const closedByDoneRef = useRef(false);

  useEffect(() => {
    if (!runId) return;

    setEvents([]);
    setError(null);
    closedByDoneRef.current = false;
    attemptsRef.current = 0;

    let cancelled = false;

    function connect() {
      if (cancelled) return;
      const wsUrl = `${API_BASE.replace(/^http/, "ws")}/incidents/${runId}/ws`;
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
          setEvents([]);
          if (ev.orphaned) {
            setError(
              "This run was interrupted (backend restarted). Trigger a new one.",
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
        const delay = Math.min(
          8000,
          1000 * Math.pow(2, attemptsRef.current++),
        );
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

  return { events, connected, error };
}
