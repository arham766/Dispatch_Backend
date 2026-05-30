"""
Shotgun — FastAPI application entry point.

Registers all routes, configures CORS, mounts static files for
screenshots, and manages the application lifespan (Kafka consumer,
DB pool).

Run with:
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routes import (
    incidents,
    stream,
    health,
    me as me_routes,
    github as github_routes,
    webhooks_github,
    webhooks_loop,
)

# ── Logging ───────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-24s │ %(levelname)-5s │ %(message)s",
    datefmt="%H:%M:%S",
)
# Make our loggers verbose — Kane/Kiro/Orchestrator detail
for _ln in ("app", "app.clients.kane", "app.clients.kiro", "app.orchestrator",
            "app.store", "app.recorder", "app.routes"):
    logging.getLogger(_ln).setLevel(logging.DEBUG)
# Suppress noisy third-party loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("shotgun")


# ── Lifespan ──────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup/shutdown of long-running services."""
    logger.info("═══ Shotgun starting ═══")
    logger.info("  Staging URL : %s", settings.STAGING_BASE_URL)
    logger.info("  Kiro mode   : %s", settings.KIRO_MODE)
    logger.info("  Intake mode : %s", settings.INTAKE_MODE)
    logger.info("  Retry budget: %d", settings.RETRY_BUDGET)
    logger.info("  Review      : %s", "ON" if settings.KANE_REVIEW_ENABLED else "OFF")

    # Start Kafka consumer if configured
    if settings.INTAKE_MODE == "kafka" and settings.KAFKA_BROKERS:
        import asyncio
        from app.intake.kafka_consumer import consume
        asyncio.create_task(consume())
        logger.info("  Kafka consumer started on topic: %s", settings.KAFKA_TOPIC)

    # Initialize Postgres pool if configured
    if settings.DATABASE_URL:
        try:
            from app import db
            await db.init_pool()
            logger.info("  Postgres pool initialized")
        except Exception as exc:
            logger.warning("  Postgres pool failed: %s", exc)

    yield

    # Shutdown
    if settings.DATABASE_URL:
        try:
            from app import db
            await db.close_pool()
        except Exception:
            pass

    logger.info("═══ Shotgun stopped ═══")


# ── App ───────────────────────────────────────────────

app = FastAPI(
    title="Shotgun",
    description=(
        "On-call copilot that diagnoses, fixes, and proves the fix "
        "in a Kiro → Kane closed loop."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow the Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register route modules
app.include_router(incidents.router)
app.include_router(stream.router)
app.include_router(health.router)
app.include_router(me_routes.router)
app.include_router(github_routes.router)
app.include_router(webhooks_github.router)
app.include_router(webhooks_loop.router)

# Mount recordings directory for screenshot serving
import os
recordings_dir = settings.RECORDINGS_DIR
if not os.path.isdir(recordings_dir):
    os.makedirs(recordings_dir, exist_ok=True)
app.mount("/screenshots", StaticFiles(directory=recordings_dir), name="screenshots")

logger.info("Routes registered: /incidents, /incidents/{id}/stream, /healthz")
