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
    """Pick subject + HTML body per event kind.

    Each email leads with a distinct colored hero banner so the user can
    tell incident_created vs kane_red vs pr_opened apart at a glance —
    not buried under an identical "Shotgun · checkout" header on every
    one. The PR email leads with the GitHub button as the primary CTA.
    """
    inc = run.incident
    page_style = (
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
        "max-width:560px;margin:0 auto;padding:0;color:#1d1d1f;"
        "background:#ffffff"
    )
    footer = (
        f'<div style="padding:20px 24px;border-top:1px solid #d2d2d7">'
        f'<p style="color:#86868b;font-size:12px;margin:0">'
        f'Run <code>{run.run_id}</code> · '
        f'<a href="{settings.PUBLIC_APP_URL}?run={run.run_id}" '
        f'style="color:#0071e3">Live monitor</a> · '
        f'<span style="font-family:monospace">{inc.service}</span>'
        f'</p></div></div>'
    )

    def hero(emoji: str, color: str, title: str, sub: str) -> str:
        return (
            f'<div style="{page_style}">'
            f'<div style="padding:32px 24px 20px 24px;background:{color};'
            f'color:white">'
            f'<div style="font-size:28px;line-height:1;margin:0 0 12px 0">{emoji}</div>'
            f'<h1 style="margin:0 0 6px 0;font-size:22px;font-weight:600">'
            f'{title}</h1>'
            f'<p style="margin:0;opacity:0.85;font-size:14px">{sub}</p>'
            f'</div>'
            f'<div style="padding:24px">'
        )

    def button(url: str, label: str, color: str = "#0071e3") -> str:
        return (
            f'<a href="{url}" '
            f'style="display:inline-block;padding:12px 22px;background:{color};'
            f'color:white;text-decoration:none;border-radius:8px;'
            f'font-weight:600;font-size:14px">{label}</a>'
        )

    if kind == "incident_created":
        return (
            f"🔔 Incident received · {inc.service}",
            hero(
                "🔔",
                "#1d1d1f",
                "We're on it.",
                f"Just received an incident for {inc.service}.",
            )
            + f'<p style="margin:0 0 12px 0;color:#1d1d1f;font-size:15px">'
              f'<strong>Symptom:</strong> {inc.symptom}</p>'
            + '<p style="margin:0 0 20px 0;color:#6e6e73;font-size:13px;line-height:1.5">'
              'Kane is reproducing the failure against your live deploy now. '
              'You will get the next email once we have a verdict — usually '
              'within ~60 seconds.</p>'
            + button(
                f"{settings.PUBLIC_APP_URL}?run={run.run_id}",
                "Open live monitor →",
            )
            + footer,
        )
    if kind == "kane_red_confirmed":
        return (
            f"🔴 Bug reproduced — Kiro is fixing · {inc.service}",
            hero(
                "🔴",
                "#dc2626",
                "Kane reproduced the bug.",
                "Kiro is writing a fix right now.",
            )
            + '<p style="margin:0 0 12px 0;color:#1d1d1f;font-size:14px">'
              '<strong>Kane verdict:</strong></p>'
            + f'<blockquote style="border-left:3px solid #dc2626;padding:8px 14px;'
              f'margin:0 0 20px 0;color:#1d1d1f;font-size:13px;background:#fef2f2">'
              f'{ctx.get("summary", "")[:600]}</blockquote>'
            + '<p style="margin:0 0 20px 0;color:#6e6e73;font-size:13px;line-height:1.5">'
              'Kiro is committing a candidate fix to a new branch. You will '
              'get another email when verification passes.</p>'
            + button(
                f"{settings.PUBLIC_APP_URL}?run={run.run_id}",
                "Watch the fix happen →",
            )
            + footer,
        )
    if kind == "kane_green":
        return (
            f"🟢 Fix verified — approve the PR · {inc.service}",
            hero(
                "🟢",
                "#16a34a",
                "Fix verified.",
                f"Confirmed {ctx.get('confirmation_runs', 0)}× green in a row. "
                "Tap to open the PR.",
            )
            + '<p style="margin:0 0 20px 0;color:#1d1d1f;font-size:14px;line-height:1.5">'
              'Kiro\'s patch passed Kane\'s regression flow. One tap from you '
              'opens the pull request on GitHub with the Kane proof embedded.'
              '</p>'
            + button(
                f"{settings.PUBLIC_APP_URL}?run={run.run_id}",
                "✅ Approve & open PR",
                color="#16a34a",
            )
            + footer,
        )
    if kind == "pr_opened":
        pr_url = ctx.get("pr_url") or "#"
        # Try to derive PR number from URL: github.com/<repo>/pull/<N>
        pr_label = "View PR on GitHub"
        try:
            num = pr_url.rstrip("/").split("/")[-1]
            if num.isdigit():
                pr_label = f"View PR #{num} on GitHub"
        except Exception:
            pass
        return (
            f"📝 PR opened on GitHub · {inc.service}",
            hero(
                "📝",
                "#0071e3",
                "Pull request is live.",
                "Click below to review on GitHub.",
            )
            + f'<p style="margin:0 0 20px 0;color:#1d1d1f;font-size:14px;line-height:1.5">'
              f'The PR includes the verified diff and a link to the Kane '
              f'replay trace. Approve and merge when ready — Shotgun will '
              f'continue watching the deploy.</p>'
            + button(pr_url, f"{pr_label} →")
            + f'<p style="margin:14px 0 0 0;color:#6e6e73;font-size:12px;'
              f'word-break:break-all">'
              f'<a href="{pr_url}" style="color:#0071e3">{pr_url}</a></p>'
            + footer,
        )
    if kind == "preview_ready":
        url = ctx.get("preview_url", "#")
        return (
            f"🚀 Preview deployed · {inc.service}",
            hero(
                "🚀",
                "#0071e3",
                "Preview is live.",
                "Try the fix in the staging environment.",
            )
            + button(url, "Open preview →")
            + footer,
        )
    if kind == "escalated":
        return (
            f"⚠️ Needs you — could not auto-fix · {inc.service}",
            hero(
                "⚠️",
                "#d97706",
                "Loop could not converge.",
                "We need a human to take a look.",
            )
            + f'<p style="margin:0 0 12px 0;color:#1d1d1f;font-size:14px">'
              f'<strong>Reason:</strong> {ctx.get("reason", "unknown")}</p>'
            + f'<p style="margin:0 0 20px 0;color:#6e6e73;font-size:13px">'
              f'Attempts: {ctx.get("attempts", 0)} of '
              f'{settings.RETRY_BUDGET}. The full timeline is recorded.</p>'
            + button(
                f"{settings.PUBLIC_APP_URL}?run={run.run_id}",
                "Inspect timeline →",
                color="#d97706",
            )
            + footer,
        )

    # Fallback for unknown kinds
    return (
        f"Shotgun · {kind} · {inc.service}",
        hero("•", "#1d1d1f", kind, inc.symptom) + footer,
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
