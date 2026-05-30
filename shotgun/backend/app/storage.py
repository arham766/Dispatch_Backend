"""
Shotgun — Per-user persistent storage (JSON-backed, Postgres-ready).

Holds the durable state that survives backend restarts:
  * github_installations  — one row per GitHub App installation a user owns
  * monitored_repos       — repos the user has provisioned the workflow on
  * incidents_meta        — light pointer rows (the full event log stays in
                            ``recordings/<run_id>/events.ndjson``)

Schema mirrors the Postgres tables in HLD §20 so the swap is one file:
when ``DATABASE_URL`` lands we replace the body of each helper with an
``asyncpg`` query and the call-sites don't change.

Concurrency:
  Single-process FastAPI; an in-process ``asyncio.Lock`` is enough.
  When we go multi-replica on Render we'll move to Postgres anyway.

On-disk layout:
    data/
    ├── installations.json   — list[Installation]
    ├── monitored_repos.json — list[MonitoredRepo]
    └── incidents.json       — list[IncidentMeta]
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

_lock = asyncio.Lock()


# ── Dataclasses ──────────────────────────────────────


@dataclass
class Installation:
    """A GitHub App installation a Shotgun user owns."""
    user_id: str                       # Firebase uid
    installation_id: int               # GitHub's numeric installation id
    account_login: str                 # the org or user the App is installed under
    account_type: str                  # "User" | "Organization"
    created_at: float = field(default_factory=time.time)


@dataclass
class MonitoredRepo:
    """A repo the user has provisioned the Shotgun workflow on."""
    id: str                            # uuid4 hex, our own
    user_id: str
    installation_id: int
    full_name: str                     # "owner/repo"
    deploy_url: str                    # the live URL Kane hits
    deploy_provider: str = "other"     # render | vercel | netlify | gh_pages | other
    monitoring_enabled: bool = True
    workflow_committed_at: float | None = None
    secrets_provisioned_at: float | None = None
    created_at: float = field(default_factory=time.time)


@dataclass
class IncidentMeta:
    """Pointer row: links a run_id to the repo and user that owns it."""
    run_id: str
    user_id: str
    repo_id: str | None                # nullable for one-off demo runs (no repo)
    source: str                        # "manual" | "webhook_deployment_status" | …
    status: str                        # mirrors RunState.state.value at last update
    created_at: float = field(default_factory=time.time)


# ── Installation helpers ─────────────────────────────


async def get_installations_for_user(user_id: str) -> list[Installation]:
    rows = await _load("installations.json")
    return [Installation(**r) for r in rows if r["user_id"] == user_id]


async def upsert_installation(inst: Installation) -> Installation:
    async with _lock:
        rows = await _load("installations.json")
        rows = [
            r for r in rows
            if not (r["installation_id"] == inst.installation_id and r["user_id"] == inst.user_id)
        ]
        rows.append(asdict(inst))
        await _save("installations.json", rows)
    logger.info("storage: upserted installation %s for user %s", inst.installation_id, inst.user_id)
    return inst


async def delete_installation(user_id: str, installation_id: int) -> None:
    async with _lock:
        rows = await _load("installations.json")
        rows = [
            r for r in rows
            if not (r["installation_id"] == installation_id and r["user_id"] == user_id)
        ]
        await _save("installations.json", rows)


async def get_installation(installation_id: int) -> Installation | None:
    rows = await _load("installations.json")
    for r in rows:
        if r["installation_id"] == installation_id:
            return Installation(**r)
    return None


# ── Monitored repo helpers ───────────────────────────


async def list_repos_for_user(user_id: str) -> list[MonitoredRepo]:
    rows = await _load("monitored_repos.json")
    return [MonitoredRepo(**r) for r in rows if r["user_id"] == user_id]


async def get_repo(repo_id: str) -> MonitoredRepo | None:
    rows = await _load("monitored_repos.json")
    for r in rows:
        if r["id"] == repo_id:
            return MonitoredRepo(**r)
    return None


async def get_repo_by_full_name(full_name: str) -> MonitoredRepo | None:
    rows = await _load("monitored_repos.json")
    for r in rows:
        if r["full_name"].lower() == full_name.lower():
            return MonitoredRepo(**r)
    return None


async def upsert_repo(repo: MonitoredRepo) -> MonitoredRepo:
    async with _lock:
        rows = await _load("monitored_repos.json")
        if not repo.id:
            repo.id = uuid.uuid4().hex[:12]
        rows = [r for r in rows if r["id"] != repo.id and r["full_name"] != repo.full_name]
        rows.append(asdict(repo))
        await _save("monitored_repos.json", rows)
    return repo


async def delete_repo(repo_id: str) -> None:
    async with _lock:
        rows = await _load("monitored_repos.json")
        rows = [r for r in rows if r["id"] != repo_id]
        await _save("monitored_repos.json", rows)


# ── Incident meta helpers ────────────────────────────


async def record_incident(meta: IncidentMeta) -> None:
    async with _lock:
        rows = await _load("incidents.json")
        rows.append(asdict(meta))
        # Keep the file from growing forever; the ground truth lives in
        # recordings/<run_id>/.
        if len(rows) > 1000:
            rows = rows[-1000:]
        await _save("incidents.json", rows)


async def list_incidents_for_user(user_id: str, limit: int = 50) -> list[IncidentMeta]:
    rows = await _load("incidents.json")
    out = [IncidentMeta(**r) for r in rows if r["user_id"] == user_id]
    out.sort(key=lambda x: x.created_at, reverse=True)
    return out[:limit]


async def update_incident_status(run_id: str, status: str) -> None:
    async with _lock:
        rows = await _load("incidents.json")
        for r in rows:
            if r["run_id"] == run_id:
                r["status"] = status
        await _save("incidents.json", rows)


# ── File IO ──────────────────────────────────────────


async def _load(filename: str) -> list[dict[str, Any]]:
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("storage: corrupt %s — %s", filename, exc)
        return []


async def _save(filename: str, rows: list[dict[str, Any]]) -> None:
    path = os.path.join(DATA_DIR, filename)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, default=str)
    os.replace(tmp, path)
