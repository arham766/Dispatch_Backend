"""
Shotgun — GitHub App routes (multi-tenant install + provision flow).

Endpoints (all under /api/github):

  POST  /manifest                — return the GitHub App manifest + URL the
                                   admin should POST to. One-time, only used
                                   before the App exists.
  GET   /manifest/callback       — GitHub redirects here after the admin
                                   creates the App; we exchange the code
                                   for credentials and persist to .env.
  GET   /install                 — redirect the signed-in user to the
                                   GitHub App install URL.
  GET   /installations/callback  — GitHub redirects here after a user
                                   installs the App; we record the
                                   installation under their Firebase uid.
  GET   /installations           — list installations the user owns.
  GET   /installations/{id}/repos
                                  — list repos this installation has access to.
  POST  /provision               — given an installation_id + full_name +
                                   deploy_url, commit the workflow, set
                                   the secrets, register the repo as
                                   monitored. Idempotent.
  POST  /repos/{repo_id}/trigger — fire a repository_dispatch (manual
                                   trigger from the dashboard).
  DELETE /repos/{repo_id}        — stop monitoring a repo (keeps secrets).
"""

from __future__ import annotations

import logging
import os
import secrets
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app.auth import FirebaseUser, current_user, require_user
from app.clients import github_app
from app.config import settings
from app import storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/github", tags=["github"])

# Where the committed workflow lives in the user's repo.
WORKFLOW_PATH = ".github/workflows/shotgun.yml"

# Where we read the workflow template from on disk.
TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "workflows"

# Cookie/state used by the manifest flow (CSRF-style guard).
MANIFEST_STATE_COOKIE = "shotgun_manifest_state"
INSTALL_STATE_COOKIE = "shotgun_install_state"


# ── Models ───────────────────────────────────────────


class ProvisionRequest(BaseModel):
    installation_id: int
    full_name: str
    deploy_url: str
    deploy_provider: str = "other"     # render | vercel | netlify | gh_pages | other


class TriggerRequest(BaseModel):
    """Optional override of the live URL Kane should hit for this run."""
    target_url: str | None = None
    note: str | None = None


# ── Manifest flow (one-time App registration) ────────


@router.get("/manifest")
async def manifest_form() -> HTMLResponse:
    """Return a tiny HTML form that POSTs the manifest to GitHub.

    GitHub requires the manifest to be POSTed as a form field; we can't
    just redirect with a query string. The browser submits this form and
    is taken to github.com/settings/apps/new where the admin clicks one
    button to create the App.

    The ``state`` cookie is a CSRF guard verified at the callback.
    """
    state = secrets.token_urlsafe(24)
    callback = f"{settings.PUBLIC_APP_URL.rstrip('/')}/api/github/manifest/callback"
    webhook = f"{settings.PUBLIC_APP_URL.rstrip('/')}/api/github/webhook"
    m = github_app.manifest(
        callback_url=callback,
        public_url=settings.PUBLIC_APP_URL,
        webhook_url=webhook,
    )

    import json
    body = f"""
    <!doctype html>
    <html><head><title>Register Shotgun GitHub App</title>
    <style>
      body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;
            background:#0f172a;color:#f1f5f9;
            display:grid;place-items:center;min-height:100vh;margin:0}}
      form{{background:rgba(255,255,255,0.05);padding:32px 28px;
            border-radius:14px;max-width:480px;text-align:center}}
      button{{background:#0071e3;color:white;border:0;padding:12px 24px;
              border-radius:10px;font-size:16px;cursor:pointer}}
      p{{color:#94a3b8;margin:0 0 18px 0}}
      code{{background:rgba(255,255,255,0.07);padding:2px 6px;border-radius:4px}}
    </style></head>
    <body><form action="https://github.com/settings/apps/new?state={state}" method="post">
      <h2>Register Shotgun on GitHub</h2>
      <p>One-time setup. You'll be taken to GitHub to confirm.</p>
      <input type="hidden" name="manifest" value='{json.dumps(m)}' />
      <button type="submit">Create GitHub App →</button>
    </form></body></html>
    """
    response = HTMLResponse(content=body)
    response.set_cookie(
        MANIFEST_STATE_COOKIE, state, httponly=True, samesite="lax", max_age=600
    )
    return response


@router.get("/manifest/callback")
async def manifest_callback(request: Request, code: str, state: str | None = None):
    """GitHub redirects here after the admin creates the App.

    We exchange the temporary `code` for the App credentials and append
    them to the backend .env. The admin restarts uvicorn once and the
    App is live for every future tenant.
    """
    cookie_state = request.cookies.get(MANIFEST_STATE_COOKIE)
    if not cookie_state or cookie_state != state:
        raise HTTPException(400, "State mismatch — possible CSRF")

    info = await github_app.exchange_manifest_code(code)

    # Persist credentials to .env so a restart picks them up.
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    appended = (
        f"\n# ── GitHub App credentials (auto-written {time.strftime('%Y-%m-%d %H:%M:%S')}) ──\n"
        f"GITHUB_APP_ID={info['id']}\n"
        f"GITHUB_APP_CLIENT_ID={info['client_id']}\n"
        f"GITHUB_APP_CLIENT_SECRET={info['client_secret']}\n"
        f"GITHUB_APP_WEBHOOK_SECRET={info.get('webhook_secret') or ''}\n"
        f"# PEM is on one line with literal \\n; module unescapes at use time.\n"
        f"GITHUB_APP_PRIVATE_KEY={info['pem'].replace(chr(10), chr(92) + 'n')}\n"
        f"GITHUB_APP_SLUG={info.get('slug', 'shotgun')}\n"
    )
    with open(env_path, "a", encoding="utf-8") as f:
        f.write(appended)

    # Also patch the live settings object so the rest of THIS process
    # already sees the new App (no restart needed for the install flow).
    settings.GITHUB_APP_ID = str(info["id"])
    settings.GITHUB_APP_CLIENT_ID = info["client_id"]
    settings.GITHUB_APP_CLIENT_SECRET = info["client_secret"]
    settings.GITHUB_APP_WEBHOOK_SECRET = info.get("webhook_secret") or ""
    settings.GITHUB_APP_PRIVATE_KEY = info["pem"]

    install_url = info.get("html_url", "") + "/installations/new"
    logger.info("github_app: registered app id=%s slug=%s", info["id"], info.get("slug"))

    return HTMLResponse(f"""
    <!doctype html><html><body style="font-family:sans-serif;padding:40px;
    background:#0f172a;color:#f1f5f9">
    <h2>✅ Shotgun GitHub App registered</h2>
    <p>App ID: <code>{info['id']}</code></p>
    <p>Credentials written to <code>backend/.env</code>.</p>
    <p><a style="color:#60a5fa" href="{install_url}">→ Install it on your first repo</a></p>
    </body></html>
    """)


# ── Install flow (per-user) ─────────────────────────


@router.get("/install")
async def install_redirect(
    request: Request,
    token: str | None = None,
    user: FirebaseUser | None = Depends(current_user),
):
    """Redirect the signed-in user to the App's install URL.

    The frontend navigates here via a plain ``<a href>`` link, so no
    ``Authorization`` header is available.  To link the installation
    back to the Firebase user we accept the token in two ways:

      1. ``Authorization: Bearer <token>`` header (API calls)
      2. ``?token=<id_token>`` query param (browser navigation)

    If neither is present we still redirect — the installation callback
    will prompt the user to sign in and link it then.
    """
    if not settings.GITHUB_APP_ID:
        raise HTTPException(503, "GitHub App not registered yet — visit /api/github/manifest first")

    # If we didn't get the user from the header, try the query param.
    if user is None and token:
        try:
            from app.auth import _init_admin, FirebaseUser as _FU
            app = _init_admin()
            if app:
                from firebase_admin import auth as fb_auth
                claims = fb_auth.verify_id_token(token)
                user = _FU(
                    uid=claims["uid"],
                    email=claims.get("email"),
                    name=claims.get("name"),
                    picture=claims.get("picture"),
                    email_verified=bool(claims.get("email_verified")),
                )
        except Exception as exc:
            logger.warning("install: token query-param verify failed — %s", exc)

    slug = os.environ.get("GITHUB_APP_SLUG", "shotgun")
    install_url = f"https://github.com/apps/{slug}/installations/new"

    state = secrets.token_urlsafe(24)
    response = RedirectResponse(install_url, status_code=302)

    if user:
        response.set_cookie(
            INSTALL_STATE_COOKIE, f"{user.uid}|{state}",
            httponly=True, samesite="lax", max_age=900,
        )
    return response


@router.get("/installations/callback")
async def installation_callback(
    request: Request,
    installation_id: int,
    setup_action: str | None = None,
):
    """GitHub redirects here after the user installs the App.

    We read the cookie set in /install to learn which Firebase user
    completed the install, then persist the installation under their uid.
    """
    cookie = request.cookies.get(INSTALL_STATE_COOKIE) or ""
    user_id = cookie.split("|", 1)[0] if "|" in cookie else None
    if not user_id:
        raise HTTPException(400, "Missing install state — please retry from /onboarding/github")

    try:
        info = await github_app.get_installation_info(installation_id)
    except Exception as exc:
        logger.error("github_app: could not fetch installation %s — %s", installation_id, exc)
        raise HTTPException(502, f"Could not fetch installation: {exc}")

    inst = storage.Installation(
        user_id=user_id,
        installation_id=installation_id,
        account_login=info["account"]["login"],
        account_type=info["account"]["type"],
    )
    await storage.upsert_installation(inst)
    logger.info("github_app: installation %s -> user %s", installation_id, user_id)

    # Redirect to the frontend projects page so the user can pick repos.
    # PUBLIC_DASHBOARD_URL is the frontend origin; PUBLIC_APP_URL is the
    # backend.  Fall through to PUBLIC_APP_URL if the dashboard var isn't set.
    frontend = settings.PUBLIC_DASHBOARD_URL or settings.PUBLIC_APP_URL
    return RedirectResponse(
        f"{frontend}/projects?installation_id={installation_id}",
        status_code=302,
    )


# ── List + provision ─────────────────────────────────


@router.get("/installations")
async def list_user_installations(user: FirebaseUser = Depends(require_user)):
    rows = await storage.get_installations_for_user(user.uid)
    return [
        {
            "installation_id": r.installation_id,
            "account_login": r.account_login,
            "account_type": r.account_type,
            "created_at": r.created_at,
        }
        for r in rows
    ]


@router.get("/installations/{installation_id}/repos")
async def list_repos(
    installation_id: int,
    user: FirebaseUser = Depends(require_user),
):
    """Return GitHub repos this installation has + which we already monitor."""
    # Ownership check
    inst = await storage.get_installation(installation_id)
    if not inst or inst.user_id != user.uid:
        raise HTTPException(404, "Installation not found")

    repos = await github_app.list_installation_repos(installation_id)
    monitored = {
        r.full_name.lower(): r
        for r in await storage.list_repos_for_user(user.uid)
    }
    return [
        {
            "full_name": r["full_name"],
            "private": r["private"],
            "default_branch": r["default_branch"],
            "html_url": r["html_url"],
            "language": r.get("language"),
            "description": r.get("description"),
            "monitored": r["full_name"].lower() in monitored,
            "monitored_id": monitored.get(r["full_name"].lower(), None) and monitored[r["full_name"].lower()].id,
            "deploy_url": monitored.get(r["full_name"].lower(), None) and monitored[r["full_name"].lower()].deploy_url,
        }
        for r in repos
    ]


@router.post("/provision")
async def provision_repo(
    body: ProvisionRequest,
    user: FirebaseUser = Depends(require_user),
):
    """Commit the workflow + set secrets + mark repo as monitored.

    Idempotent: re-running on the same repo updates the workflow file
    (no-op if unchanged) and refreshes secrets. Use this to "re-sync"
    a repo if you rotated credentials.
    """
    inst = await storage.get_installation(body.installation_id)
    if not inst or inst.user_id != user.uid:
        raise HTTPException(404, "Installation not found")

    # Render the workflow template (no per-tenant tokens baked in — they
    # come from Action secrets).
    tpl = (TEMPLATE_DIR / "shotgun.yml").read_text(encoding="utf-8")

    # 1. Commit workflow
    try:
        commit = await github_app.commit_file(
            installation_id=body.installation_id,
            full_name=body.full_name,
            path=WORKFLOW_PATH,
            content=tpl,
            message="ci: install Shotgun monitor workflow",
        )
    except Exception as exc:
        logger.error("provision: commit failed — %s", exc)
        raise HTTPException(502, f"Could not commit workflow: {exc}")

    # 2. Issue a per-repo callback token (lets the Action POST back to us).
    repo_id = uuid.uuid4().hex[:12]
    callback_token = secrets.token_urlsafe(32)
    callback_url = f"{settings.PUBLIC_APP_URL.rstrip('/')}/api/webhooks/loop-event"

    # 3. Set secrets the workflow needs
    secrets_to_set = {
        "SHOTGUN_CALLBACK_URL": callback_url,
        "SHOTGUN_LOOP_TOKEN": callback_token,
        "SHOTGUN_REPO_ID": repo_id,
        # We ship the Kane creds — users don't have to BYOK
        "LT_USERNAME": settings.LT_USERNAME,
        "LT_ACCESS_KEY": settings.LT_ACCESS_KEY,
    }
    for name, value in secrets_to_set.items():
        if not value:
            continue
        try:
            await github_app.set_repo_secret(
                body.installation_id, body.full_name, name, value
            )
        except Exception as exc:
            logger.warning("provision: secret %s failed — %s", name, exc)

    # 4. Persist monitored repo
    now = time.time()
    repo = storage.MonitoredRepo(
        id=repo_id,
        user_id=user.uid,
        installation_id=body.installation_id,
        full_name=body.full_name,
        deploy_url=body.deploy_url,
        deploy_provider=body.deploy_provider,
        workflow_committed_at=now,
        secrets_provisioned_at=now,
    )
    await storage.upsert_repo(repo)
    logger.info("provision: %s monitored under user %s", body.full_name, user.uid)

    return {
        "ok": True,
        "repo_id": repo_id,
        "commit_sha": commit.get("commit", {}).get("sha"),
        "workflow_path": WORKFLOW_PATH,
    }


@router.post("/repos/{repo_id}/trigger")
async def trigger_repo(
    repo_id: str,
    body: TriggerRequest | None = None,
    user: FirebaseUser = Depends(require_user),
):
    """Fire a repository_dispatch event on a monitored repo.

    Bootstraps an in-memory RunState + recording dir *before* we tell
    GitHub to start the workflow, so the user can be redirected to
    /incident?run=<id> instantly and see live timeline ticks ("queued
    in GitHub Actions…") while the runner spins up. Without this the
    WebSocket would 1008-close because the run only exists in durable
    storage, not the in-memory bus the WS reads.

    Also publishes the incident_created notification (email + voice
    call to the on-call engineer) the same way the local-loop path
    does — so a deploy-failure-triggered run gets the same human
    coverage as a manual trigger.
    """
    import os
    from app.config import settings as cfg
    from app.models import Incident, RunState, State
    from app.store import store
    from app import notifications

    repo = await storage.get_repo(repo_id)
    if not repo or repo.user_id != user.uid:
        raise HTTPException(404, "Repo not found")

    incident_id = uuid.uuid4().hex[:12]
    target = (body and body.target_url) or repo.deploy_url
    symptom = (
        (body and body.note)
        or f"Manual trigger on {repo.full_name} → {target}"
    )

    # 1) Bootstrap RunState in the in-memory bus so the WS finds it
    inc = Incident(
        service=repo.full_name.split("/")[-1],
        symptom=symptom,
        suspect_url=target,
        repro_flow="(remote — GitHub Actions)",
        recent_diff_hint=None,
        source="manual",
    )
    run = RunState(incident=inc, state=State.INTAKE)
    run.run_id = incident_id
    store.create(run)

    # 2) Set up recording dir so events get mirrored to NDJSON
    rec_dir = os.path.join(cfg.RECORDINGS_DIR, incident_id)
    os.makedirs(rec_dir, exist_ok=True)
    store.set_recording_dir(incident_id, rec_dir)

    # 3) Publish initial timeline events so the live monitor isn't blank
    await store.publish(incident_id, {
        "event": "state_change",
        "state": "INTAKE",
        "message": f"Incident accepted — {repo.full_name}",
    })
    await store.publish(incident_id, {
        "event": "state_change",
        "state": "DISPATCHED",
        "message": "Queued in GitHub Actions… (workflow will pick up in ~10-30s)",
    })

    # 4) Record durable meta + fire notifications (email + voice)
    await storage.record_incident(storage.IncidentMeta(
        run_id=incident_id, user_id=user.uid, repo_id=repo.id,
        source="manual", status="DISPATCHED",
    ))
    await notifications.publish(run, "incident_created")

    # 5) Fire repository_dispatch — the Action's first /webhooks/loop-event
    #    will then drive REPRODUCE / PATCH / VERIFY events into the bus.
    await github_app.dispatch_workflow(
        installation_id=repo.installation_id,
        full_name=repo.full_name,
        event_type="shotgun-run",
        client_payload={
            "incident_id": incident_id,
            "repo_id": repo.id,
            "target_url": target,
            "source": "manual",
            "symptom": symptom,
        },
    )

    return {"ok": True, "incident_id": incident_id, "target_url": target}


@router.delete("/repos/{repo_id}")
async def stop_monitoring(
    repo_id: str,
    user: FirebaseUser = Depends(require_user),
):
    repo = await storage.get_repo(repo_id)
    if not repo or repo.user_id != user.uid:
        raise HTTPException(404, "Repo not found")
    await storage.delete_repo(repo_id)
    return {"ok": True}


# ── Public status (no auth) ─────────────────────────


@router.get("/status")
async def app_status():
    """Public — tells the frontend whether the App is registered yet."""
    return {
        "app_registered": bool(settings.GITHUB_APP_ID),
        "app_id": settings.GITHUB_APP_ID or None,
        "slug": os.environ.get("GITHUB_APP_SLUG"),
        "manifest_url": f"{settings.PUBLIC_APP_URL}/api/github/manifest",
    }
