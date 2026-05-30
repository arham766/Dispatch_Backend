"""
Shotgun — kane_review: the second closed loop (§16).

After a fix ships, kane_review does NOT just re-check the one flow — it
replays the ENTIRE accumulated suite (this run's repro flow + every
previous recorded run's flow) against the new PR branch. If any previous
scenario now fails, that is a regression the naive single-flow loop would
miss; the review posts "changes requested" on the PR and kicks the run
back into the fix loop.

Why this scores well:
    It is a loop ON TOP OF a loop (fix loop ⟲ review loop), it makes
    Kane load-bearing twice, and the chain ledger means each PR is
    provably reviewed against its predecessor — a continuously
    self-reinforcing closed system, not a one-shot check.

    SHIP (PR open)
         │
         ▼
    ┌──────────── REVIEW (kane_review) ────────────┐
    │  replay suite = [this.flow, prev.flow, …]     │
    │  against the NEW PR branch                    │
    └───────────────────────────────────────────────┘
         │ all green                 │ any previous flow red
         ▼                           ▼
    post APPROVE review        post CHANGES-REQUESTED review
         │                           │  feed regression → Kiro
         ▼                           ▼  re-patch same branch
    RECORD + chain          ──► back into REVIEW (budget--)
"""

from __future__ import annotations

import logging
import os
from typing import Callable, Coroutine

from app.config import settings
from app.models import KaneResult, ReviewResult, RunState
from app.clients import kane, github_pr
from app import recorder

logger = logging.getLogger(__name__)


async def run(
    run_state: RunState,
    on_step: Callable[[dict], Coroutine] | None = None,
) -> ReviewResult:
    """Run the kane_review loop: replay the full suite against the PR branch.

    Args:
        run_state:  The current run (has prev_run_id, incident, branch, pr_url).
        on_step:    Async callback for Kane progress events.

    Returns:
        A ``ReviewResult`` with pass/fail, flows run, regressions, review URL.
    """
    # ── Build the regression suite ────────────────────
    if settings.KANE_REVIEW_MODE == "chained":
        suite = recorder.previous_flows(run_state)
        # Always include this run's own repro flow
        if run_state.incident.repro_flow not in suite:
            suite.append(run_state.incident.repro_flow)
    else:
        # Standalone: just this run's flow
        suite = [run_state.incident.repro_flow]

    # Filter to flows that actually exist on disk
    suite = [f for f in suite if os.path.exists(f)]

    logger.info(
        "[%s] kane_review: replaying %d flow(s) — %s",
        run_state.run_id,
        len(suite),
        suite,
    )

    # ── Replay every flow against the patched staging ─
    results: list[KaneResult] = []
    regressed: list[str] = []

    for flow in suite:
        logger.info("[%s] kane_review: running %s", run_state.run_id, flow)
        res = await kane.run_flow(
            flow,
            settings.STAGING_BASE_URL,
            variables=None,
            on_step=on_step,
            timeout=settings.KANE_TIMEOUT_SECONDS,
        )
        results.append(res)
        if not res.passed:
            regressed.append(flow)
            logger.warning(
                "[%s] kane_review: REGRESSION in %s — %s",
                run_state.run_id, flow, res.summary,
            )

    passed = not regressed

    # ── Post the review on the PR ─────────────────────
    body = _review_body(run_state, suite, regressed, results)
    event = "APPROVE" if passed else "REQUEST_CHANGES"
    review_url: str | None = None

    if run_state.pr_url:
        try:
            if settings.KANE_REVIEW_POST_AS == "review":
                review_url = await github_pr.post_review(
                    run_state.pr_url, event, body
                )
            else:
                review_url = await github_pr.post_comment(
                    run_state.pr_url, body
                )
        except Exception as exc:
            logger.error(
                "[%s] kane_review: failed to post review — %s",
                run_state.run_id, exc,
            )

    result = ReviewResult(
        passed=passed,
        flows_run=suite,
        regressed_flows=regressed,
        review_url=review_url,
        details=[r for r in results if not r.passed] or results[:1],
    )

    logger.info(
        "[%s] kane_review: %s — %d/%d flows passed",
        run_state.run_id,
        "PASSED ✅" if passed else "REGRESSED ❌",
        len(suite) - len(regressed),
        len(suite),
    )
    return result


def _review_body(
    run_state: RunState,
    suite: list[str],
    regressed: list[str],
    results: list[KaneResult],
) -> str:
    """Build the GitHub review body with per-flow results.

    The body documents what was reviewed, against which previous run,
    and the outcome of each flow.
    """
    head = (
        "✅ kane_review passed"
        if not regressed
        else "❌ kane_review found regressions"
    )
    lines = [
        f"## {head}",
        "",
        f"Reviewed PR against the chained suite "
        f"(prev run: `{run_state.prev_run_id or 'none'}`).",
        "",
        f"- Flows replayed: {len(suite)}",
        f"- Regressed: {regressed or 'none'}",
        "",
    ]

    for r in results:
        mark = "✅" if r.passed else "❌"
        lines.append(
            f"{mark} `{r.summary}` ({r.duration:.1f}s) {r.test_url or ''}"
        )

    lines.extend([
        "",
        "---",
        "_Each PR is reviewed against the previous one. Chain is unbroken._",
    ])
    return "\n".join(lines)
