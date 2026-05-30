"""
Shotgun — GitHub webhook receiver.

POST /api/github/webhook is the single endpoint GitHub posts every event
to. We verify the X-Hub-Signature-256 HMAC against
``GITHUB_APP_WEBHOOK_SECRET`` and dispatch by the X-GitHub-Event header.

Events handled:

  installation                — App was installed / uninstalled.
                                Persists the installation under the user
                                that initiated it (uid carried via the
                                /install cookie + callback URL).

  installation_repositories   — User added or removed repos from an
                                existing installation. We don't need to
                                pre-fetch them — the repo list is queried
                                on demand from /installations/{id}/repos.

  deployment_status           — A deploy finished. If state=="failure"
                                AND the repo is monitored, we open a
                                Shotgun incident and fire a
                                repository_dispatch back to the same repo
                                so the workflow can run the loop.

  workflow_run                — A CI workflow finished. If
                                conclusion=="failure" AND repo is
                                monitored, same flow as deployment_status.

  push                        — Best-effort: if the push touched the
                                workflow file we silently re-commit it
                                to keep our config canonical.

Everything else is logged + acked.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import uuid

from fastapi import APIRouter, Header, HTTPException, Request

from app import storage
from app.clients import github_app
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/github", tags=["github-webhook"])


@router.post("/webhook")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
):
    raw = await request.body()

    if not _signature_ok(raw, x_hub_signature_256):
        raise HTTPException(401, "Bad signature")

    # Parse body
    import json
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")

    event = (x_github_event or "").lower()
    logger.info("webhook: event=%s delivery=%s action=%s",
                event, x_github_delivery, payload.get("action"))

    if event == "installation":
        await _handle_installation(payload)
    elif event == "installation_repositories":
        await _handle_installation_repos(payload)
    elif event == "deployment_status":
        await _handle_deployment_status(payload)
    elif event == "workflow_run":
        await _handle_workflow_run(payload)
    elif event == "push":
        pass  # nothing actionable yet
    elif event == "ping":
        return {"pong": True}
    else:
        logger.info("webhook: ignored event %s", event)

    return {"ok": True}


# ── Signature verify ────────────────────────────────


def _signature_ok(body: bytes, header: str | None) -> bool:
    """Constant-time HMAC-SHA256 verification per GitHub spec.

    When GITHUB_APP_WEBHOOK_SECRET is empty we allow the request through
    (dev mode); production deploys MUST set the secret.
    """
    secret = settings.GITHUB_APP_WEBHOOK_SECRET
    if not secret:
        logger.warning("webhook: no GITHUB_APP_WEBHOOK_SECRET set — skipping signature check")
        return True
    if not header or not header.startswith("sha256="):
        return False
    mac = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={mac}", header)


# ── Event handlers ───────────────────────────────────


async def _handle_installation(payload: dict) -> None:
    """`installation: created/deleted` — track ownership.

    For `created` we rely on the user having gone through /install (which
    stamped a cookie). The browser redirect from GitHub hits our
    /installations/callback BEFORE the webhook arrives, so the row is
    already in place — this handler is a backup for cases like
    org-admin-installs-without-clicking-our-link.
    """
    action = payload.get("action")
    inst = payload.get("installation", {})
    installation_id = inst.get("id")
    if not installation_id:
        return

    if action == "deleted":
        # Nuke from all users; storage is best-effort here.
        for stored in await storage.get_installations_for_user("*"):
            if stored.installation_id == installation_id:
                await storage.delete_installation(stored.user_id, installation_id)
        logger.info("webhook: installation %s deleted", installation_id)
        return

    # `created`: if we don't have a row yet, drop a placeholder under the
    # account's GitHub login. The dashboard will adopt it once the user
    # signs in.
    existing = await storage.get_installation(installation_id)
    if existing:
        return
    account = inst.get("account", {})
    placeholder = storage.Installation(
        user_id=f"pending:{account.get('login', '?')}",
        installation_id=installation_id,
        account_login=account.get("login", ""),
        account_type=account.get("type", "User"),
    )
    await storage.upsert_installation(placeholder)


async def _handle_installation_repos(payload: dict) -> None:
    """`installation_repositories: added/removed` — repo list changed.

    We re-list on demand so nothing to do here beyond logging.
    """
    action = payload.get("action")
    added = [r["full_name"] for r in payload.get("repositories_added", [])]
    removed = [r["full_name"] for r in payload.get("repositories_removed", [])]
    logger.info("webhook: install repos %s added=%s removed=%s", action, added, removed)


async def _handle_deployment_status(payload: dict) -> None:
    """Failed deployment → open an incident and dispatch the loop."""
    status = payload.get("deployment_status", {})
    if status.get("state") != "failure":
        return

    full_name = payload.get("repository", {}).get("full_name")
    if not full_name:
        return

    repo = await storage.get_repo_by_full_name(full_name)
    if not repo or not repo.monitoring_enabled:
        logger.info("webhook: deployment_status failure for unmonitored repo %s", full_name)
        return

    await _open_and_dispatch(
        repo=repo,
        source="webhook_deployment_status",
        symptom=status.get("description") or f"Failed deploy on {full_name}",
        suspect_url=status.get("environment_url") or repo.deploy_url,
    )


async def _handle_workflow_run(payload: dict) -> None:
    """Failed workflow_run on a monitored repo → open incident."""
    run = payload.get("workflow_run", {})
    if run.get("conclusion") != "failure":
        return
    # Don't infinite-loop on our own workflow
    name = (run.get("name") or "").lower()
    if "shotgun" in name:
        return

    full_name = payload.get("repository", {}).get("full_name")
    if not full_name:
        return

    repo = await storage.get_repo_by_full_name(full_name)
    if not repo or not repo.monitoring_enabled:
        return

    await _open_and_dispatch(
        repo=repo,
        source="webhook_workflow_run",
        symptom=f"CI failure: {run.get('name')} ({run.get('event')})",
        suspect_url=repo.deploy_url,
    )


async def _open_and_dispatch(
    repo: storage.MonitoredRepo,
    source: str,
    symptom: str,
    suspect_url: str,
) -> None:
    """Persist an incident row + fire repository_dispatch."""
    incident_id = uuid.uuid4().hex[:12]
    await storage.record_incident(storage.IncidentMeta(
        run_id=incident_id, user_id=repo.user_id, repo_id=repo.id,
        source=source, status="DISPATCHED",
    ))
    try:
        await github_app.dispatch_workflow(
            installation_id=repo.installation_id,
            full_name=repo.full_name,
            event_type="shotgun-run",
            client_payload={
                "incident_id": incident_id,
                "target_url": suspect_url,
                "source": source,
                "symptom": symptom,
            },
        )
        logger.info("webhook: dispatched %s for incident %s on %s",
                    source, incident_id, repo.full_name)
    except Exception as exc:
        logger.error("webhook: dispatch failed for %s — %s", repo.full_name, exc)
