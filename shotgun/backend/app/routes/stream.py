"""
Shotgun — WebSocket streaming endpoint.

ws://.../incidents/{run_id}/ws — bidirectional channel for the live monitor.

Protocol (server → client):
    Each message is a JSON object exactly matching what the orchestrator
    publishes to the event bus, e.g.:
        {"event":"state_change","state":"REPRODUCE","message":"…"}
        {"event":"kane_result","passed":true,"summary":"…", …}

    The very first message after connect is a snapshot envelope:
        {"event":"snapshot","run_id":"…","past_event_count":N,"state":"…"}
    followed by N replayed past events, then live events from the bus.

    Replay closes the "page-opened-mid-run shows nothing" hole — every
    state_change, kane_step, patch, kane_result etc. that fired before
    you connected is sent immediately so the UI's timeline is complete.

Protocol (client → server):
    Currently none. A `ping`/`pong` heartbeat may be added later.

Lifecycle:
    Connection closes when the orchestrator emits `done` (final event)
    or when the client disconnects. Disconnected subscribers are reaped
    so the per-run queue list stays small.
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.store import store

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stream"])


@router.websocket("/incidents/{run_id}/ws")
async def websocket_stream(websocket: WebSocket, run_id: str) -> None:
    """Live event feed for one incident run.

    Sequence:
        1. Accept the upgrade.
        2. Verify the run exists.
        3. Subscribe to the event bus BEFORE replay — anything published
           between replay and live attach lands in our queue, no gap.
        4. Send a `snapshot` envelope + replay every past event from
           the run's events.ndjson mirror.
        5. Stream live events from the queue until `done` or disconnect.
    """
    await websocket.accept()

    run = store.get(run_id)
    if not run:
        # Orphaned run — the orchestrator that drove it died (most often:
        # backend restart). Replay whatever was recorded so the user sees
        # the actual history instead of reconnect-spamming, then close
        # cleanly with a synthetic `done` event.
        past = store.read_past_events(run_id)
        if past:
            logger.info(
                "ws: %s orphaned but %d events recorded — replaying read-only",
                run_id, len(past),
            )
            await websocket.send_text(json.dumps({
                "event": "snapshot",
                "run_id": run_id,
                "state": past[-1].get("state", "UNKNOWN"),
                "attempt": 0,
                "past_event_count": len(past),
                "orphaned": True,
            }))
            for ev in past:
                await websocket.send_text(json.dumps(ev, default=str))
            await websocket.send_text(json.dumps({
                "event": "done",
                "state": past[-1].get("state", "ESCALATE"),
                "final_state": "ORPHANED",
                "reason": (
                    "Backend was restarted while this run was in flight; "
                    "trigger a new one from the dashboard."
                ),
            }))
            await websocket.close()
            return
        logger.warning("ws: run %s not found and no recording, closing", run_id)
        await websocket.close(code=1008, reason="Run not found")
        return

    # Subscribe FIRST so we never lose an event during the replay window.
    q = store.subscribe(run_id)
    sent_keys: set[tuple[str, str]] = set()  # dedupe across replay+live boundary

    def _key(ev: dict) -> tuple[str, str]:
        """A stable-ish dedupe key for replayed vs live events."""
        return (ev.get("event", ""), json.dumps(ev, sort_keys=True, default=str))

    async def _send(ev: dict) -> None:
        await websocket.send_text(json.dumps(ev, default=str))

    try:
        # Replay past events from disk
        past = store.read_past_events(run_id)
        await _send({
            "event": "snapshot",
            "run_id": run_id,
            "state": run.state.value,
            "attempt": run.attempt,
            "past_event_count": len(past),
        })
        for ev in past:
            sent_keys.add(_key(ev))
            await _send(ev)

        logger.info("ws: %s replayed %d past events, switching to live", run_id, len(past))

        # Live stream
        while True:
            ev = await q.get()
            k = _key(ev)
            if k in sent_keys:
                continue  # likely just replayed; skip
            sent_keys.add(k)
            await _send(ev)
            if ev.get("event") == "done":
                break

    except WebSocketDisconnect:
        logger.info("ws: %s client disconnected", run_id)
    except Exception as exc:
        logger.error("ws: %s error — %s", run_id, exc)
    finally:
        store.unsubscribe(run_id, q)
        try:
            await websocket.close()
        except Exception:
            pass
