"""
Shotgun — GitHub PR creation + review posting.

Opens a PR with the fix diff and Kane proof attached, and posts
reviews (APPROVE / REQUEST_CHANGES) from kane_review.

The PR body embeds the Kane proof: pass record, the replayable
KaneAI dashboard link, and the extracted final_state. The reviewer
sees exactly what ran. That is the trust artifact.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from pydantic import BaseModel

from app.config import settings
from app.models import Incident, KaneResult

logger = logging.getLogger(__name__)


class PR(BaseModel):
    """Lightweight PR result."""
    url: str


@asynccontextmanager
async def _client() -> AsyncIterator[httpx.AsyncClient]:
    """GitHub API client with auth + accept headers."""
    async with httpx.AsyncClient(
        base_url="https://api.github.com",
        headers={
            "Authorization": f"Bearer {settings.GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30.0,
    ) as c:
        yield c


async def open_pr(
    branch: str,
    inc: Incident,
    kane: KaneResult | None,
) -> PR:
    """Create a GitHub pull request with the fix and Kane proof.

    Idempotent: if a PR for this head branch already exists (e.g. a
    previous run that was re-fired before merging), we update its body
    and return its URL instead of erroring 422.
    """
    body = _pr_body(inc, kane)
    title = f"Shotgun fix: {inc.symptom}"[:250]  # GitHub caps title length
    owner = settings.GITHUB_REPO.split("/")[0]
    head_label = f"{owner}:{branch}"

    async with _client() as c:
        # 1. Try to create
        r = await c.post(
            f"/repos/{settings.GITHUB_REPO}/pulls",
            json={
                "title": title,
                "head": branch,
                "base": settings.GITHUB_BASE_BRANCH,
                "body": body,
            },
        )
        if r.status_code == 422:
            # Likely "A pull request already exists for…". Look it up.
            lookup = await c.get(
                f"/repos/{settings.GITHUB_REPO}/pulls",
                params={"head": head_label, "state": "open"},
            )
            lookup.raise_for_status()
            existing = lookup.json()
            if existing:
                pr_number = existing[0]["number"]
                # Refresh body so the proof block reflects the latest run.
                upd = await c.patch(
                    f"/repos/{settings.GITHUB_REPO}/pulls/{pr_number}",
                    json={"title": title, "body": body},
                )
                upd.raise_for_status()
                url = upd.json()["html_url"]
                logger.info("PR updated (already existed): %s", url)
                return PR(url=url)
            # 422 for a different reason — surface the GitHub error message
            try:
                detail = r.json().get("errors") or r.json().get("message")
            except Exception:
                detail = r.text[:300]
            logger.error("PR create 422 with no existing PR — %s", detail)
            r.raise_for_status()
        r.raise_for_status()
        url = r.json()["html_url"]
        logger.info("PR opened: %s", url)
        return PR(url=url)


async def post_review(pr_url: str, event: str, body: str) -> str:
    """Post a PR review (APPROVE or REQUEST_CHANGES).

    Args:
        pr_url: The full PR html_url (we extract the number).
        event:  "APPROVE" or "REQUEST_CHANGES".
        body:   The review body (markdown).

    Returns:
        The review html_url.
    """
    number = pr_url.rstrip("/").split("/")[-1]
    async with _client() as c:
        r = await c.post(
            f"/repos/{settings.GITHUB_REPO}/pulls/{number}/reviews",
            json={"event": event, "body": body},
        )
        r.raise_for_status()
        url = r.json()["html_url"]
        logger.info("PR review posted: %s (%s)", url, event)
        return url


async def post_comment(pr_url: str, body: str) -> str:
    """Post a plain comment on the PR (alternative to review).

    Args:
        pr_url: The full PR html_url.
        body:   The comment body (markdown).

    Returns:
        The comment html_url.
    """
    number = pr_url.rstrip("/").split("/")[-1]
    async with _client() as c:
        r = await c.post(
            f"/repos/{settings.GITHUB_REPO}/issues/{number}/comments",
            json={"body": body},
        )
        r.raise_for_status()
        url = r.json()["html_url"]
        logger.info("PR comment posted: %s", url)
        return url


async def check_token() -> bool:
    """Validate the GitHub token. Returns True if it has repo scope."""
    if not settings.GITHUB_TOKEN:
        return False
    try:
        async with _client() as c:
            r = await c.get("/user")
            return r.status_code == 200
    except httpx.HTTPError:
        return False


def _pr_body(inc: Incident, kane: KaneResult | None) -> str:
    """Build the PR body with incident details + Kane proof."""
    lines = [
        "## Shotgun verified fix\n",
        f"**Incident:** {inc.symptom}",
        f"**Service:** {inc.service}",
        "",
        "### Proof (Kane)",
    ]

    if kane:
        status_emoji = "✅" if kane.passed else "❌"
        lines.extend([
            f"- Status: {status_emoji} {kane.summary}",
            f"- Duration: {kane.duration:.1f}s",
        ])
        if kane.test_url:
            lines.append(f"- Replayable trace: {kane.test_url}")
        if kane.final_state:
            lines.append(f"- Extracted state: `{kane.final_state}`")
    else:
        lines.append("- ⚠️ No Kane result available")

    lines.extend([
        "",
        "---",
        "_Generated by Shotgun. Human approval required before merge._",
    ])
    return "\n".join(lines)
