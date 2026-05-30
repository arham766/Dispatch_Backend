"""
Shotgun — Incident API routes.

Endpoints:
    POST   /incidents                   Start a run
    GET    /incidents/{run_id}          Snapshot of current RunState
    POST   /incidents/{run_id}/approve  Human gate: open the PR
    POST   /incidents/{run_id}/reject   Human gate: stand down
    POST   /webhooks/agentphone/decision  Voice decision callback
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.intake.normalize import to_incident
from app.models import RunState, State
from app.orchestrator import run_incident
from app.store import store
from app import recorder

logger = logging.getLogger(__name__)

router = APIRouter(tags=["incidents"])


# ── Request / Response models ─────────────────────────


class ApproveRequest(BaseModel):
    approve: bool = True


class IncidentResponse(BaseModel):
    run_id: str
    state: str


# ── Endpoints ─────────────────────────────────────────


@router.post("/incidents", response_model=IncidentResponse)
async def create_incident(payload: dict, bg: BackgroundTasks):
    """Start a new incident run.

    Accepts PagerDuty, Sentry, Kafka (CEO contract), or plain JSON.
    Normalizes the payload → Incident, creates a RunState, and spawns
    the orchestrator as a background task.
    """
    try:
        incident = to_incident(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    run = store.create(RunState(incident=incident))
    logger.info(
        "Created run %s for incident: %s — %s",
        run.run_id, incident.service, incident.symptom,
    )

    # Spawn the orchestrator (runs detached)
    bg.add_task(run_incident, run)

    return IncidentResponse(run_id=run.run_id, state=run.state.value)


@router.get("/incidents/{run_id}")
async def get_incident(run_id: str):
    """Snapshot of the current RunState (debug / reconnect)."""
    run = store.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run.model_dump(mode="json")


@router.post("/incidents/{run_id}/approve")
async def approve_incident(run_id: str, body: ApproveRequest | None = None):
    """Human gate: approve the fix and open the PR.

    The orchestrator is blocked on ``store.wait_for_approval(run_id)``
    and resumes when this is called.
    """
    run = store.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not run.awaiting_approval:
        raise HTTPException(status_code=409, detail="Not awaiting approval")

    store.approve(run_id)
    logger.info("Run %s approved by human", run_id)
    return {"ok": True}


@router.post("/incidents/{run_id}/reject")
async def reject_incident(run_id: str):
    """Human gate: stand down. Sets the run to STANDBY."""
    run = store.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not run.awaiting_approval:
        raise HTTPException(status_code=409, detail="Not awaiting approval")

    run.state = State.STANDBY
    run.awaiting_approval = False
    # Unblock the orchestrator (it will see STANDBY and stop)
    store.approve(run_id)
    logger.info("Run %s rejected by human → STANDBY", run_id)
    return {"ok": True}


@router.get("/incidents")
async def list_incidents():
    """List all runs (most recent first)."""
    runs = store.list_runs()
    return [
        {
            "run_id": r.run_id,
            "service": r.incident.service,
            "symptom": r.incident.symptom,
            "state": r.state.value,
            "attempt": r.attempt,
            "pr_url": r.pr_url,
            "created_at": r.created_at,
        }
        for r in runs
    ]


# ── AgentPhone webhook ────────────────────────────────


@router.post("/webhooks/agentphone/decision")
async def agentphone_decision(body: dict):
    """Spoken decision callback from AgentPhone.

    Body: {"incident_id": "...", "decision": "fix" | "dismiss"}
    """
    incident_id = body.get("incident_id")
    decision = body.get("decision", "fix")

    if not incident_id:
        raise HTTPException(status_code=400, detail="Missing incident_id")

    store.set_decision(incident_id, decision)
    logger.info("AgentPhone decision for %s: %s", incident_id, decision)
    return {"ok": True}
