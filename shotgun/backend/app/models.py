"""
Shotgun — Pydantic data models.

Defines every data structure the system operates on:
  - Incident         (normalized alert from any source)
  - State            (15-state enum for the state machine)
  - KaneResult       (parsed Kane run_end event)
  - PatchResult      (Kiro's output)
  - ReviewResult     (kane_review outcome)
  - RunState         (full mutable state of one incident run)
"""

from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field
import time
import uuid


class Incident(BaseModel):
    """Normalized incident. Webhooks (PagerDuty/Sentry/JSON) map into this."""
    service: str
    symptom: str                                    # human description
    suspect_url: str                                # the browser flow Kane will exercise
    repro_flow: str                                 # path to the Kane testmd flow file
    recent_diff_hint: str | None = None             # file/area Kiro should focus on
    source: Literal["pagerduty", "sentry", "manual", "kafka"] = "manual"


class State(str, Enum):
    """All states of the closed-loop state machine.

    Covers both the Shotgun and Dispatch (CEO spec) vocabularies.
    """
    INTAKE = "INTAKE"                               # Dispatch: RECEIVED
    REPRODUCE = "REPRODUCE"                         # Dispatch: DIAGNOSING (diagnosis loop)
    CALLING = "CALLING"                             # AgentPhone dials + reads diagnosis (voice)
    AWAITING_DECISION = "AWAITING_DECISION"         # waiting on spoken fix/dismiss
    PATCH = "PATCH"                                 # Dispatch: FIXING (remediation loop)
    VERIFY = "VERIFY"
    DECIDE = "DECIDE"
    CONFIRM = "CONFIRM"
    HUMAN_GATE = "HUMAN_GATE"                       # web-app approval (alt/parallel to CALLING)
    SHIP = "SHIP"                                   # Dispatch: PR_OPENING
    REVIEW = "REVIEW"                               # second loop: kane_review vs. previous
    REVIEW_DECIDE = "REVIEW_DECIDE"                 # regression found → re-enter fix loop
    RECORD = "RECORD"                               # persist + chain this run
    ESCALATE = "ESCALATE"                           # Dispatch: ESCALATED
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"                         # engineer declined the fix (voice/web)
    STANDBY = "STANDBY"


class KaneResult(BaseModel):
    """Parsed from Kane's run_end event + exit code."""
    passed: bool
    exit_code: int                                  # 0 pass / 1 fail / 2 error / 3 timeout
    summary: str = ""
    one_liner: str = ""
    reason: str = ""
    duration: float = 0.0
    credits: int | None = None
    final_state: dict[str, Any] = Field(default_factory=dict)
    screenshot_path: str | None = None
    run_dir: str | None = None
    test_url: str | None = None                     # KaneAI dashboard deep link (proof)


class PatchResult(BaseModel):
    """Output from a Kiro patch attempt."""
    branch: str
    diff_summary: str
    changed_files: list[str] = Field(default_factory=list)
    ok: bool = True


class ReviewResult(BaseModel):
    """Outcome of the kane_review pass against the new PR branch."""
    passed: bool                                    # True = no regression vs. the suite
    flows_run: list[str] = Field(default_factory=list)
    regressed_flows: list[str] = Field(default_factory=list)
    review_url: str | None = None                   # the posted GitHub PR review
    details: list[KaneResult] = Field(default_factory=list)


class RunState(BaseModel):
    """Full mutable state of one incident run through the loop.

    `prev_run_id` is the chain link: it points at the most recent recorded run,
    and `kane_review` always replays *that* run's flows (plus the whole accumulated
    suite) against the new PR. Every run is reviewed relative to the one before it,
    forming an unbroken chain.
    """
    run_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    incident: Incident
    state: State = State.INTAKE
    attempt: int = 0
    retry_budget: int = 3
    branch: str | None = None
    last_kane: KaneResult | None = None
    pr_url: str | None = None
    created_at: float = Field(default_factory=time.time)
    awaiting_approval: bool = False

    # --- recording + chained review ---
    prev_run_id: str | None = None                  # chain link to previous recorded run
    review_budget: int = 2
    review: ReviewResult | None = None
    recording_dir: str | None = None                # recordings/<run_id>/
