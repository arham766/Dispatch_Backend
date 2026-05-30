"""
Shotgun backend — pytest shared configuration & fixtures.

NEW test-only module. Does not import or modify any application file at
collection time except to put the backend root on sys.path so `import app`
works regardless of pytest's import mode.

Isolation strategy (autouse, per-test):
  * `iso_recordings` redirects the recorder to a fresh tmp dir and resets
    the orchestration knobs (retry budget, confirmation runs, review flags)
    to deterministic values, restoring originals afterwards.
  * `reset_store` clears the module-level in-memory RunStore singleton so
    runs/queues/approvals never leak between tests.
"""

from __future__ import annotations

import os
import sys

# ── Make `import app` work no matter the pytest import mode ────────────
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

# ── Point side-effecting paths at a throwaway dir BEFORE app.config is
#    ever imported (pydantic-settings reads env at Settings() construction).
_ENV_DEFAULTS = {
    "RECORDINGS_DIR": os.path.join(_BACKEND_ROOT, ".pytest_recordings"),
    "RECORD_INDEX_FILE": os.path.join(_BACKEND_ROOT, ".pytest_recordings", "index.json"),
    "KANE_REVIEW_ENABLED": "false",
    "INTAKE_MODE": "webhook",
    "DATABASE_URL": "",
    "GITHUB_TOKEN": "",
}
for _k, _v in _ENV_DEFAULTS.items():
    os.environ.setdefault(_k, _v)

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def iso_recordings(tmp_path):
    """Redirect recordings to tmp_path and pin deterministic orchestrator knobs."""
    from app.config import settings

    saved = {
        k: getattr(settings, k)
        for k in (
            "RECORDINGS_DIR",
            "RECORD_INDEX_FILE",
            "RECORD_RETENTION",
            "RECORD_LOOPS",
            "RETRY_BUDGET",
            "CONFIRMATION_RUNS",
            "KANE_TIMEOUT_SECONDS",
            "KANE_REVIEW_ENABLED",
            "KANE_REVIEW_MODE",
            "KANE_REVIEW_BUDGET",
            "KANE_REVIEW_BLOCK_ON_REGRESSION",
            "KANE_REVIEW_POST_AS",
            "KANE_REVIEW_CARRY_FORWARD",
        )
    }

    rec = tmp_path / "recordings"
    settings.RECORDINGS_DIR = str(rec)
    settings.RECORD_INDEX_FILE = str(rec / "index.json")
    settings.RECORD_RETENTION = 50
    settings.RECORD_LOOPS = True
    settings.RETRY_BUDGET = 3
    settings.CONFIRMATION_RUNS = 2
    settings.KANE_TIMEOUT_SECONDS = 5
    settings.KANE_REVIEW_ENABLED = False
    settings.KANE_REVIEW_MODE = "standalone"
    settings.KANE_REVIEW_BUDGET = 2
    settings.KANE_REVIEW_BLOCK_ON_REGRESSION = True
    settings.KANE_REVIEW_POST_AS = "review"
    settings.KANE_REVIEW_CARRY_FORWARD = True

    yield settings

    for k, v in saved.items():
        setattr(settings, k, v)


@pytest.fixture(autouse=True)
def reset_store():
    """Clear the in-memory RunStore singleton before and after each test."""
    from app.store import store

    def _clear():
        store._runs.clear()
        store._queues.clear()
        store._approvals.clear()
        store._decisions.clear()
        store._decision_values.clear()
        store._event_files.clear()

    _clear()
    yield store
    _clear()
