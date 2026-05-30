"""
Shotgun — /api/me

Returns the verified Firebase user + admin flag + monitored repos.
Acts as the bootstrap call the dashboard makes on load: a single
round-trip tells the UI everything it needs to render.

Admin side-effect:
    On first /me hit, if the caller is an admin and the demo repo
    isn't yet recorded as monitored for them, we auto-create the
    MonitoredRepo row pointing at .env's GITHUB_REPO + STAGING_BASE_URL.
    No GitHub App install required — admins get a working dashboard
    out of the box for demos.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app import storage
from app.auth import FirebaseUser, require_user
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["me"])


@router.get("/me")
async def me(user: FirebaseUser = Depends(require_user)):
    """Bootstrap call: user identity + repos + admin flag."""

    # Admin convenience: pre-provision the demo repo on first sign-in.
    if user.is_admin:
        await _ensure_admin_demo_repo(user)

    repos = await storage.list_repos_for_user(user.uid)
    installations = await storage.get_installations_for_user(user.uid)

    return {
        "uid": user.uid,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "is_admin": user.is_admin,
        "installations": [
            {
                "installation_id": i.installation_id,
                "account_login": i.account_login,
                "account_type": i.account_type,
            }
            for i in installations
        ],
        "monitored_repos": [
            {
                "id": r.id,
                "full_name": r.full_name,
                "deploy_url": r.deploy_url,
                "deploy_provider": r.deploy_provider,
                "monitoring_enabled": r.monitoring_enabled,
                "is_local_loop": (
                    r.installation_id == 0  # 0 == admin/local-loop sentinel
                ),
            }
            for r in repos
        ],
    }


async def _ensure_admin_demo_repo(user: FirebaseUser) -> None:
    """Idempotent: create the demo MonitoredRepo for admin if missing."""
    if not settings.DEMO_REPO_FULL_NAME:
        return
    existing = await storage.list_repos_for_user(user.uid)
    if any(r.full_name == settings.DEMO_REPO_FULL_NAME for r in existing):
        return

    import time, uuid
    now = time.time()
    repo = storage.MonitoredRepo(
        id=uuid.uuid4().hex[:12],
        user_id=user.uid,
        installation_id=0,   # sentinel: 0 = "no GitHub App; use .env PAT + local loop"
        full_name=settings.DEMO_REPO_FULL_NAME,
        deploy_url=settings.DEMO_REPO_DEPLOY_URL or settings.STAGING_BASE_URL,
        deploy_provider="gh_pages",
        monitoring_enabled=True,
        workflow_committed_at=now,        # treat as already provisioned
        secrets_provisioned_at=now,
    )
    await storage.upsert_repo(repo)
    logger.info(
        "me: auto-provisioned demo repo %s for admin %s",
        repo.full_name, user.email,
    )
