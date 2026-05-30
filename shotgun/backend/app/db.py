"""
Shotgun — Postgres datastore layer (§20).

Provides async helpers over an asyncpg pool for incidents, runs,
and artifacts. Write-through pattern: the orchestrator mirrors each
significant transition here so Render Postgres always reflects live
state for the dashboard.

Schema:
    incidents  — one row per incident (also the run_id)
    runs       — one row per Kane run (repro / verify / review)
    artifacts  — before/after screenshots, replays, diffs
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# Pool will be initialized at startup if DATABASE_URL is set
_pool = None


async def init_pool() -> None:
    """Initialize the asyncpg connection pool."""
    global _pool
    if not settings.DATABASE_URL:
        logger.info("No DATABASE_URL set — skipping Postgres")
        return

    import asyncpg
    dsn = settings.DATABASE_URL
    # asyncpg needs postgresql:// not postgresql+asyncpg://
    if "+asyncpg" in dsn:
        dsn = dsn.replace("+asyncpg", "")

    _pool = await asyncpg.create_pool(
        dsn,
        min_size=1,
        max_size=settings.DB_POOL_SIZE,
    )
    logger.info("Postgres pool initialized (max_size=%d)", settings.DB_POOL_SIZE)

    # Run migrations
    await _ensure_schema()


async def close_pool() -> None:
    """Close the connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Postgres pool closed")


async def _ensure_schema() -> None:
    """Create tables if they don't exist."""
    if not _pool:
        return
    async with _pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                id text PRIMARY KEY,
                service text,
                symptom text,
                url text,
                repo text,
                commit_sha text,
                severity text,
                status text,
                diagnosis text,
                decision text,
                pr_url text,
                created_at timestamptz DEFAULT now(),
                updated_at timestamptz
            );

            CREATE TABLE IF NOT EXISTS runs (
                id text PRIMARY KEY,
                incident_id text REFERENCES incidents(id),
                phase text,
                status text,
                attempt int,
                run_dir text,
                replay_url text,
                screenshot text,
                created_at timestamptz DEFAULT now()
            );

            CREATE TABLE IF NOT EXISTS artifacts (
                id serial PRIMARY KEY,
                incident_id text REFERENCES incidents(id),
                kind text,
                uri text
            );
        """)
        logger.info("Postgres schema ensured")


# ── CRUD helpers ──────────────────────────────────────


async def incident_exists(incident_id: str) -> bool:
    """Check if an incident already exists (idempotency guard for Kafka)."""
    if not _pool:
        return False
    async with _pool.acquire() as conn:
        row = await conn.fetchval(
            "SELECT 1 FROM incidents WHERE id = $1", incident_id
        )
        return row is not None


async def insert_incident(incident_id: str, incident: Any) -> None:
    """Insert a new incident row."""
    if not _pool:
        return
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO incidents (id, service, symptom, url, status, created_at)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (id) DO NOTHING
            """,
            incident_id,
            incident.service,
            incident.symptom,
            incident.suspect_url,
            "INTAKE",
            datetime.now(timezone.utc),
        )


async def update_status(
    incident_id: str,
    status: str,
    **fields: Any,
) -> None:
    """Update the incident status and optional fields."""
    if not _pool:
        return
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE incidents
            SET status = $1, updated_at = $2, pr_url = COALESCE($3, pr_url)
            WHERE id = $4
            """,
            status,
            datetime.now(timezone.utc),
            fields.get("pr_url"),
            incident_id,
        )


async def insert_run(
    run_id: str,
    incident_id: str,
    phase: str,
    kane_result: Any,
) -> None:
    """Insert a Kane run record."""
    if not _pool:
        return
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO runs (id, incident_id, phase, status, attempt, run_dir, replay_url, screenshot)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            run_id,
            incident_id,
            phase,
            "passed" if kane_result.passed else "failed",
            getattr(kane_result, "exit_code", 0),
            kane_result.run_dir,
            kane_result.test_url,
            kane_result.screenshot_path,
        )


async def add_artifact(
    incident_id: str,
    kind: str,
    uri: str,
) -> None:
    """Register an artifact (before_shot, after_shot, diff, etc.)."""
    if not _pool:
        return
    async with _pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO artifacts (incident_id, kind, uri) VALUES ($1, $2, $3)",
            incident_id, kind, uri,
        )


async def get_incident(incident_id: str) -> dict | None:
    """Fetch a single incident by ID."""
    if not _pool:
        return None
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM incidents WHERE id = $1", incident_id
        )
        return dict(row) if row else None


async def list_incidents(limit: int = 50, offset: int = 0) -> list[dict]:
    """List incidents, most recent first."""
    if not _pool:
        return []
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM incidents ORDER BY created_at DESC LIMIT $1 OFFSET $2",
            limit, offset,
        )
        return [dict(r) for r in rows]
