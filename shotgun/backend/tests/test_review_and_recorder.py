"""
Integration tests for the second closed loop (kane_review) and the
recorder chain ledger.

Covers:
  * REVIEW posts an approving PR review when the suite stays green.
  * A regression re-enters the fix loop and re-reviews (budget-bounded).
  * The chain ledger links each run to its predecessor and grows the suite.
  * Retention trims old recordings.
"""

from __future__ import annotations

import json
import os

import pytest

from app.models import State
from tests import fakes


pytestmark = pytest.mark.integration


# ── Recorder / chain ledger ───────────────────────────────────────────

async def test_recording_bundle_written(monkeypatch, iso_recordings):
    loop = fakes.FakeLoop(fixed_after_patches=1)
    fakes.install_loop(monkeypatch, loop)

    run = fakes.make_run()
    await fakes.drive_incident(run)

    d = run.recording_dir
    assert d and os.path.isdir(d)
    assert os.path.exists(os.path.join(d, "run.json"))
    assert os.path.exists(os.path.join(d, "pr.json"))
    # The live event mirror produced the replayable timeline.
    assert os.path.exists(os.path.join(d, "events.ndjson"))

    pr = json.load(open(os.path.join(d, "pr.json")))
    assert pr["pr_url"].endswith("/pull/1")
    assert pr["branch"].startswith("shotgun/fix-checkout")


async def test_events_ndjson_replayable(monkeypatch):
    loop = fakes.FakeLoop(fixed_after_patches=1)
    fakes.install_loop(monkeypatch, loop)

    run = fakes.make_run()
    events = await fakes.drive_incident(run)

    lines = [
        json.loads(l)
        for l in open(os.path.join(run.recording_dir, "events.ndjson"), encoding="utf-8")
        if l.strip()
    ]
    # Mirror should hold (almost) every published event in order.
    assert [l["event"] for l in lines][:1] == ["state_change"]
    assert any(l["event"] == "pr_opened" for l in lines)


async def test_chain_links_three_runs(monkeypatch, iso_recordings):
    loop = fakes.FakeLoop(fixed_after_patches=1)
    fakes.install_loop(monkeypatch, loop)

    ids = []
    for _ in range(3):
        loop.patches = 0  # reset the fake world per run
        run = fakes.make_run()
        await fakes.drive_incident(run)
        ids.append(run.run_id)

    idx = json.load(open(iso_recordings.RECORD_INDEX_FILE))
    assert idx["head"] == ids[-1]
    assert len(idx["runs"]) == 3
    assert idx["runs"][0]["prev"] is None
    assert idx["runs"][1]["prev"] == ids[0]
    assert idx["runs"][2]["prev"] == ids[1]


async def test_prev_run_id_set_from_ledger(monkeypatch):
    loop = fakes.FakeLoop(fixed_after_patches=1)
    fakes.install_loop(monkeypatch, loop)

    first = fakes.make_run()
    await fakes.drive_incident(first)
    assert first.prev_run_id is None

    loop.patches = 0
    second = fakes.make_run()
    await fakes.drive_incident(second)
    assert second.prev_run_id == first.run_id


async def test_retention_trims_old_recordings(monkeypatch, iso_recordings):
    iso_recordings.RECORD_RETENTION = 2
    loop = fakes.FakeLoop(fixed_after_patches=1)
    fakes.install_loop(monkeypatch, loop)

    for _ in range(4):
        loop.patches = 0
        await fakes.drive_incident(fakes.make_run())

    idx = json.load(open(iso_recordings.RECORD_INDEX_FILE))
    assert len(idx["runs"]) == 2
    # Only the surviving run dirs remain on disk.
    remaining = {
        name for name in os.listdir(iso_recordings.RECORDINGS_DIR)
        if os.path.isdir(os.path.join(iso_recordings.RECORDINGS_DIR, name))
    }
    assert len(remaining) <= 2


# ── kane_review: the second loop ──────────────────────────────────────

async def test_review_approves_when_suite_green(monkeypatch, iso_recordings, tmp_path):
    iso_recordings.KANE_REVIEW_ENABLED = True
    iso_recordings.KANE_REVIEW_MODE = "standalone"
    loop = fakes.FakeLoop(fixed_after_patches=1)
    gh = fakes.install_loop(monkeypatch, loop)

    # flow file must exist on disk for kane_review to include it
    flow = _make_flow(tmp_path)
    run = fakes.make_run(repro_flow=flow)
    events = await fakes.drive_incident(run)

    assert run.state is State.RESOLVED
    rr = fakes.first(events, "review_result")
    assert rr is not None and rr["passed"] is True
    assert len(gh.reviews) == 1
    assert gh.reviews[0]["event"] == "APPROVE"


async def test_review_regression_reenters_fix_loop(monkeypatch, iso_recordings, tmp_path):
    """A red review must request changes and re-patch (not silently pass)."""
    iso_recordings.KANE_REVIEW_ENABLED = True
    iso_recordings.KANE_REVIEW_MODE = "standalone"
    iso_recordings.KANE_REVIEW_BUDGET = 2
    flow = _make_flow(tmp_path)

    # Kane calls: 1 REPRODUCE(red) 2 VERIFY(green) 3-4 CONFIRM(green)
    # 5 REVIEW(FLAKE→regression) → re-patch → 6 VERIFY-in-review ...
    loop = fakes.FakeLoop(fixed_after_patches=1, flake_calls={5})
    gh = fakes.install_loop(monkeypatch, loop)

    run = fakes.make_run(repro_flow=flow)
    events = await fakes.drive_incident(run)

    reviews = [e for e in events if e["event"] == "review_result"]
    assert len(reviews) >= 2, "expected a failing review then a passing one"
    assert reviews[0]["passed"] is False
    assert any(r["event"] == "REQUEST_CHANGES" for r in gh.reviews)
    assert run.state is State.RESOLVED


async def test_review_budget_exhausted_escalates(monkeypatch, iso_recordings, tmp_path):
    iso_recordings.KANE_REVIEW_ENABLED = True
    iso_recordings.KANE_REVIEW_MODE = "standalone"
    iso_recordings.KANE_REVIEW_BUDGET = 1
    flow = _make_flow(tmp_path)

    # Force every REVIEW replay red (calls 5+), so the budget runs out.
    loop = fakes.FakeLoop(fixed_after_patches=1, flake_calls=set(range(5, 40)))
    fakes.install_loop(monkeypatch, loop)

    run = fakes.make_run(repro_flow=flow)
    events = await fakes.drive_incident(run)

    assert run.state is State.ESCALATE
    esc = fakes.first(events, "escalated")
    assert "regress" in esc["reason"].lower()


# ── helpers ───────────────────────────────────────────────────────────

def _make_flow(tmp_path) -> str:
    """Create a flow file inside the test's tmp dir (never in the repo)."""
    path = tmp_path / "flow.md"
    path.write_text("# test flow\n", encoding="utf-8")
    return str(path)
