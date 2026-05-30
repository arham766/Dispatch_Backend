"""
Shotgun — Notifications fan-out (Resend email + AgentPhone voice).

The orchestrator never talks to email/voice providers directly. It calls
``notify.publish(run, kind, **ctx)`` and this module routes to whatever
channels are enabled in settings. That way enabling/disabling a provider
is a single env flag, and the same lifecycle event drives every channel.

Channels:
  * Resend  — HTML email per RESEND_ENABLED + RESEND_API_KEY
  * AgentPhone — outbound voice call per AGENTPHONE_ENABLED

Event kinds (the ``kind`` argument):
  * incident_created     — first contact, "we are on it"
  * kane_red_confirmed   — reproduced, working on fix
  * kane_green           — fix verified, awaiting approval
  * pr_opened            — PR live, link inside
  * preview_ready        — branch preview deployed
  * escalated            — budget exhausted, human takeover

Idempotency:
  In-memory ``_sent`` set keyed by (run_id, kind) prevents double-sends
  if the orchestrator re-emits an event (e.g. on review re-loop). When
  Postgres lands the same logic moves into the ``notifications`` table.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import settings
from app.models import RunState

logger = logging.getLogger(__name__)

# (run_id, kind) → already-sent. Wiped on process restart; Postgres-backed
# dedupe lands in Phase 2 when we ship the schema.
_sent: set[tuple[str, str]] = set()


# ── Public entry point ───────────────────────────────


async def publish(run: RunState, kind: str, **ctx: Any) -> None:
    """Fan a lifecycle event out to every enabled channel.

    Safe to await even when all channels are disabled — becomes a no-op.
    Failures in one channel never block the others (or the orchestrator);
    each provider is awaited individually with isolated error handling.
    """
    key = (run.run_id, kind)
    if key in _sent:
        return
    _sent.add(key)

    logger.info("notify: run=%s kind=%s ctx=%s", run.run_id, kind, list(ctx.keys()))

    tasks: list = []
    if settings.RESEND_ENABLED and settings.RESEND_API_KEY:
        tasks.append(_send_email(run, kind, ctx))
    if settings.AGENTPHONE_ENABLED and settings.AGENTPHONE_API_KEY:
        # Voice calls fire only when we have something substantive to say.
        # incident_created has no info beyond "an incident hit" — emails
        # are better for that. We call once Kane has actually reproduced
        # the bug (kane_red_confirmed) so the agent can read out the
        # real failure summary, and again at decision time.
        if kind in {
            "kane_red_confirmed",   # "Found bug X, Kiro is fixing now"
            "kane_green",           # "Fix verified — open the PR?" (decision)
            "pr_opened",            # "PR #N is live"
            "escalated",            # "Could not converge"
        }:
            tasks.append(_place_call(run, kind, ctx))

    if not tasks:
        return

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for r in results:
        if isinstance(r, Exception):
            logger.warning("notify: provider failed — %s", r)


# ── Resend (email) ───────────────────────────────────


async def _send_email(run: RunState, kind: str, ctx: dict) -> None:
    """Render + send the transactional email for this event kind."""
    try:
        import resend
    except ImportError:
        logger.error("notify: resend not installed (pip install resend)")
        return

    resend.api_key = settings.RESEND_API_KEY

    subject, html = _render_email(run, kind, ctx)
    to = ctx.get("recipient") or settings.RESEND_NOTIFY
    if not to:
        logger.warning("notify: no recipient for email (RESEND_NOTIFY empty)")
        return

    def _send():
        return resend.Emails.send({
            "from": settings.RESEND_FROM,
            "to": to,
            "subject": subject,
            "html": html,
        })

    # resend SDK is sync — push to a thread so the loop never blocks.
    res = await asyncio.to_thread(_send)
    logger.info("notify: email sent kind=%s id=%s to=%s", kind, res.get("id"), to)


def _render_email(run: RunState, kind: str, ctx: dict) -> tuple[str, str]:
    """Pick subject + HTML body per event kind."""
    inc = run.incident
    base_style = (
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
        "max-width:560px;margin:0 auto;padding:24px;color:#1d1d1f"
    )
    header = (
        f'<div style="{base_style}">'
        f'<h2 style="margin:0 0 8px 0">Shotgun · {inc.service}</h2>'
        f'<p style="color:#6e6e73;margin:0 0 16px 0">{inc.symptom}</p>'
    )
    footer = (
        f'<hr style="border:none;border-top:1px solid #d2d2d7;margin:20px 0">'
        f'<p style="color:#86868b;font-size:12px">Run <code>{run.run_id}</code> · '
        f'<a href="{settings.PUBLIC_APP_URL}?run={run.run_id}">Live monitor</a></p>'
        f'</div>'
    )

    if kind == "incident_created":
        return (
            f"[Shotgun] {inc.service}: incident received",
            header
            + '<p>An incident just landed and Shotgun is on it.</p>'
            + '<p><strong>Next:</strong> Kane will try to reproduce the failure '
              'against your live deploy. Watch live →</p>'
            + footer,
        )
    if kind == "kane_red_confirmed":
        return (
            f"[Shotgun] {inc.service}: bug confirmed, fixing now",
            header
            + '<p>✅ <strong>Kane reproduced the bug.</strong></p>'
            + f'<blockquote style="border-left:3px solid #d2d2d7;padding-left:12px;'
              f'color:#1d1d1f">{ctx.get("summary", "")[:600]}</blockquote>'
            + '<p>Kiro is now writing a fix. You will get another email when it'
              ' is verified.</p>'
            + footer,
        )
    if kind == "kane_green":
        return (
            f"[Shotgun] {inc.service}: fix verified ✅",
            header
            + '<p>✅ <strong>Kane verified the fix passes the regression flow.</strong></p>'
            + f'<p>Confirmed {ctx.get("confirmation_runs", 0)}× green from cache. '
              'A PR is ready to open with your approval.</p>'
            + f'<p><a href="{settings.PUBLIC_APP_URL}?run={run.run_id}" '
              'style="display:inline-block;padding:10px 16px;background:#0071e3;'
              'color:white;text-decoration:none;border-radius:8px">'
              'Open the PR →</a></p>'
            + footer,
        )
    if kind == "pr_opened":
        pr_url = ctx.get("pr_url", "#")
        return (
            f"[Shotgun] {inc.service}: PR opened",
            header
            + '<p>📝 The pull request is live with Kane proof attached.</p>'
            + f'<p><a href="{pr_url}" '
              'style="display:inline-block;padding:10px 16px;background:#0071e3;'
              f'color:white;text-decoration:none;border-radius:8px">View PR →</a></p>'
            + footer,
        )
    if kind == "preview_ready":
        url = ctx.get("preview_url", "#")
        return (
            f"[Shotgun] {inc.service}: preview deployed",
            header
            + f'<p>🚀 Preview deploy of the fix is live.</p>'
            + f'<p><a href="{url}">{url}</a></p>'
            + footer,
        )
    if kind == "escalated":
        return (
            f"[Shotgun] {inc.service}: needs you",
            header
            + '<p>⚠️ <strong>Shotgun could not converge.</strong></p>'
            + f'<p style="color:#dc2626">Reason: {ctx.get("reason", "unknown")}</p>'
            + f'<p>Attempts: {ctx.get("attempts", 0)} of '
              f'{settings.RETRY_BUDGET}. The full timeline is recorded — open '
              'the live monitor to inspect.</p>'
            + footer,
        )

    # Fallback for unknown kinds
    return (
        f"[Shotgun] {inc.service}: {kind}",
        header + f'<p>Event: {kind}</p>' + footer,
    )


# ── AgentPhone (voice) ───────────────────────────────


async def _place_call(run: RunState, kind: str, ctx: dict) -> None:
    """Place an outbound voice call summarizing the event.

    Most events use a one-way "notification" call (fire-and-forget).
    The only two-way call is HUMAN_GATE via voice (kane_green), where
    the engineer can say "open the PR" or "stand down" — that lands
    in /webhooks/agentphone/decision and unblocks the orchestrator.
    """
    from app.clients import agentphone

    inc = run.incident
    expect = "ack"

    if kind == "incident_created":
        say = (
            f"Shotgun on the line. A new incident just fired for "
            f"{inc.service}. Symptom: {inc.symptom[:160]}. "
            f"Kane is reproducing the failure now. "
            f"I will call back once we know whether it is real."
        )
    elif kind == "kane_red_confirmed":
        say = (
            f"Shotgun. Kane reproduced the {inc.service} bug. "
            f"Kiro is writing a fix. Verified summary: "
            f"{(ctx.get('summary') or '')[:200]}. "
            f"I will call back when the fix is verified."
        )
    elif kind == "kane_green":
        say = (
            f"Shotgun. The {inc.service} fix is verified — Kane went "
            f"green {ctx.get('confirmation_runs', 0)} times in a row. "
            f"Approve and open the pull request now?"
        )
        expect = "decision"
    elif kind == "pr_opened":
        say = (
            f"Shotgun. The pull request for {inc.service} is open and "
            f"includes Kane proof. Standing by."
        )
    elif kind == "escalated":
        say = (
            f"Shotgun. The {inc.service} loop could not converge after "
            f"{ctx.get('attempts', 0)} attempts. Reason: "
            f"{(ctx.get('reason') or 'unknown')[:120]}. Needs human review."
        )
    else:
        return

    if expect == "decision":
        await agentphone.place_decision_call(run.run_id, say)
    else:
        await agentphone.place_notification_call(run.run_id, say)


# ── Test helper ──────────────────────────────────────


def clear_sent() -> None:
    """Wipe the dedupe set — used by tests so per-test runs aren't blocked."""
    _sent.clear()
