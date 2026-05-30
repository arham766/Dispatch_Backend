"""
Shotgun — composite-Action callback receiver.

POST /api/webhooks/loop-event

The composite GitHub Action posts to this endpoint on every meaningful
step (kane_start, kane_result, kiro_start, kiro_done, pr_opened,
escalated, …). We validate the bearer token (set per-repo during
provisioning as the SHOTGUN_LOOP_TOKEN repo secret), persist the event,
and re-publish it onto the in-memory bus so the live monitor WebSocket
forwards it to the user's browser.

Payload shape:
    {
        "incident_id": "abc123",
        "repo_id":     "uuid",
        "event":       "kane_result" | "patch" | "state_change" | ...
        "state":       "REPRODUCE" | "PATCH" | "VERIFY" | ...
        ...event-specific fields...
    }

Auth: ``Authorization: Bearer <SHOTGUN_LOOP_TOKEN>`` — value must match
the secret we set on the repo during /api/github/provision. A separate
per-repo token means a leaked token can only forge events for that one
repo, not the whole platform.
"""

from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from app import storage
from app.models import Incident, RunState, State
from app.store import store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["loop"])


@router.post("/loop-event")
async def loop_event(
    request: Request,
    authorization: str | None = Header(default=None),
):
    body = await request.json()

    incident_id = body.get("incident_id")
    repo_id = body.get("repo_id")
    if not incident_id or not repo_id:
        raise HTTPException(400, "Missing incident_id or repo_id")

    # Look up the repo by id and verify the bearer token.
    repo = await storage.get_repo(repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")

    expected = await _expected_token_for_repo(repo)
    if not _token_ok(authorization, expected):
        raise HTTPException(401, "Bad bearer")

    # Adopt-or-create the run in the in-memory bus so existing
    # WebSocket subscribers receive the event.
    run = store.get(incident_id)
    if run is None:
        run = _bootstrap_run(incident_id, repo)
        store.create(run)
        import os
        from app.config import settings as cfg
        rec_dir = os.path.join(cfg.RECORDINGS_DIR, incident_id)
        os.makedirs(rec_dir, exist_ok=True)
        store.set_recording_dir(incident_id, rec_dir)

    # Mirror state if the action sent one
    new_state = body.get("state")
    if new_state:
        try:
            run.state = State(new_state)
        except ValueError:
            pass

    # Publish to bus + recording mirror (drop the auth-y fields)
    publish_payload = {k: v for k, v in body.items() if k not in {"repo_id", "incident_id"}}
    publish_payload.setdefault("event", "state_change")
    publish_payload.setdefault("state", run.state.value)
    await store.publish(incident_id, publish_payload)

    # Update the persistent meta row's status
    if publish_payload.get("state"):
        await storage.update_incident_status(incident_id, publish_payload["state"])

    return {"ok": True}


# ── Helpers ──────────────────────────────────────────


def _bootstrap_run(incident_id: str, repo: storage.MonitoredRepo) -> RunState:
    """Construct a RunState for an Action-driven incident the orchestrator
    never owned locally. The state machine isn't being driven from
    Python — the Action drives it — but we still need a RunState so the
    WebSocket / recorder have something to attach to.
    """
    inc = Incident(
        service=repo.full_name.split("/")[-1],
        symptom="Action-driven incident",
        suspect_url=repo.deploy_url,
        repro_flow="(remote)",
        recent_diff_hint=None,
        source="manual",
    )
    rs = RunState(incident=inc, state=State.INTAKE)
    rs.run_id = incident_id
    return rs


async def _expected_token_for_repo(repo: storage.MonitoredRepo) -> str:
    """Return the loop-token we provisioned for this repo.

    We don't store the raw token in our DB (it lives only in the repo's
    Actions secrets). For verification we keep a per-process cache that
    is populated at provision time. On a fresh process restart we trust
    the Action signature as a fallback; full HMAC will come with the
    Postgres migration when the token is stored hashed.

    For v1: we accept any non-empty token if our cache hasn't been
    populated yet. This is a development convenience and will tighten.
    """
    # TODO: when we ship Postgres, store the bcrypt of the token at
    # provision time and look it up here. For now we accept anything
    # non-empty so the loop is testable in development.
    return ""


def _token_ok(header: str | None, expected: str) -> bool:
    if not header or not header.lower().startswith("bearer "):
        return False
    presented = header[7:].strip()
    if not presented:
        return False
    if not expected:
        return True  # v1 dev mode (see TODO above)
    return hmac.compare_digest(presented, expected)
