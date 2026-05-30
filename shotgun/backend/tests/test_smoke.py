"""Smoke test — proves the harness wires the real orchestrator to the fakes."""

from __future__ import annotations

import pytest

from tests import fakes


@pytest.mark.integration
async def test_happy_path_red_then_green(monkeypatch):
    loop = fakes.FakeLoop(fixed_after_patches=1)
    gh = fakes.install_loop(monkeypatch, loop)

    run = fakes.make_run()
    events = await fakes.drive_incident(run)

    kinds = fakes.types_of(events)
    assert "kane_result" in kinds
    assert "pr_opened" in kinds
    assert events[-1]["event"] == "done"
    assert events[-1]["final_state"] == "RESOLVED"
    assert run.state.value == "RESOLVED"
    assert len(gh.prs) == 1
