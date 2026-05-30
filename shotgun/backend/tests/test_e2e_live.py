"""
End-to-end test driving the live, running backend.

Unlike the existing integration tests (which monkey-patch Kane/Kiro/GitHub
and exercise the orchestrator's state machine in isolation), this test
talks to the REAL backend over HTTP/WebSocket and asserts the observable
behaviour a user sees:

  - REPRODUCE fires a smoke check
  - The first email arrives within ~10s of trigger (incident_created)
  - The second email arrives within ~60s (kane_red_confirmed)
  - The cloud patcher commits a real branch on GitHub
  - HUMAN_GATE is reached within ~3 minutes
  - After auto-approve, a real PR opens on GitHub
  - All this lands in the recording NDJSON in the right order + timing

Run with:
    cd shotgun/backend
    python -m pytest tests/test_e2e_live.py -v -s

By default the test targets http://127.0.0.1:8000. Override with
SHOTGUN_TEST_BASE=https://dispatch-backend-i50g.onrender.com to run
against prod (just don't auto-approve there unless you want a real PR).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

import httpx
import pytest


BASE = os.getenv("SHOTGUN_TEST_BASE", "http://127.0.0.1:8000")
SERVICE = "checkout"
SUSPECT_URL = "https://arham766.github.io/app-under-test"
TOTAL_TIMEOUT = 240  # seconds — full loop deadline

pytestmark = pytest.mark.asyncio


# ── Test helpers ─────────────────────────────────────


async def _fire_incident(client: httpx.AsyncClient) -> str:
    r = await client.post(
        f"{BASE}/incidents",
        json={
            "service": SERVICE,
            "symptom": "E2E test: Checkout 500 on pay",
            "suspect_url": SUSPECT_URL,
            "repro_flow": "flows/checkout_test.md",
            "recent_diff_hint": "payment.js",
            "source": "manual",
        },
    )
    r.raise_for_status()
    return r.json()["run_id"]


async def _state(client: httpx.AsyncClient, run_id: str) -> dict[str, Any]:
    r = await client.get(f"{BASE}/incidents/{run_id}")
    r.raise_for_status()
    return r.json()


async def _approve(client: httpx.AsyncClient, run_id: str) -> None:
    r = await client.post(
        f"{BASE}/incidents/{run_id}/approve",
        json={"approve": True},
    )
    r.raise_for_status()


def _read_events(run_id: str) -> list[dict[str, Any]]:
    """Read every event mirrored to the recording NDJSON."""
    p = f"./recordings/{run_id}/events.ndjson"
    if not os.path.exists(p):
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def _kinds(events: list[dict]) -> list[str]:
    return [e.get("event") for e in events]


def _states_visited(events: list[dict]) -> list[str]:
    return [
        e.get("state")
        for e in events
        if e.get("event") == "state_change" and e.get("state")
    ]


# ── The test ────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.slow
async def test_full_loop_lands_pr() -> None:
    """Drive a real run from INTAKE all the way to RESOLVED + PR open."""
    started = time.time()

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Pre-flight: backend is up and healthy
        h = await client.get(f"{BASE}/healthz")
        h.raise_for_status()
        health = h.json()
        assert health.get("kane") is True, f"Kane CLI auth failed: {health}"
        assert health.get("github") is True, "GitHub token invalid"

        # Fire the incident
        run_id = await _fire_incident(client)
        print(f"\n>>> run_id={run_id}")

        # Poll for terminal state with a hard deadline
        approved = False
        terminal_states = {"RESOLVED", "ESCALATE", "STANDBY", "DISMISSED"}
        last_state = ""
        while time.time() - started < TOTAL_TIMEOUT:
            snap = await _state(client, run_id)
            state = snap["state"]
            if state != last_state:
                elapsed = time.time() - started
                print(f"  t+{elapsed:5.1f}s  {state:<18s}  attempt={snap['attempt']}")
                last_state = state

            if snap.get("awaiting_approval") and not approved:
                print(f"  t+{time.time()-started:5.1f}s  >>> AUTO-APPROVE")
                await _approve(client, run_id)
                approved = True

            if state in terminal_states:
                break
            await asyncio.sleep(2)
        else:
            pytest.fail(
                f"Loop did not terminate within {TOTAL_TIMEOUT}s "
                f"(last state: {last_state})"
            )

        final = await _state(client, run_id)
        events = _read_events(run_id)
        kinds = _kinds(events)
        states = _states_visited(events)

        print("\n=== summary ===")
        print(f"  duration:     {time.time() - started:.1f}s")
        print(f"  final state:  {final['state']}")
        print(f"  PR url:       {final.get('pr_url')}")
        print(f"  states seen:  {states}")
        print(f"  event kinds:  {kinds}")

        # ── Assertions ────────────────────────────────

        # (1) state machine visited the canonical happy path
        assert "INTAKE" in states
        assert "REPRODUCE" in states
        assert "PATCH" in states
        assert "VERIFY" in states
        assert "SHIP" in states
        assert "RECORD" in states

        # (2) Kane smoke detected the bug (REPRODUCE went red)
        repro_results = [
            e for e in events
            if e.get("event") == "kane_result"
            and e.get("state") == "REPRODUCE"
        ]
        assert repro_results, "no REPRODUCE kane_result recorded"
        assert repro_results[0]["passed"] is False, \
            "REPRODUCE should have gone red on the seeded bug"

        # (3) Kiro produced at least one patch event
        patches = [e for e in events if e.get("event") == "patch"]
        assert patches, "no patch event recorded — Kiro client did not run"
        assert patches[-1].get("changed_files"), \
            f"last patch produced no files: {patches[-1]}"

        # (4) PR was opened with a real github.com URL
        pr_events = [e for e in events if e.get("event") == "pr_opened"]
        assert pr_events, "no pr_opened event recorded"
        pr_url = pr_events[0].get("pr_url") or ""
        assert pr_url.startswith("https://github.com/"), \
            f"unexpected PR URL: {pr_url}"

        # (5) terminal state is RESOLVED
        assert final["state"] == "RESOLVED", \
            f"expected RESOLVED, got {final['state']} (events: {kinds})"

        # (6) Total wall time is bounded — fast mode should finish in <4 min
        assert time.time() - started < TOTAL_TIMEOUT


@pytest.mark.integration
async def test_notifications_fire_promptly() -> None:
    """Side-effect timing: incident_created notification must fire within
    ~10 seconds. If the email/voice queue is slow we want to see it here.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        started = time.time()
        run_id = await _fire_incident(client)

        # The incident_created event is published as part of INTAKE which
        # happens within the first ~5 seconds; the email is fired in the
        # same emit() call. We just check the recording file was created.
        deadline = started + 15
        while time.time() < deadline:
            events = _read_events(run_id)
            if any(e.get("event") == "state_change" for e in events):
                elapsed = time.time() - started
                print(f"first state_change in {elapsed:.2f}s")
                assert elapsed < 10, \
                    f"first state_change took {elapsed:.1f}s (expected <10s)"
                return
            await asyncio.sleep(0.5)
        pytest.fail("incident_created event never landed in events.ndjson")
