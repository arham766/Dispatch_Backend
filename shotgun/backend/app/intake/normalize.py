"""
Shotgun — Incident intake normalizer.

Maps PagerDuty, Sentry, Kafka (CEO contract), or plain JSON payloads
into a normalized ``Incident`` object.

Kafka message contract (CEO spec):
    incident_id, service, symptom, url, repo, commit_sha,
    severity, repro_hint, detected_at
"""

from __future__ import annotations

import logging
from app.models import Incident

logger = logging.getLogger(__name__)


def to_incident(payload: dict) -> Incident:
    """Normalize an arbitrary incident payload into an Incident.

    Supported formats:
        - PagerDuty webhook (``incident.trigger``)
        - Sentry webhook (``event_alert.triggered``)
        - Kafka / Dispatch (CEO contract)
        - Plain JSON (passthrough)

    Returns:
        A normalized ``Incident`` ready for the orchestrator.
    """
    # ── PagerDuty ─────────────────────────────────────
    if "incident" in payload and "trigger_summary_data" in payload.get("incident", {}):
        pd = payload["incident"]
        trigger = pd.get("trigger_summary_data", {})
        return Incident(
            service=pd.get("service", {}).get("name", "unknown"),
            symptom=trigger.get("description", pd.get("title", "Unknown incident")),
            suspect_url=trigger.get("client_url", ""),
            repro_flow=_guess_flow(pd.get("service", {}).get("name", "")),
            recent_diff_hint=None,
            source="pagerduty",
        )

    # ── Sentry ────────────────────────────────────────
    if "event" in payload and "issue" in payload.get("data", {}):
        event = payload.get("data", {})
        issue = event.get("issue", {})
        return Incident(
            service=issue.get("project", {}).get("slug", "unknown"),
            symptom=issue.get("title", "Unknown error"),
            suspect_url=issue.get("permalink", ""),
            repro_flow=_guess_flow(issue.get("project", {}).get("slug", "")),
            recent_diff_hint=None,
            source="sentry",
        )

    # ── Kafka / Dispatch (CEO contract) ───────────────
    if "incident_id" in payload and "repro_hint" in payload:
        return Incident(
            service=payload.get("service", "unknown"),
            symptom=payload.get("symptom", "Unknown"),
            suspect_url=payload.get("url", ""),
            repro_flow=_lookup_flow(payload.get("repro_hint", "")),
            recent_diff_hint=payload.get("commit_sha"),
            source="kafka",
        )

    # ── Plain JSON (passthrough) ──────────────────────
    try:
        return Incident(**payload)
    except Exception as exc:
        logger.error("Failed to parse incident payload: %s — %s", payload, exc)
        raise ValueError(f"Unrecognized incident format: {exc}") from exc


def _guess_flow(service_name: str) -> str:
    """Guess the testmd flow file path from a service name.

    Falls back to the default checkout flow if no match is found.
    """
    flow_map = {
        "checkout": "flows/checkout_test.md",
        "payment": "flows/checkout_test.md",
        "login": "flows/login_test.md",
        "search": "flows/search_test.md",
    }
    service_lower = service_name.lower()
    for key, flow in flow_map.items():
        if key in service_lower:
            return flow
    return "flows/checkout_test.md"  # default


def _lookup_flow(repro_hint: str) -> str:
    """Look up the testmd flow from a Kafka repro_hint.

    The hint is a human-readable description like "checkout flow";
    map it to the committed flow file.
    """
    return _guess_flow(repro_hint)
