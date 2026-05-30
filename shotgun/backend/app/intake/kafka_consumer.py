"""
Shotgun — Kafka intake consumer (§19).

Consumes the ``frontend.incidents`` topic from Upstash/Redpanda,
normalizes messages into Incident objects, and spawns orchestrator
tasks. Idempotent on ``incident_id`` so a redelivery never starts
a second loop.

The consumer runs as a long-lived task started from FastAPI's lifespan.
"""

from __future__ import annotations

import asyncio
import json
import logging

from app.config import settings
from app.intake.normalize import to_incident
from app.models import RunState
from app.orchestrator import run_incident
from app.store import store
from app import recorder, db

logger = logging.getLogger(__name__)


async def consume() -> None:
    """Main Kafka consumer loop.

    Reads from ``settings.KAFKA_TOPIC``, normalizes each message,
    checks idempotency against Postgres, and spawns an orchestrator
    task for new incidents.

    Commits offsets only after the work is accepted.
    """
    try:
        from aiokafka import AIOKafkaConsumer
    except ImportError:
        logger.error("aiokafka not installed — cannot start Kafka consumer")
        return

    logger.info(
        "Kafka consumer starting: topic=%s, group=%s, brokers=%s",
        settings.KAFKA_TOPIC,
        settings.KAFKA_GROUP_ID,
        settings.KAFKA_BROKERS,
    )

    consumer = AIOKafkaConsumer(
        settings.KAFKA_TOPIC,
        bootstrap_servers=settings.KAFKA_BROKERS,
        group_id=settings.KAFKA_GROUP_ID,
        enable_auto_commit=False,
        security_protocol="SASL_SSL",
        sasl_mechanism=settings.KAFKA_SASL_MECHANISM,
        sasl_plain_username=settings.KAFKA_USERNAME,
        sasl_plain_password=settings.KAFKA_PASSWORD,
        value_deserializer=lambda b: json.loads(b),
    )

    await consumer.start()
    logger.info("Kafka consumer started successfully")

    try:
        async for msg in consumer:
            payload = msg.value
            iid = payload.get("incident_id")

            if not iid:
                logger.warning("Kafka: message missing incident_id, skipping")
                await consumer.commit()
                continue

            # Idempotency guard — don't process the same incident twice
            if await db.incident_exists(iid):
                logger.info("Kafka: incident %s already exists, skipping", iid)
                await consumer.commit()
                continue

            logger.info(
                "Kafka: new incident %s — %s",
                iid,
                payload.get("symptom", "unknown"),
            )

            # Normalize and persist
            incident = to_incident(payload)
            await db.insert_incident(iid, incident)

            # Create the run (use the Kafka incident_id as the run_id)
            run = store.create(RunState(incident=incident))
            run.run_id = iid

            # Chain to the previous recorded run
            recorder.link_previous(run)

            # Spawn the orchestrator
            asyncio.create_task(run_incident(run))

            # Commit only after we own the work
            await consumer.commit()

    except Exception as exc:
        logger.error("Kafka consumer error: %s", exc)
        raise
    finally:
        await consumer.stop()
        logger.info("Kafka consumer stopped")
