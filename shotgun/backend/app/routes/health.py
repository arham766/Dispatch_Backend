"""
Shotgun — Health check endpoint.

GET /healthz checks:
    - Kane CLI auth (shells ``kane-cli whoami``)
    - GitHub token validity
    - Kiro mode configuration
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from app.clients import kane, github_pr
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz():
    """Liveness check. Verifies external dependencies are reachable.

    Returns a JSON object with the status of each dependency:
        {
            "kane": true/false,
            "github": true/false,
            "kiro": {"mode": "hook", "workdir": "..."},
            "status": "healthy" / "degraded"
        }
    """
    kane_ok = await kane.check_auth()
    github_ok = await github_pr.check_token()
    kiro_info = {
        "mode": settings.KIRO_MODE,
        "workdir": settings.KIRO_WORKDIR,
    }

    all_ok = kane_ok and github_ok
    status = "healthy" if all_ok else "degraded"

    if not kane_ok:
        logger.warning("healthz: Kane CLI auth failed")
    if not github_ok:
        logger.warning("healthz: GitHub token invalid or missing")

    return {
        "kane": kane_ok,
        "github": github_ok,
        "kiro": kiro_info,
        "status": status,
        "settings": {
            "retry_budget": settings.RETRY_BUDGET,
            "confirmation_runs": settings.CONFIRMATION_RUNS,
            "kane_review_enabled": settings.KANE_REVIEW_ENABLED,
            "intake_mode": settings.INTAKE_MODE,
            "record_loops": settings.RECORD_LOOPS,
        },
    }
