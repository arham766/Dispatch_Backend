"""
Shotgun — AgentPhone voice layer.

Wraps `POST https://api.agentphone.ai/v1/calls` (the real endpoint we
discovered by probing the OpenAPI). Calls are placed by an AgentPhone
"agent" (a hosted LLM with a phone number) — we override the
`systemPrompt` per call so the same agent can be repurposed for Shotgun
without changing the agent's permanent configuration.

Auth: Bearer ``AGENTPHONE_API_KEY``.

Request body (CreateOutboundCallRequest):
    {
      "agentId":        "cm…",            # required, agent in user's acct
      "toNumber":       "+1…",            # required, E.164
      "fromNumberId":   "num_…" | null,   # optional caller ID; first if omitted
      "initialGreeting":"Shotgun here…",  # first line spoken on pick-up
      "systemPrompt":   "You are…",       # scopes the conversation
      "variables":      {"k":"v"}         # template values for the prompt
    }

Two public modes:
  * place_notification_call — one-way brief, agent hangs up after greeting
                              + a couple of clarifying lines if user asks
  * place_decision_call     — two-way; agent prompts for "fix" or "dismiss"
                              and POSTs the verdict to
                              /webhooks/agentphone/decision

Everything is best-effort: a failed call NEVER raises, it just logs.
The orchestrator loop must keep moving even if voice is down.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.config import settings
from app.store import store

logger = logging.getLogger(__name__)

# ── System-prompt builders ───────────────────────────


_NOTIFICATION_SYSTEM_PROMPT = (
    "You are Shotgun, an on-call copilot AI. You are calling the engineer "
    "to brief them on an incident their service has just hit. Be concise, "
    "calm, and factual. Crucially, if the engineer asks a question, "
    "maintain the context of their previous questions and provide a helpful, "
    "context-aware answer using the briefing details. Do not unnecessarily deflect "
    "or tell them to check the dashboard unless you genuinely lack the information. "
    "End the call politely after delivering the brief unless the engineer keeps the "
    "conversation going."
)

_DECISION_SYSTEM_PROMPT = (
    "You are Shotgun, an on-call copilot AI. A fix has been verified by "
    "Kane and is ready to ship as a pull request. Your job on this call is "
    "to (1) state the verdict clearly, (2) ask the engineer 'Should I open "
    "the pull request?', (3) listen for a yes/no answer (which may also "
    "be phrased as 'ship it' / 'fix' or 'dismiss' / 'stand down'), and "
    "(4) confirm what you heard before hanging up. "
    "If the engineer asks questions about the fix, provide helpful context "
    "based on the incident and patch details instead of deflecting. "
    "If they ask for time to review, treat that as 'dismiss' for now — "
    "they can approve later in the dashboard."
)


# ── Public API ───────────────────────────────────────


async def place_call(
    incident_id: str,
    say: str,
    *,
    to: str | None = None,
    expect: str = "ack",
    variables: dict[str, str] | None = None,
) -> None:
    """Place an outbound call via AgentPhone /v1/calls.

    Args:
        incident_id: Correlation id (also the run_id).
        say:         The greeting the agent speaks on pick-up.
        to:          Override destination phone (defaults to ONCALL_PHONE).
        expect:      "ack" — one-way; "decision" — two-way fix/dismiss.
        variables:   Substituted into ``{{var}}`` placeholders in the prompt.

    Side effects:
        Logs the provider's response code + body so a 4xx or 5xx is
        diagnosable in the backend log. Never raises.
    """
    if not settings.AGENTPHONE_ENABLED:
        logger.info("AgentPhone disabled — skipping call for %s", incident_id)
        return
    if not (settings.AGENTPHONE_API_KEY and settings.AGENTPHONE_AGENT_ID):
        logger.warning(
            "AgentPhone misconfigured (api_key=%s agent_id=%s) — skipping",
            bool(settings.AGENTPHONE_API_KEY),
            bool(settings.AGENTPHONE_AGENT_ID),
        )
        return

    destination = to or settings.ONCALL_PHONE
    if not destination:
        logger.warning("AgentPhone: no destination phone (ONCALL_PHONE empty)")
        return

    payload: dict[str, Any] = {
        "agentId": settings.AGENTPHONE_AGENT_ID,
        "toNumber": destination,
        "initialGreeting": say,
        "systemPrompt": (
            _DECISION_SYSTEM_PROMPT if expect == "decision"
            else _NOTIFICATION_SYSTEM_PROMPT
        ),
    }
    if settings.AGENTPHONE_FROM_NUMBER_ID:
        payload["fromNumberId"] = settings.AGENTPHONE_FROM_NUMBER_ID
    if variables:
        payload["variables"] = variables

    url = f"{settings.AGENTPHONE_API_URL.rstrip('/')}/v1/calls"
    logger.info(
        "AgentPhone: POST %s → %s (incident=%s, expect=%s, agent=%s)",
        url, destination, incident_id, expect, settings.AGENTPHONE_AGENT_ID,
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(
                url,
                headers={
                    "Authorization": f"Bearer {settings.AGENTPHONE_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if 200 <= r.status_code < 300:
            try:
                body = r.json()
            except Exception:
                body = {"_raw": r.text[:200]}
            logger.info(
                "AgentPhone: call queued for %s — call_id=%s status=%d",
                incident_id, body.get("id") or body.get("callId") or "?",
                r.status_code,
            )
        else:
            logger.warning(
                "AgentPhone: provider returned %d for %s → %s",
                r.status_code, incident_id, r.text[:300],
            )
    except httpx.HTTPError as exc:
        logger.error("AgentPhone: HTTP failure for %s — %s", incident_id, exc)


async def place_notification_call(incident_id: str, say: str) -> None:
    """One-way brief — agent speaks, can answer follow-ups, hangs up."""
    await place_call(incident_id, say, expect="ack")


async def place_decision_call(incident_id: str, say: str) -> None:
    """Two-way HUMAN_GATE — agent waits for fix/dismiss decision."""
    await place_call(incident_id, say, expect="decision")


# ── Voice-gate await (only used by orchestrator when CALLING is wired) ──


async def wait_for_decision(
    incident_id: str,
    timeout: int | None = None,
) -> str:
    """Block until the spoken decision arrives via webhook.

    Returns "fix", "dismiss", or "no_answer" on timeout.
    """
    if timeout is None:
        timeout = settings.AGENTPHONE_NO_ANSWER_TIMEOUT
    try:
        decision = await asyncio.wait_for(
            store.wait_for_decision(incident_id), timeout=timeout,
        )
        logger.info("AgentPhone: decision for %s → %s", incident_id, decision)
        return decision
    except asyncio.TimeoutError:
        logger.warning(
            "AgentPhone: no answer for %s after %ds → escalating",
            incident_id, timeout,
        )
        return "no_answer"
