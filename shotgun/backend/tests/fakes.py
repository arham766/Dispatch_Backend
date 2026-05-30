"""
Shotgun backend — test doubles & loop driver (NEW test-only module).

Nothing here imports at app start; tests opt in. The fakes model the
*real* contracts the orchestrator depends on so the genuine state machine,
recorder, normalizer and event bus all execute — only the three external
engines (Kane subprocess, Kiro agent, GitHub API) are replaced.

Key pieces:
  * kane_result(...)      — build a KaneResult quickly.
  * FakeLoop              — coordinated fake Kane + Kiro. Kiro "fixing" the
                            app flips Kane from red to green, exactly like
                            the production loop (REPRODUCE red → PATCH →
                            VERIFY green → CONFIRM green).
  * FakeGitHub            — records open_pr / post_review / post_comment calls.
  * install_loop(...)     — monkeypatch the orchestrator's three seams.
  * drive_incident(...)   — run the orchestrator end-to-end, capture every
                            SSE event, and satisfy the human gate.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.models import Incident, KaneResult, PatchResult, RunState, State


# ── Builders ──────────────────────────────────────────────────────────

def make_incident(service: str = "checkout", **kw: Any) -> Incident:
    return Incident(
        service=service,
        symptom=kw.get("symptom", "Checkout returns 500 on pay-submit"),
        suspect_url=kw.get("suspect_url", "https://staging.example.com/checkout"),
        repro_flow=kw.get("repro_flow", "flows/checkout_test.md"),
        recent_diff_hint=kw.get("recent_diff_hint", "payment.js"),
        source=kw.get("source", "manual"),
    )


def make_run(service: str = "checkout", **kw: Any) -> RunState:
    return RunState(incident=make_incident(service, **kw))


def kane_result(passed: bool = True, exit_code: int | None = None, **kw: Any) -> KaneResult:
    if exit_code is None:
        exit_code = 0 if passed else 1
    return KaneResult(
        passed=passed,
        exit_code=exit_code,
        summary=kw.get("summary", "order confirmation #1234" if passed else "pay button dead"),
        one_liner=kw.get("one_liner", ""),
        reason=kw.get("reason", "" if passed else "HTTP 500 on /pay"),
        duration=kw.get("duration", 1.0),
        credits=kw.get("credits"),
        final_state=kw.get("final_state", {"order": "1234"} if passed else {"error": "500"}),
        screenshot_path=kw.get("screenshot_path"),
        run_dir=kw.get("run_dir"),
        test_url=kw.get("test_url", "https://kaneai.example/run/abc123"),
    )


# ── Coordinated fake Kane + Kiro ──────────────────────────────────────

class FakeLoop:
    """A shared world: Kiro patching the code flips Kane red→green.

    Args:
        fixed_after_patches: number of Kiro patches required before Kane
            reports green. ``0`` ⇒ green from the very first run (models a
            bug that cannot be reproduced).
        emit_steps: how many ``kane_step`` progress events to stream per run.
        flake_calls: a set of 1-based Kane call indices that are forced red
            regardless of patch state (models flaky confirmation runs).
        reproduce_override: a KaneResult returned on the *first* Kane call
            only (models an infra error / exit code 2 at REPRODUCE).
    """

    def __init__(
        self,
        fixed_after_patches: int = 1,
        emit_steps: int = 2,
        flake_calls: set[int] | None = None,
        reproduce_override: KaneResult | None = None,
    ) -> None:
        self.fixed_after = fixed_after_patches
        self.emit_steps = emit_steps
        self.flake_calls = flake_calls or set()
        self.reproduce_override = reproduce_override
        self.patches = 0
        self.kane_calls = 0
        self.kiro_calls = 0
        self.flows_run: list[str] = []

    async def run_flow(
        self,
        flow_file: str,
        base_url: str,
        variables: dict | None = None,
        on_step=None,
        timeout: int = 120,
    ) -> KaneResult:
        self.kane_calls += 1
        n = self.kane_calls
        self.flows_run.append(flow_file)

        if on_step is not None:
            for i in range(self.emit_steps):
                await on_step({"step": f"step-{i}", "status": "running", "remark": flow_file})

        if n == 1 and self.reproduce_override is not None:
            return self.reproduce_override
        if n in self.flake_calls:
            return kane_result(passed=False)

        passed = self.patches >= self.fixed_after
        return kane_result(passed=passed)

    def agent(self):
        loop = self

        class _Kiro:
            async def patch(self, incident: Incident, last_failure, attempt: int) -> PatchResult:
                loop.kiro_calls += 1
                loop.patches += 1
                return PatchResult(
                    branch=f"shotgun/fix-{incident.service}-{attempt}",
                    diff_summary="1 file changed, 3 insertions(+), 1 deletion(-)",
                    changed_files=["payment.js"],
                )

        return _Kiro()


# ── Fake GitHub ───────────────────────────────────────────────────────

class FakeGitHub:
    """Captures PR/review/comment calls instead of hitting the API."""

    def __init__(self, base: str = "https://github.com/org/app") -> None:
        self.base = base
        self.prs: list[dict] = []
        self.reviews: list[dict] = []
        self.comments: list[dict] = []

    async def open_pr(self, branch: str, inc: Incident, kane: KaneResult | None):
        from app.clients.github_pr import PR

        num = len(self.prs) + 1
        url = f"{self.base}/pull/{num}"
        self.prs.append({"branch": branch, "url": url, "symptom": inc.symptom})
        return PR(url=url)

    async def post_review(self, pr_url: str, event: str, body: str) -> str:
        url = f"{pr_url}#review-{len(self.reviews) + 1}"
        self.reviews.append({"pr_url": pr_url, "event": event, "body": body, "url": url})
        return url

    async def post_comment(self, pr_url: str, body: str) -> str:
        url = f"{pr_url}#comment-{len(self.comments) + 1}"
        self.comments.append({"pr_url": pr_url, "body": body, "url": url})
        return url


# ── Wiring ────────────────────────────────────────────────────────────

def install_loop(
    monkeypatch,
    loop: FakeLoop,
    github: FakeGitHub | None = None,
) -> FakeGitHub:
    """Patch the orchestrator's three external seams to use the fakes."""
    import app.clients.kane as kane_mod
    import app.clients.github_pr as gh_mod
    import app.orchestrator as orch_mod

    github = github or FakeGitHub()

    monkeypatch.setattr(kane_mod, "run_flow", loop.run_flow)
    monkeypatch.setattr(orch_mod, "make_kiro_agent", lambda: loop.agent())
    monkeypatch.setattr(gh_mod, "open_pr", github.open_pr)
    monkeypatch.setattr(gh_mod, "post_review", github.post_review)
    monkeypatch.setattr(gh_mod, "post_comment", github.post_comment)
    return github


# ── Driver ────────────────────────────────────────────────────────────

async def drive_incident(
    run: RunState,
    *,
    approve: bool = True,
    reject: bool = False,
    timeout: float = 10.0,
) -> list[dict]:
    """Run the orchestrator to completion, capturing every SSE event.

    Subscribes before the orchestrator starts, satisfies the HUMAN_GATE
    (approve or reject), and returns the ordered list of published events.
    """
    from app.store import store
    from app import orchestrator

    if run.run_id not in store._runs:
        store.create(run)
    q = store.subscribe(run.run_id)
    events: list[dict] = []

    task = asyncio.create_task(orchestrator.run_incident(run))

    async def pump() -> None:
        while True:
            ev = await q.get()
            events.append(ev)
            if ev.get("event") == "awaiting_approval":
                if reject:
                    run.state = State.STANDBY
                    run.awaiting_approval = False
                    store.approve(run.run_id)
                elif approve:
                    store.approve(run.run_id)
            if ev.get("event") == "done":
                return

    try:
        await asyncio.wait_for(pump(), timeout=timeout)
    finally:
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except (asyncio.TimeoutError, Exception):
            if not task.done():
                task.cancel()
        store.unsubscribe(run.run_id, q)

    return events


# ── Event helpers ─────────────────────────────────────────────────────

def types_of(events: list[dict]) -> list[str]:
    return [e.get("event") for e in events]


def first(events: list[dict], event_type: str) -> dict | None:
    return next((e for e in events if e.get("event") == event_type), None)


def states_seen(events: list[dict]) -> list[str]:
    return [e.get("state") for e in events if e.get("event") == "state_change"]
