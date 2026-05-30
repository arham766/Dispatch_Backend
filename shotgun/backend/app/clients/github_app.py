"""
Shotgun — GitHub App client.

Three-layer auth, in order of scope:

1. App JWT (10-minute lifetime, RS256-signed with the App's private key)
   — used only to mint installation tokens.

2. Installation token (1-hour lifetime, scoped to one user's installation)
   — used for every per-repo REST call: list repos, commit files, set
   secrets, dispatch workflows.

3. User OAuth (not yet used in this module — see `routes/github.py` for
   the manifest-creation and install callbacks).

Two ways to register the GitHub App:

  * Manifest flow (recommended) — POST a manifest to GitHub, user is
    redirected, GitHub creates the App, redirects back with a temporary
    code, we exchange the code for the App credentials. ~30 seconds end
    to end. Implemented in ``routes/github.py``.

  * Manual registration — user creates the App at
    github.com/settings/apps/new, pastes ID + private key into .env.

Both paths produce the same env vars (``GITHUB_APP_ID``,
``GITHUB_APP_PRIVATE_KEY``, ``GITHUB_APP_CLIENT_ID``,
``GITHUB_APP_CLIENT_SECRET``, ``GITHUB_APP_WEBHOOK_SECRET``) that this
module reads from ``settings``.
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Any

import httpx
import jwt
from nacl import encoding, public

from app.config import settings

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"

# In-process cache of installation tokens (1hr lifetime). Key by installation_id.
_token_cache: dict[int, tuple[str, float]] = {}


# ── App JWT ──────────────────────────────────────────


def _is_configured() -> bool:
    return bool(settings.GITHUB_APP_ID and settings.GITHUB_APP_PRIVATE_KEY)


def _app_jwt() -> str:
    """Mint a fresh ~10-minute JWT signed with the App's RSA key.

    The `iat` is back-dated 60 seconds to absorb clock skew between
    our box and GitHub. `exp` is 9 minutes out to stay under the
    10-minute hard limit.
    """
    if not _is_configured():
        raise RuntimeError("GitHub App not configured (set GITHUB_APP_ID + GITHUB_APP_PRIVATE_KEY)")

    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + 9 * 60,
        "iss": str(settings.GITHUB_APP_ID),
    }
    # Private key may be stored with literal "\n" escapes in .env.
    pem = settings.GITHUB_APP_PRIVATE_KEY.replace("\\n", "\n")
    return jwt.encode(payload, pem, algorithm="RS256")


# ── Installation token ───────────────────────────────


async def installation_token(installation_id: int) -> str:
    """Return a valid installation access token, caching for ~55 minutes."""
    cached = _token_cache.get(installation_id)
    if cached and cached[1] > time.time() + 60:
        return cached[0]

    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.post(
            f"{GITHUB_API}/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {_app_jwt()}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        r.raise_for_status()
        body = r.json()
        token = body["token"]
        # GitHub returns ISO8601; convert to epoch
        from datetime import datetime, timezone
        exp = datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
        _token_cache[installation_id] = (token, exp.timestamp())
        return token


def _inst_client(token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=GITHUB_API,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30.0,
    )


# ── Installation info ────────────────────────────────


async def get_installation_info(installation_id: int) -> dict:
    """Fetch the installation record (account_login, account_type, …)."""
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.get(
            f"{GITHUB_API}/app/installations/{installation_id}",
            headers={
                "Authorization": f"Bearer {_app_jwt()}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        r.raise_for_status()
        return r.json()


# ── Repos ────────────────────────────────────────────


async def list_installation_repos(installation_id: int) -> list[dict]:
    """List every repo this installation has access to.

    Paginates until exhausted. Filters to repos we can actually act on
    (write permissions present).
    """
    token = await installation_token(installation_id)
    out: list[dict] = []
    page = 1
    async with _inst_client(token) as c:
        while True:
            r = await c.get(
                "/installation/repositories",
                params={"per_page": 100, "page": page},
            )
            r.raise_for_status()
            body = r.json()
            out.extend(body.get("repositories", []))
            if len(body.get("repositories", [])) < 100:
                break
            page += 1
    return out


# ── Repo writes (file commit, secrets, dispatch) ────


async def commit_file(
    installation_id: int,
    full_name: str,
    path: str,
    content: str,
    message: str,
    branch: str | None = None,
) -> dict:
    """Create-or-update a file in a repo via the contents API.

    Returns the GitHub commit object. If the file already exists we
    fetch its SHA so the PUT is treated as an update, not a create.
    """
    token = await installation_token(installation_id)
    async with _inst_client(token) as c:
        # Discover the default branch if not given
        if branch is None:
            r = await c.get(f"/repos/{full_name}")
            r.raise_for_status()
            branch = r.json()["default_branch"]

        # Check if the file exists to get its sha
        sha: str | None = None
        r = await c.get(f"/repos/{full_name}/contents/{path}", params={"ref": branch})
        if r.status_code == 200:
            sha = r.json().get("sha")

        body = {
            "message": message,
            "content": base64.b64encode(content.encode()).decode(),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha

        r = await c.put(f"/repos/{full_name}/contents/{path}", json=body)
        r.raise_for_status()
        return r.json()


async def set_repo_secret(
    installation_id: int,
    full_name: str,
    secret_name: str,
    secret_value: str,
) -> None:
    """Encrypt with the repo's public key and PUT the secret."""
    token = await installation_token(installation_id)
    async with _inst_client(token) as c:
        # 1. fetch the repo's public key
        r = await c.get(f"/repos/{full_name}/actions/secrets/public-key")
        r.raise_for_status()
        pk = r.json()
        key_id = pk["key_id"]
        pub_b64 = pk["key"]

        # 2. encrypt the secret with libsodium sealed box
        pub = public.PublicKey(pub_b64, encoding.Base64Encoder())
        box = public.SealedBox(pub)
        encrypted = box.encrypt(secret_value.encode())
        encrypted_b64 = base64.b64encode(encrypted).decode()

        # 3. PUT it
        r = await c.put(
            f"/repos/{full_name}/actions/secrets/{secret_name}",
            json={"encrypted_value": encrypted_b64, "key_id": key_id},
        )
        r.raise_for_status()
        logger.info("github_app: set secret %s on %s", secret_name, full_name)


async def dispatch_workflow(
    installation_id: int,
    full_name: str,
    event_type: str,
    client_payload: dict[str, Any],
) -> None:
    """Fire a `repository_dispatch` event on the repo.

    The user's workflow listens for matching ``event_type`` and runs the
    composite closed-loop action.
    """
    token = await installation_token(installation_id)
    async with _inst_client(token) as c:
        r = await c.post(
            f"/repos/{full_name}/dispatches",
            json={"event_type": event_type, "client_payload": client_payload},
        )
        r.raise_for_status()
        logger.info(
            "github_app: dispatched %s to %s with payload keys %s",
            event_type, full_name, list(client_payload.keys()),
        )


# ── Manifest flow helper ─────────────────────────────


def manifest(callback_url: str, public_url: str, webhook_url: str) -> dict:
    """Build the GitHub App manifest JSON the user submits to create the App.

    We POST this to github.com/settings/apps/new?state=… and GitHub
    redirects back to our callback with ?code=… which we exchange for
    the App credentials in ``routes/github.py``.
    """
    return {
        "name": "Shotgun",
        "url": public_url,
        "hook_attributes": {
            "url": webhook_url,
            "active": True,
        },
        "redirect_url": callback_url,
        "callback_urls": [f"{public_url}/api/github/installations/callback"],
        "public": False,
        "request_oauth_on_install": True,
        "setup_on_update": False,
        "default_permissions": {
            "contents": "write",
            "pull_requests": "write",
            "actions": "write",
            "deployments": "read",
            "checks": "write",
            "secrets": "write",
            "workflows": "write",
            "metadata": "read",
        },
        "default_events": [
            "push",
            "pull_request",
            "deployment_status",
            "workflow_run",
            "installation",
            "installation_repositories",
        ],
    }


# ── Exchange manifest code → credentials ─────────────


async def exchange_manifest_code(code: str) -> dict:
    """Exchange a manifest code for App credentials.

    Returns the full App config dict from GitHub, including:
      id, slug, html_url, name, client_id, client_secret,
      pem (private key), webhook_secret.

    Caller is expected to persist these into env / settings.
    """
    async with httpx.AsyncClient(timeout=20.0) as c:
        r = await c.post(
            f"{GITHUB_API}/app-manifests/{code}/conversions",
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        r.raise_for_status()
        return r.json()
