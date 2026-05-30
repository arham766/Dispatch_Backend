"""
Shotgun — The Orchestrator (core IP).

A bounded, deterministic state machine. Every failure path leads
somewhere safe — a human, never silence. ~200 lines of real control flow.

State machine:
    INTAKE → REPRODUCE → PATCH → VERIFY → CONFIRM → HUMAN_GATE → SHIP
                                    ↑        ↓
                                  DECIDE ← (red)
                                    ↓
                              (budget=0) → ESCALATE

    SHIP → REVIEW → RECORD → RESOLVED
              ↓
        REVIEW_DECIDE → (budget>0) → PATCH (re-enter)
              ↓
        (budget=0) → ESCALATE

Hard rule: the demo and the real tool are the same codebase fed a known
input. No ``if service == "checkout": return canned_fix``. The orchestrator
really calls Kiro and really parses Kane's real output; only the inputs
(staging app, seeded bug, repo state) are rehearsed.
"""

from __future__ import annotations

import logging
import os

from app.config import settings
from app.models import Incident, KaneResult, RunState, State
from app.store import store
from app.clients import kane, kane_smoke
from app.clients.kiro import make_kiro_agent
from app import recorder, notifications

logger = logging.getLogger(__name__)


async def run_incident(run: RunState) -> None:
    """Drive one incident through the full closed-loop state machine.

    This is the single entry point. It is spawned as a background task
    from the ``POST /incidents`` handler.
    """
    kiro = make_kiro_agent()
    inc = run.incident
    run.retry_budget = settings.RETRY_BUDGET

    # Set up recording directory for event mirroring
    if settings.RECORD_LOOPS:
        import os
        rec_dir = os.path.join(settings.RECORDINGS_DIR, run.run_id)
        os.makedirs(rec_dir, exist_ok=True)
        store.set_recording_dir(run.run_id, rec_dir)

    # ── Helpers ───────────────────────────────────────

    async def emit(event: str, **data) -> None:
        """Publish an event to all SSE subscribers + recording mirror."""
        await store.publish(run.run_id, {
            "event": event,
            "state": run.state.value,
            **data,
        })

    async def on_step(step: dict) -> None:
        """Stream Kane progress lines to the UI."""
        await emit(
            "kane_step",
            step=step.get("step", ""),
            status=step.get("status", ""),
            remark=step.get("remark", ""),
        )

    async def kane_run(attempt: int = 0, *, force_real: bool = False) -> KaneResult:
        """Run a verification pass and emit the result.

        Two backends, picked by KANE_FAST_MODE + the ``force_real`` flag:

        * Fast smoke (default for REPRODUCE/VERIFY/CONFIRM):
          2-sec curl + DOM-text + Node-sandbox check against the URL.
          Catches the seeded ReferenceError / 500-ish bugs instantly.
          Used for in-loop iterations so the demo finishes in <2 minutes
          instead of 30.

        * Real Kane CLI (used when KANE_FAST_MODE=false OR force_real=True):
          Full testmd run with the agent. Slow (3-6min per pass) but
          produces the LTM dashboard link we embed as audit proof in
          the PR body. We do exactly ONE real run before SHIP so the
          PR carries the canonical artifact.
        """
        # URL selection for this run:
        #   attempt 0 (REPRODUCE)   → STAGING_BASE_URL (the broken prod page)
        #   attempt > 0 (VERIFY)    → in this order:
        #     1) explicit PREVIEW_BASE_URL env (set by composite Action)
        #     2) raw.githubusercontent.com/<repo>/<branch>/<file>
        #        — instant access to the patched file content, no GH Pages
        #        refresh delay, works for any tenant repo
        #     3) LOCAL_PREVIEW_URL (dev only)
        #     4) fall back to STAGING_BASE_URL
        test_url = settings.STAGING_BASE_URL
        if attempt > 0:
            preview = os.getenv("PREVIEW_BASE_URL")
            if not preview and run.branch and settings.GITHUB_REPO:
                # Use raw.githubusercontent so the smoke fetch sees the
                # branch's freshly-patched content immediately.
                hint = inc.recent_diff_hint or ""
                if hint and ("/" in hint or "." in hint.rsplit("/", 1)[-1]):
                    preview = (
                        f"https://raw.githubusercontent.com/"
                        f"{settings.GITHUB_REPO}/{run.branch}/{hint}"
                    )
            if not preview:
                preview = os.getenv("LOCAL_PREVIEW_URL")
            if preview:
                test_url = preview

        use_smoke = settings.KANE_FAST_MODE and not force_real
        if use_smoke:
            logger.info(
                "[%s] kane_run: smoke mode (target=%s, attempt=%d)",
                run.run_id, test_url, attempt,
            )
            res = await kane_smoke.run_smoke(test_url, on_step=on_step)
        else:
            logger.info(
                "[%s] kane_run: REAL Kane CLI (target=%s, attempt=%d)",
                run.run_id, test_url, attempt,
            )
            res = await kane.run_flow(
                inc.repro_flow,
                test_url,
                variables={"STAGING_BASE_URL": test_url},
                on_step=on_step,
                timeout=settings.KANE_TIMEOUT_SECONDS,
            )

        await emit(
            "kane_result",
            passed=res.passed,
            summary=res.summary,
            duration=res.duration,
            test_url=res.test_url,
            screenshot_url=_public(res.screenshot_path),
            mode="smoke" if use_smoke else "real",
        )
        run.last_kane = res
        return res

    # ── INTAKE ────────────────────────────────────────

    run.state = State.INTAKE
    await emit("state_change", message="Incident received, normalizing...")
    await notifications.publish(run, "incident_created")
    logger.info("========================================================")
    logger.info("[%s] INTAKE", run.run_id)
    logger.info("  service  : %s", inc.service)
    logger.info("  symptom  : %s", inc.symptom)
    logger.info("  url      : %s", inc.suspect_url)
    logger.info("  flow     : %s", inc.repro_flow)
    logger.info("  hint     : %s", inc.recent_diff_hint or "-")
    logger.info("  source   : %s", inc.source)
    logger.info("  budget   : %d attempts", run.retry_budget)
    logger.info("========================================================")

    # Chain to the previous recorded run (for kane_review)
    if settings.RECORD_LOOPS:
        recorder.link_previous(run)

    # ── REPRODUCE ── confirm the bug is real ───────────

    run.state = State.REPRODUCE
    await emit("state_change", message="Reproducing the failure with Kane...")
    logger.info("[%s] >> REPRODUCE: running %s against %s", run.run_id, inc.repro_flow, settings.STAGING_BASE_URL)

    repro = await kane_run()
    logger.info("[%s] REPRODUCE result: passed=%s exit=%d summary=%s",
                run.run_id, repro.passed, repro.exit_code, repro.summary[:100])
    if repro.passed or repro.exit_code == 2:
        # Can't reproduce -- the bug isn't there or infra error
        logger.info("[%s] REPRODUCE: cannot reproduce (passed=%s exit=%d) -> ESCALATE",
                    run.run_id, repro.passed, repro.exit_code)
        return await _escalate(run, emit, "Could not reproduce a red failure.")

    # Confirmed red — notify user "we're on it"
    await notifications.publish(
        run, "kane_red_confirmed", summary=repro.summary
    )

    # ── PATCH → VERIFY → DECIDE loop ─────────────────

    while True:
        run.attempt += 1

        # PATCH -- Kiro writes a fix
        run.state = State.PATCH
        await emit(
            "state_change",
            attempt=run.attempt,
            message=f"Kiro is writing a fix (attempt {run.attempt})...",
        )
        logger.info("[%s] >> PATCH: attempt %d (budget left: %d)",
                    run.run_id, run.attempt, run.retry_budget)

        patch = await kiro.patch(inc, run.last_kane, run.attempt)
        run.branch = patch.branch
        await emit(
            "patch",
            branch=patch.branch,
            diff_summary=patch.diff_summary,
            changed_files=patch.changed_files,
        )

        # VERIFY -- Kane re-verifies the patched app
        run.state = State.VERIFY
        await emit("state_change", message="Kane re-verifying the patched app...")
        logger.info("[%s] >> VERIFY: running Kane on branch %s", run.run_id, patch.branch)

        verify = await kane_run(run.attempt)
        logger.info("[%s] VERIFY result: passed=%s exit=%d summary=%s",
                    run.run_id, verify.passed, verify.exit_code, verify.summary[:100])

        if verify.passed:
            break  # Fix works!

        # DECIDE — still red, feed failure back
        run.state = State.DECIDE
        run.retry_budget -= 1
        if run.retry_budget <= 0:
            return await _escalate(run, emit, "Retry budget exhausted.")

        await emit(
            "state_change",
            message=(
                f"Still red — re-prompting Kiro "
                f"({run.retry_budget} attempt(s) left)."
            ),
        )
        logger.info(
            "[%s] DECIDE: still red, %d attempts left",
            run.run_id, run.retry_budget,
        )

    # ── CONFIRM — N deterministic replays (free) ─────

    run.state = State.CONFIRM
    await emit(
        "state_change",
        message=f"Confirming: {settings.CONFIRMATION_RUNS}× deterministic replay…",
    )
    logger.info("[%s] CONFIRM: %d replays", run.run_id, settings.CONFIRMATION_RUNS)

    for i in range(settings.CONFIRMATION_RUNS):
        c = await kane_run(run.attempt)
        if not c.passed:
            run.retry_budget -= 1
            if run.retry_budget <= 0:
                return await _escalate(run, emit, "Confirmation runs flaked.")
            run.state = State.DECIDE
            await emit(
                "state_change",
                message=f"Confirmation {i + 1} flaked — re-entering fix loop.",
            )
            # Re-enter the fix loop (recursive, bounded by budget)
            return await run_incident(run)

    # ── HUMAN_GATE — never merge autonomously ─────────

    run.state = State.HUMAN_GATE
    run.awaiting_approval = True
    await emit(
        "awaiting_approval",
        summary=run.last_kane.summary if run.last_kane else "",
        confirmation_runs=settings.CONFIRMATION_RUNS,
        auto_approving=settings.AUTO_APPROVE_AT_HUMAN_GATE,
    )
    # The "✅ approve" call + email fires here regardless of mode — it's
    # the on-call's notification that the fix is ready. The difference
    # is whether SHIP blocks waiting for an explicit /approve.
    await notifications.publish(
        run, "kane_green",
        confirmation_runs=settings.CONFIRMATION_RUNS,
    )

    if settings.AUTO_APPROVE_AT_HUMAN_GATE:
        # Race the explicit /approve against a short auto-approve timer.
        # If the user clicks the green button or the agent posts a "yes"
        # decision in that window, that wins. Otherwise we proceed to
        # SHIP automatically — the call/email already told them what's
        # happening. A "stand down" click would set state to STANDBY
        # before this window closes; we honour it.
        logger.info(
            "[%s] HUMAN_GATE: auto-approving in %ds (call out for awareness)",
            run.run_id, settings.AUTO_APPROVE_DELAY_SECONDS,
        )
        try:
            import asyncio as _asyncio
            await _asyncio.wait_for(
                store.wait_for_approval(run.run_id),
                timeout=settings.AUTO_APPROVE_DELAY_SECONDS,
            )
            logger.info("[%s] HUMAN_GATE: approved by human", run.run_id)
        except _asyncio.TimeoutError:
            logger.info("[%s] HUMAN_GATE: auto-approving (no manual response)", run.run_id)
        # If the user clicked "Stand down" the route flips state to
        # STANDBY; respect that and exit.
        if run.state == State.STANDBY:
            logger.info("[%s] HUMAN_GATE: user stood down — aborting SHIP", run.run_id)
            return
    else:
        logger.info("[%s] HUMAN_GATE: waiting for explicit approval…", run.run_id)
        await store.wait_for_approval(run.run_id)
        if run.state == State.STANDBY:
            logger.info("[%s] HUMAN_GATE: user stood down — aborting SHIP", run.run_id)
            return
        logger.info("[%s] HUMAN_GATE: approved!", run.run_id)

    run.awaiting_approval = False

    # ── PROOF — one real Kane run before SHIP (audit artifact) ───

    if settings.KANE_FAST_MODE and settings.KANE_REAL_PROOF:
        await emit(
            "state_change",
            message="Running real Kane CLI once for the audit trail proof…",
        )
        logger.info("[%s] PROOF: real Kane run before SHIP", run.run_id)
        try:
            proof = await kane_run(run.attempt, force_real=True)
            # If real Kane disagrees with the smoke check (rare but
            # possible — smoke is intentionally narrow), bail to DECIDE.
            if not proof.passed:
                run.retry_budget -= 1
                if run.retry_budget <= 0:
                    return await _escalate(
                        run, emit,
                        "Real Kane disagreed with smoke verdict.",
                    )
                run.state = State.DECIDE
                await emit(
                    "state_change",
                    message="Real Kane disagreed — re-entering fix loop.",
                )
                return await run_incident(run)
        except Exception as exc:
            # Don't block ship if real Kane has infra trouble. We have
            # the smoke verdict + Kiro's diff as evidence already.
            logger.warning("[%s] PROOF: real Kane errored: %s", run.run_id, exc)
            await emit(
                "state_change",
                message=f"Real Kane errored ({type(exc).__name__}); shipping on smoke verdict.",
            )

    # ── SHIP — open GitHub PR ─────────────────────────

    run.state = State.SHIP
    await emit("state_change", message="Opening the pull request…")
    logger.info("[%s] SHIP: opening PR on %s", run.run_id, run.branch)

    try:
        from app.clients import github_pr
        from app.clients.kiro import _is_cloud_environment
        # If we're effectively in cloud mode (cloud configured OR no
        # local git workdir / Kiro binary) the branch is already on
        # origin via the Contents API push — skip `git push` entirely.
        # In a real local-dev setup we still need to push.
        skip_push = settings.KIRO_MODE == "cloud" or _is_cloud_environment()
        if not skip_push:
            push_ok = await _push_branch(run.branch)
            if not push_ok:
                logger.warning(
                    "[%s] SHIP: git push failed, attempting PR open anyway "
                    "(branch may already be on origin via API)",
                    run.run_id,
                )
        pr = await github_pr.open_pr(run.branch, run.incident, run.last_kane)
        run.pr_url = pr.url
        await emit("pr_opened", pr_url=pr.url, proof_url=run.last_kane.test_url)
        await notifications.publish(run, "pr_opened", pr_url=pr.url)
    except Exception as exc:
        logger.error("[%s] SHIP: PR failed — %s", run.run_id, exc)
        await emit(
            "state_change",
            message=f"PR creation failed: {exc}. Continuing to RECORD.",
        )

    # ── REVIEW — the SECOND closed loop (§16) ────────

    if settings.KANE_REVIEW_ENABLED:
        run.review_budget = settings.KANE_REVIEW_BUDGET

        while True:
            run.state = State.REVIEW
            await emit(
                "state_change",
                message="kane_review: replaying the regression suite vs. previous…",
            )
            logger.info("[%s] REVIEW: running kane_review", run.run_id)

            from app.clients import kane_review
            review = await kane_review.run(run, on_step=on_step)
            run.review = review
            await emit(
                "review_result",
                passed=review.passed,
                flows_run=review.flows_run,
                regressed=review.regressed_flows,
                review_url=review.review_url,
            )

            if review.passed:
                break

            # Regression found → re-enter the fix loop
            run.state = State.REVIEW_DECIDE
            run.review_budget -= 1

            if run.review_budget <= 0 or not settings.KANE_REVIEW_BLOCK_ON_REGRESSION:
                return await _escalate(
                    run,
                    emit,
                    f"kane_review found regressions: {review.regressed_flows}",
                )

            # Feed the regression back to Kiro
            run.last_kane = (
                review.details[0] if review.details else run.last_kane
            )
            await emit(
                "state_change",
                message=(
                    f"Regression caught — re-prompting Kiro "
                    f"({run.review_budget} review attempt(s) left)."
                ),
            )

            patch = await kiro.patch(inc, run.last_kane, run.attempt + 1)
            run.attempt += 1
            run.branch = patch.branch
            await emit(
                "patch",
                branch=patch.branch,
                diff_summary=patch.diff_summary,
                changed_files=patch.changed_files,
            )

            # Re-verify and re-review
            await kane_run()

    # ── RECORD — persist everything + chain ───────────

    run.state = State.RECORD
    await emit("state_change", message="Recording the loop and chaining it…")
    logger.info("[%s] RECORD: persisting run", run.run_id)

    rec = await recorder.finalize(run)
    run.recording_dir = rec.dir

    # ── RESOLVED ──────────────────────────────────────

    run.state = State.RESOLVED
    await emit(
        "recorded",
        recording_dir=rec.dir,
        prev_run_id=run.prev_run_id,
        chain_length=rec.chain_length,
    )
    await emit("done", final_state="RESOLVED")
    logger.info("[%s] RESOLVED ✅", run.run_id)


async def _escalate(run: RunState, emit, reason: str) -> None:
    """Handle all failure paths — escalate to human with everything gathered."""
    run.state = State.ESCALATE
    logger.warning("[%s] ESCALATE: %s (after %d attempts)", run.run_id, reason, run.attempt)

    await emit("escalated", reason=reason, attempts=run.attempt)
    await notifications.publish(run, "escalated", reason=reason, attempts=run.attempt)

    # Escalated runs are recorded too
    try:
        rec = await recorder.finalize(run)
        run.recording_dir = rec.dir
    except Exception as exc:
        logger.error("[%s] ESCALATE: recording failed — %s", run.run_id, exc)

    await emit("done", final_state="ESCALATE")


async def _push_branch(branch: str) -> bool:
    """Push the Kiro-built branch to origin so the PR can reference it.

    Uses the existing ``origin`` remote (which carries the embedded PAT
    in dev / admin mode; in multi-tenant cloud we use the GitHub App's
    installation token instead). Returns True on success.
    """
    import asyncio
    import logging as _logging
    _log = _logging.getLogger(__name__)
    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "push", "--set-upstream", "origin", branch, "--force",
            cwd=settings.KIRO_WORKDIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            _log.info("push: %s → origin OK", branch)
            return True
        _log.error(
            "push: %s failed (rc=%d) — %s",
            branch, proc.returncode,
            (stderr or stdout).decode(errors="ignore")[:300],
        )
        return False
    except Exception as exc:
        _log.error("push: exception pushing %s — %s", branch, exc)
        return False


def _public(screenshot_path: str | None) -> str | None:
    """Convert a local screenshot path to a URL the frontend can fetch."""
    if not screenshot_path:
        return None
    # The main app mounts recordings under /screenshots
    # Convert: ./recordings/<run_id>/screenshot.png → /screenshots/<run_id>/screenshot.png
    if "recordings" in screenshot_path:
        parts = screenshot_path.split("recordings")
        return f"/screenshots{parts[-1]}"
    return screenshot_path
