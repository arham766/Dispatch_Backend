"""
Shotgun — In-memory run registry + event bus.

The orchestrator and the SSE endpoint never call each other directly.
They communicate through a per-run `asyncio.Queue`. The orchestrator
publishes; every connected browser subscribes.

Also supports approval gating (HUMAN_GATE) and voice decisions
(AgentPhone CALLING / AWAITING_DECISION).
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from app.models import RunState


class RunStore:
    """In-memory store for active runs + per-run event fan-out."""

    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}
        self._queues: dict[str, list[asyncio.Queue]] = {}
        self._approvals: dict[str, asyncio.Event] = {}
        self._decisions: dict[str, asyncio.Event] = {}
        self._decision_values: dict[str, str] = {}
        # Mirror file handles for recording (written lazily)
        self._event_files: dict[str, Any] = {}

    # ── Run lifecycle ─────────────────────────────────

    def create(self, run: RunState) -> RunState:
        """Register a new run, set up its event queues and gates."""
        self._runs[run.run_id] = run
        self._queues[run.run_id] = []
        self._approvals[run.run_id] = asyncio.Event()
        self._decisions[run.run_id] = asyncio.Event()
        return run

    def get(self, run_id: str) -> RunState | None:
        """Get the current state of a run."""
        return self._runs.get(run_id)

    def list_runs(self) -> list[RunState]:
        """List all runs (most recent first)."""
        return sorted(self._runs.values(), key=lambda r: r.created_at, reverse=True)

    # ── Event fan-out ─────────────────────────────────

    async def publish(self, run_id: str, event: dict) -> None:
        """Push an event to all subscribers of this run.

        Also mirrors the event to the recording NDJSON file if recording
        is enabled and the run directory exists.
        """
        for q in self._queues.get(run_id, []):
            await q.put(event)

        # Mirror to recordings/<run_id>/events.ndjson
        self._mirror_event(run_id, event)

    def subscribe(self, run_id: str) -> asyncio.Queue:
        """Subscribe to live events for a run. Returns a new Queue."""
        q: asyncio.Queue = asyncio.Queue()
        self._queues.setdefault(run_id, []).append(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        """Remove a subscriber queue."""
        queues = self._queues.get(run_id, [])
        if q in queues:
            queues.remove(q)

    # ── Human gate (web-app approval) ─────────────────

    def approve(self, run_id: str) -> None:
        """Signal that the human approved the fix (HUMAN_GATE → SHIP)."""
        self._approvals[run_id].set()

    async def wait_for_approval(self, run_id: str) -> None:
        """Block until the human approves."""
        await self._approvals[run_id].wait()

    # ── Voice decisions (AgentPhone) ──────────────────

    def set_decision(self, run_id: str, decision: str) -> None:
        """Record a spoken decision ("fix" / "dismiss") from AgentPhone."""
        self._decision_values[run_id] = decision
        if run_id in self._decisions:
            self._decisions[run_id].set()

    async def wait_for_decision(self, run_id: str) -> str:
        """Block until a voice decision arrives. Returns "fix" or "dismiss"."""
        await self._decisions[run_id].wait()
        return self._decision_values.get(run_id, "fix")

    # ── Recording mirror ──────────────────────────────

    def set_recording_dir(self, run_id: str, recording_dir: str) -> None:
        """Set the recording directory so events are mirrored to disk."""
        ndjson_path = os.path.join(recording_dir, "events.ndjson")
        os.makedirs(recording_dir, exist_ok=True)
        self._event_files[run_id] = ndjson_path

    def _mirror_event(self, run_id: str, event: dict) -> None:
        """Append an event line to the recording NDJSON file."""
        path = self._event_files.get(run_id)
        if path:
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(event) + "\n")
            except OSError:
                pass  # best-effort recording; never block the loop

    # ── Event replay (for late WebSocket joiners) ─────

    def read_past_events(self, run_id: str) -> list[dict]:
        """Return every event mirrored to disk for this run, in order.

        Used by the WebSocket endpoint to catch up clients that connected
        after the loop already started, so the UI shows the full timeline
        the moment the page loads.
        """
        path = self._event_files.get(run_id)
        if not path or not os.path.exists(path):
            return []
        out: list[dict] = []
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass
        return out


# Module-level singleton — import this everywhere
store = RunStore()
