"""
Shotgun — SSE event types and serializer.

Defines the stable contract between the backend (orchestrator) and the
frontend (Next.js EventSource). The frontend keys off `event` (the type
name) and `state` (the current machine state).

Each SSE line is:  event: <type>\ndata: <json>\n\n
Use sse-starlette's EventSourceResponse to emit them.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class EventType(str, Enum):
    """Every SSE event the front end will ever see."""

    STATE_CHANGE = "state_change"
    """Orchestrator enters a new state.
    Payload: state, attempt, message"""

    KANE_STEP = "kane_step"
    """Each Kane progress line (NDJSON, untyped step).
    Payload: step, status, remark"""

    KANE_RESULT = "kane_result"
    """Kane run_end parsed.
    Payload: passed, summary, screenshot_url, test_url, duration"""

    PATCH = "patch"
    """Kiro produced a candidate fix.
    Payload: branch, diff_summary, changed_files"""

    AWAITING_APPROVAL = "awaiting_approval"
    """HUMAN_GATE reached.
    Payload: summary, confirmation_runs"""

    PR_OPENED = "pr_opened"
    """PR created.
    Payload: pr_url, proof_url"""

    REVIEW_RESULT = "review_result"
    """kane_review finished a pass.
    Payload: passed, flows_run, regressed, review_url"""

    RECORDED = "recorded"
    """Run persisted + chained.
    Payload: recording_dir, prev_run_id, chain_length"""

    ESCALATED = "escalated"
    """Retry/review budget exhausted / cannot reproduce.
    Payload: reason, attempts"""

    DONE = "done"
    """Terminal — close the stream.
    Payload: final_state (RESOLVED / ESCALATE / STANDBY)"""


def make_event(event_type: str | EventType, **data: Any) -> dict:
    """Build a dict ready to be published to the event bus.

    Example:
        await store.publish(run_id, make_event("state_change",
                            state="REPRODUCE", message="Reproducing…"))
    """
    name = event_type.value if isinstance(event_type, EventType) else event_type
    return {"event": name, **data}
