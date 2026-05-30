"""
Integration tests for the orchestrator state machine (app/orchestrator.py).

These exercise the REAL state machine, recorder, and event bus end-to-end;
only Kane / Kiro / GitHub are faked. Each test asserts on the observable
SSE event stream and the final RunState.

Where the current implementation diverges from the HLD's intended behaviour,
the test is marked xfail(strict=True) with the finding documented, so the
suite stays green AND the bug is recorded (an xpass will flag the fix).
"""

from __future__ import annotations

import pytest

from app.models import State
from tests import fakes


pytestmark = pytest.mark.integration


# ── Happy path ────────────────────────────────────────────────────────

async def test_single_patch_resolves(monkeypatch):
    """Red → one patch → green → confirm → gate → PR → review-off → RESOLVED."""
    loop = fakes.FakeLoop(fixed_after_patches=1)
    gh = fakes.install_loop(monkeypatch, loop)

    run = fakes.make_run()
    events = await fakes.drive_incident(run)

    assert run.state is State.RESOLVED
    assert loop.kiro_calls == 1
    assert len(gh.prs) == 1
    # REPRODUCE(1) + VERIFY(1) + CONFIRM(2) = 4 Kane calls
    assert loop.kane_calls == 2 + fakes_confirmation_runs()


async def test_event_sequence_is_well_formed(monkeypatch):
    loop = fakes.FakeLoop(fixed_after_patches=1)
    fakes.install_loop(monkeypatch, loop)

    events = await fakes.drive_incident(fakes.make_run())
    kinds = fakes.types_of(events)

    # Ordering guarantees the UI relies on.
    assert kinds[0] == "state_change"
    assert kinds[-1] == "done"
    assert kinds.index("patch") < kinds.index("pr_opened")
    assert kinds.index("awaiting_approval") < kinds.index("pr_opened")
    assert kinds.index("pr_opened") < kinds.index("recorded")
    # Every event carries the machine state for the dashboard.
    assert all("state" in e for e in events)


async def test_states_visited_in_order(monkeypatch):
    loop = fakes.FakeLoop(fixed_after_patches=1)
    fakes.install_loop(monkeypatch, loop)

    events = await fakes.drive_incident(fakes.make_run())
    seen = fakes.states_seen(events)

    for s in ("INTAKE", "REPRODUCE", "PATCH", "VERIFY", "CONFIRM", "SHIP", "RECORD"):
        assert s in seen, f"expected to pass through {s}; saw {seen}"
    assert seen.index("REPRODUCE") < seen.index("PATCH") < seen.index("VERIFY")


async def test_kane_steps_streamed(monkeypatch):
    loop = fakes.FakeLoop(fixed_after_patches=1, emit_steps=3)
    fakes.install_loop(monkeypatch, loop)

    events = await fakes.drive_incident(fakes.make_run())
    steps = [e for e in events if e["event"] == "kane_step"]
    assert len(steps) >= 3
    assert all("step" in s and "status" in s for s in steps)


# ── Retry / patch loop ────────────────────────────────────────────────

async def test_multiple_patches_before_green(monkeypatch):
    """Two failed verifies, third patch fixes it. Budget must absorb the misses."""
    loop = fakes.FakeLoop(fixed_after_patches=3)
    fakes.install_loop(monkeypatch, loop)

    run = fakes.make_run()
    events = await fakes.drive_incident(run)

    assert run.state is State.RESOLVED
    assert loop.kiro_calls == 3
    assert run.attempt == 3


async def test_retry_budget_exhausted_escalates(monkeypatch, iso_recordings):
    """Bug never gets fixed → budget hits zero → ESCALATE, never reaches a PR."""
    iso_recordings.RETRY_BUDGET = 2
    loop = fakes.FakeLoop(fixed_after_patches=99)  # never fixed
    gh = fakes.install_loop(monkeypatch, loop)

    run = fakes.make_run()
    events = await fakes.drive_incident(run)

    assert run.state is State.ESCALATE
    esc = fakes.first(events, "escalated")
    assert esc is not None
    assert "budget" in esc["reason"].lower()
    assert events[-1]["final_state"] == "ESCALATE"
    assert len(gh.prs) == 0


async def test_escalation_still_records(monkeypatch):
    """An escalated run is recorded too (audit trail / chain integrity)."""
    loop = fakes.FakeLoop(fixed_after_patches=99)
    fakes.install_loop(monkeypatch, loop)

    run = fakes.make_run()
    await fakes.drive_incident(run)

    assert run.recording_dir is not None


# ── REPRODUCE guard ───────────────────────────────────────────────────

async def test_cannot_reproduce_green_escalates(monkeypatch):
    """If the bug reproduces green, the loop must NOT fabricate a fix."""
    loop = fakes.FakeLoop(fixed_after_patches=0)  # green from the first call
    gh = fakes.install_loop(monkeypatch, loop)

    run = fakes.make_run()
    events = await fakes.drive_incident(run)

    assert run.state is State.ESCALATE
    assert loop.kiro_calls == 0
    assert len(gh.prs) == 0
    esc = fakes.first(events, "escalated")
    assert "reproduce" in esc["reason"].lower()


async def test_reproduce_infra_error_escalates(monkeypatch):
    """Exit code 2 (infra error) at REPRODUCE escalates rather than patching."""
    loop = fakes.FakeLoop(
        fixed_after_patches=1,
        reproduce_override=fakes.kane_result(passed=False, exit_code=2),
    )
    fakes.install_loop(monkeypatch, loop)

    run = fakes.make_run()
    await fakes.drive_incident(run)

    assert run.state is State.ESCALATE
    assert loop.kiro_calls == 0


# ── Human gate ────────────────────────────────────────────────────────

async def test_human_gate_blocks_until_approval(monkeypatch):
    """No PR is opened before the human approves."""
    loop = fakes.FakeLoop(fixed_after_patches=1)
    gh = fakes.install_loop(monkeypatch, loop)

    run = fakes.make_run()
    events = await fakes.drive_incident(run, approve=True)

    gate = fakes.first(events, "awaiting_approval")
    assert gate is not None
    assert gate["confirmation_runs"] == fakes_confirmation_runs()
    assert len(gh.prs) == 1


async def test_pr_carries_kane_proof(monkeypatch):
    loop = fakes.FakeLoop(fixed_after_patches=1)
    fakes.install_loop(monkeypatch, loop)

    run = fakes.make_run()
    events = await fakes.drive_incident(run)
    pr = fakes.first(events, "pr_opened")
    assert pr["pr_url"].endswith("/pull/1")
    assert pr["proof_url"]  # KaneAI replay link attached


# ── Confirmation flake (documented finding) ───────────────────────────

async def test_confirmation_flake_does_not_resolve(monkeypatch, iso_recordings):
    """A flaky confirmation run must not yield a falsely-RESOLVED state.

    Current behaviour: the orchestrator recurses into run_incident(), which
    re-runs REPRODUCE against the now-fixed app (green) and escalates with
    "Could not reproduce". Either way it must not end RESOLVED with a PR.
    """
    iso_recordings.CONFIRMATION_RUNS = 2
    # calls: 1=REPRODUCE(red) 2=VERIFY(green) 3=CONFIRM#1(green) 4=CONFIRM#2(FLAKE)
    loop = fakes.FakeLoop(fixed_after_patches=1, flake_calls={4})
    gh = fakes.install_loop(monkeypatch, loop)

    run = fakes.make_run()
    events = await fakes.drive_incident(run)

    assert events[-1]["event"] == "done"
    assert run.state is not State.RESOLVED
    assert len(gh.prs) == 0


# ── Reject path (documented finding) ──────────────────────────────────

@pytest.mark.xfail(
    strict=True,
    reason=(
        "FINDING: orchestrator does not check the approval verdict — after "
        "wait_for_approval() it proceeds straight to SHIP, so a rejected run "
        "still opens a PR. Expected: reject → STANDBY, no PR."
    ),
)
async def test_reject_at_gate_stands_down_without_pr(monkeypatch):
    loop = fakes.FakeLoop(fixed_after_patches=1)
    gh = fakes.install_loop(monkeypatch, loop)

    run = fakes.make_run()
    await fakes.drive_incident(run, approve=False, reject=True)

    assert run.state is State.STANDBY
    assert len(gh.prs) == 0


# ── helpers ───────────────────────────────────────────────────────────

def fakes_confirmation_runs() -> int:
    from app.config import settings
    return settings.CONFIRMATION_RUNS
