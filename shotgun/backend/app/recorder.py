"""
Shotgun — Run recorder + chain ledger.

Every run — successful or escalated — is written to disk as a self-contained
bundle and linked into a chain ledger. This is what makes the second loop
possible (you can only "review against the previous" if the previous is
recorded) and it doubles as an audit trail and a growing regression suite.

On-disk layout (one folder per run):
    recordings/
    ├── index.json                    # the chain ledger
    └── <run_id>/
        ├── run.json                   # full RunState snapshot (final)
        ├── events.ndjson              # every SSE event, in order
        ├── attempts/
        │   ├── 1/ kane_verify.json  screenshot.png
        │   └── …
        ├── repro/ kane_repro.json  screenshot.png
        ├── review/ review.json
        ├── flow.md                    # this run's testmd flow (carried forward)
        └── pr.json                    # pr_url, review_url, branch, diff
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from dataclasses import dataclass

from app.config import settings
from app.models import RunState

logger = logging.getLogger(__name__)


@dataclass
class Recording:
    """Result of finalizing a run's recording."""
    dir: str
    chain_length: int


def link_previous(run: RunState) -> str | None:
    """Called at INTAKE. Sets ``run.prev_run_id`` from the chain ledger head.

    Returns:
        The prior run_id, or None if this is the first recorded run.
    """
    idx = _load_index()
    run.prev_run_id = idx.get("head")
    logger.info(
        "[%s] Chained to previous run: %s",
        run.run_id,
        run.prev_run_id or "(none — first run)",
    )
    return run.prev_run_id


async def finalize(run: RunState) -> Recording:
    """Persist the full run as a self-contained recording bundle.

    Steps:
        1. Write run.json (full RunState snapshot)
        2. Carry forward this run's repro flow into the suite
        3. Persist PR + review pointers
        4. Update the chain ledger (this run becomes the new head)
        5. Enforce retention (delete old runs beyond RECORD_RETENTION)

    Returns:
        A ``Recording`` with the directory path and chain length.
    """
    d = os.path.join(settings.RECORDINGS_DIR, run.run_id)
    os.makedirs(os.path.join(d, "attempts"), exist_ok=True)
    os.makedirs(os.path.join(d, "repro"), exist_ok=True)
    os.makedirs(os.path.join(d, "review"), exist_ok=True)

    # 1. Snapshot the final state
    _write(os.path.join(d, "run.json"), run.model_dump(mode="json"))
    logger.info("[%s] Wrote run snapshot to %s", run.run_id, d)

    # events.ndjson is written live by the store's event mirror
    # (appended in store.publish → _mirror_event)

    # 2. Carry this run's repro flow forward into the suite
    if settings.KANE_REVIEW_CARRY_FORWARD and os.path.exists(run.incident.repro_flow):
        try:
            shutil.copy(run.incident.repro_flow, os.path.join(d, "flow.md"))
        except OSError as exc:
            logger.warning("[%s] Could not copy flow: %s", run.run_id, exc)

    # 3. Persist PR + review pointers
    _write(
        os.path.join(d, "pr.json"),
        {
            "pr_url": run.pr_url,
            "review_url": run.review.review_url if run.review else None,
            "branch": run.branch,
        },
    )

    # 4. Update the chain ledger (this run becomes the new head)
    idx = _load_index()
    idx.setdefault("runs", []).append({
        "run_id": run.run_id,
        "prev": run.prev_run_id,
        "pr": run.pr_url,
        "flow": os.path.join(d, "flow.md"),
        "status": run.state.value,
        "ts": time.time(),
    })
    idx["head"] = run.run_id
    _save_index(idx)

    # 5. Enforce retention
    _enforce_retention(idx)

    chain_length = len(idx["runs"])
    logger.info(
        "[%s] Recording finalized — chain length: %d, prev: %s",
        run.run_id, chain_length, run.prev_run_id,
    )
    return Recording(dir=d, chain_length=chain_length)


def previous_flows(run: RunState) -> list[str]:
    """The regression suite for kane_review: every recorded run's flow,
    newest-previous first.

    With CARRY_FORWARD enabled, this set only ever grows — each run's
    repro flow is added to the suite for the next run, so coverage
    compounds over the chain.
    """
    idx = _load_index()
    flows = [
        r["flow"]
        for r in idx.get("runs", [])
        if os.path.exists(r.get("flow", ""))
    ]
    return flows


def get_chain_length() -> int:
    """Return the number of recorded runs in the chain."""
    idx = _load_index()
    return len(idx.get("runs", []))


# ── Private helpers ───────────────────────────────────


def _load_index() -> dict:
    """Load the chain ledger from disk."""
    p = settings.RECORD_INDEX_FILE
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            logger.warning("Corrupt index file %s — starting fresh", p)
    return {"head": None, "runs": []}


def _save_index(idx: dict) -> None:
    """Write the chain ledger to disk."""
    os.makedirs(os.path.dirname(settings.RECORD_INDEX_FILE), exist_ok=True)
    with open(settings.RECORD_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(idx, f, indent=2)


def _write(path: str, data: dict) -> None:
    """Write a JSON file, creating parent dirs as needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def _enforce_retention(idx: dict) -> None:
    """Delete the oldest recordings if we exceed RECORD_RETENTION."""
    if settings.RECORD_RETENTION <= 0:
        return  # unlimited

    runs = idx.get("runs", [])
    if len(runs) <= settings.RECORD_RETENTION:
        return

    # Remove the oldest runs beyond the retention limit
    to_remove = runs[: len(runs) - settings.RECORD_RETENTION]
    for r in to_remove:
        run_dir = os.path.join(settings.RECORDINGS_DIR, r["run_id"])
        if os.path.isdir(run_dir):
            try:
                shutil.rmtree(run_dir)
                logger.info("Retention: removed old recording %s", r["run_id"])
            except OSError as exc:
                logger.warning("Retention: failed to remove %s — %s", run_dir, exc)

    # Update the index to reflect removals
    idx["runs"] = runs[len(to_remove):]
    _save_index(idx)
