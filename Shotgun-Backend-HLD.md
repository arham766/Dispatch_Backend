# Shotgun / Dispatch — Backend High-Level Design (Developer Edition)

*An on-call copilot that diagnoses, fixes, and proves the fix.*

**Closed-loop incident remediation: Kiro writes the fix, Kane proves it, the web app shows it go green.**

Stack: **FastAPI** (orchestrator + API) · **Next.js** (minimal front end) · **Kane CLI** (verifier) · **AWS Kiro** (in-loop code fixer) · **Kafka** (intake) · **Postgres** (datastore) · **Render** (deploy) · run from **Warp**.

Build target: TestMu AI × dev.to one-day hack day. Working doc · v2.0 · for development.

> **v2.0 note — this doc now integrates the CEO "Dispatch" spec.** Dispatch and Shotgun are the **same product**; Dispatch is the enterprise framing (Kafka in front, Postgres underneath, AgentPhone voice, the Kiro Bridge as a file-watch seam). The mapping, the Render deployment topology, and the Kafka/Postgres/voice additions are in **Part C (§17–§22)**. Two decisions are taken as defaults there and flagged so you can flip them: **(1)** Render hosts the dashboard + app-under-test + Postgres while the Kiro↔Kane loop stays local; **(2)** Kafka is managed (Upstash/Redpanda) behind a swappable interface, with a Postgres-queue fallback.

---

## 0. Read this first — the one rule everything hangs on

The scored "closed loop" is: **a Kiro hook fires Kane → Kane fails → Kiro reads the failure → Kiro patches → the hook re-fires → Kane goes green.** Kiro must be the agent that writes the in-loop fix. The FastAPI service is *orchestration only* — it never writes the fix itself. If FastAPI (or you, or Warp's agent) generates the patch, you forfeit the highest-value judging dimension.

So the backend's job is narrow and well-defined:

1. Take an incident in.
2. Ask Kane to reproduce the bug (expect red).
3. Ask Kiro to patch (Kiro does the thinking).
4. Ask Kane to verify (expect green).
5. Loop with a bounded retry budget, feeding Kane's failure back to Kiro each time.
6. Gate on a human, then open a GitHub PR with Kane's proof attached.
7. Stream every transition to the front end so the room watches it happen.

That is ~200 lines of real control flow. Everything below is how to build those 200 lines cleanly, in three phases, so that **if the clock runs out you still have a winning-eligible submission at every stopping point.**

---

## 1. Architecture at a glance

```
                          ┌──────────────────────────────┐
   incident (webhook/JSON) │         FastAPI service       │
   ───────────────────────►│                              │
                            │  POST /incidents             │
                            │       │                      │
                            │       ▼                      │
                            │  ┌─────────────────────┐     │
                            │  │   Orchestrator      │     │
                            │  │  (state machine)    │     │
                            │  └─────────────────────┘     │
                            │     │        │        │      │
                            │  Kane     Kiro      GitHub    │
                            │  runner   client    client    │
                            └────┼────────┼─────────┼───────┘
                                 │        │         │
                       subprocess│        │ headless│ REST
                          NDJSON │        │ or hook │
                                 ▼        ▼         ▼
                          ┌──────────┐ ┌──────┐ ┌─────────┐
                          │ Kane CLI │ │ Kiro │ │ GitHub  │
                          │ (Chrome) │ │agent │ │  PR API │
                          └──────────┘ └──────┘ └─────────┘
                                 │
                                 │  staging app under test (seeded bug)
                                 ▼
                          ┌────────────────────┐
                          │  App Under Test     │
                          │  (stable staging)   │
                          └────────────────────┘

   live stream (Server-Sent Events) ──────────────► Next.js front end
                                                     (split-screen loop view)
```

**Why these choices:**

| Decision | Rationale |
|---|---|
| FastAPI, async | Kane/Kiro calls are long-running I/O. `async` + subprocess streaming lets one worker drive the loop and fan out live events without blocking. |
| Server-Sent Events (SSE) for the live view | One-directional, dead simple, auto-reconnects, no WebSocket handshake complexity. The loop only pushes; control actions come back as plain POSTs. |
| Kane via subprocess NDJSON | Kane's `--agent` mode emits one JSON object per line on stdout. Parse line-by-line; key automation off the `run_end` event (stable schema) and exit code. |
| Kiro behind an interface | The open risk is whether Kiro can be driven headlessly. Hide it behind `KiroAgent` with two implementations so the orchestrator never changes when you learn the answer. |
| In-memory run store (Phase 1–2), optional SQLite (Phase 3) | A hackathon doesn't need a database to win. Keep state in a dict keyed by `run_id`; persist only if you have spare time. |

---

## 2. Repository & module layout

```
shotgun/
├── backend/
│   ├── pyproject.toml            # or requirements.txt
│   ├── .env.example
│   ├── app/
│   │   ├── main.py               # FastAPI app, lifespan, route registration
│   │   ├── config.py             # Settings (pydantic-settings); env vars
│   │   ├── models.py             # Pydantic models (Incident, RunState, events…)
│   │   ├── store.py              # In-memory run registry + event bus
│   │   ├── events.py             # SSE event types + serializer
│   │   ├── orchestrator.py       # THE state machine (core IP)
│   │   ├── clients/
│   │   │   ├── kane.py           # Kane CLI runner + NDJSON parser
│   │   │   ├── kane_review.py    # kane_review: chained regression review loop (§16)
│   │   │   ├── kiro.py           # KiroAgent interface + 2 implementations
│   │   │   ├── agentphone.py     # AgentPhone voice: call + decision webhook (§21)
│   │   │   └── github_pr.py      # Branch + PR + PR review with Kane proof
│   │   ├── recorder.py           # persists each run + maintains the chain ledger (§15)
│   │   ├── db.py                 # Postgres layer (incidents/runs/artifacts) (§20)
│   │   ├── intake/
│   │   │   ├── kafka_consumer.py # Dispatch frontend.incidents consumer (§19)
│   │   │   └── normalize.py      # Kafka/Sentry/PagerDuty/JSON -> Incident
│   │   └── routes/
│   │       ├── incidents.py      # POST /incidents, POST /incidents/{id}/approve
│   │       ├── stream.py         # GET /incidents/{id}/stream  (SSE)
│   │       └── health.py         # GET /healthz
│   ├── flows/
│   │   └── checkout_test.md      # Kane testmd repro flow (committed)
│   └── examples/
│       └── checkout-500.json     # Seeded incident the judges can run
└── frontend/                     # Next.js (Phase 3)
    ├── package.json
    ├── app/
    │   ├── page.tsx              # Single page: trigger + split-screen loop
    │   └── components/
    │       ├── LoopTimeline.tsx
    │       ├── KaneScreen.tsx
    │       └── PrCard.tsx
    └── lib/useIncidentStream.ts  # EventSource hook
```

**Dependencies (`backend/requirements.txt`):**

```
fastapi>=0.111
uvicorn[standard]>=0.30
pydantic>=2.7
pydantic-settings>=2.3
httpx>=0.27          # GitHub API + any webhook callbacks
sse-starlette>=2.1   # clean SSE responses
PyGithub>=2.3        # optional convenience for PRs (or use httpx directly)
```

**Environment (`.env.example`):**

```
# Kane CLI
LT_USERNAME=
LT_ACCESS_KEY=
KANE_HEADLESS=true

# App under test
STAGING_BASE_URL=https://shotgun-staging.example.com

# Kiro
KIRO_MODE=headless          # headless | hook  (see §6)
KIRO_WORKDIR=/abs/path/to/app-under-test-repo
KIRO_TRIGGER_FILE=.shotgun/trigger.json   # used only in hook mode

# GitHub
GITHUB_TOKEN=
GITHUB_REPO=your-org/app-under-test
GITHUB_BASE_BRANCH=main

# Orchestrator
RETRY_BUDGET=3
CONFIRMATION_RUNS=3
KANE_TIMEOUT_SECONDS=120

# Recording — persist every loop iteration for audit + replay (§15)
RECORD_LOOPS=true
RECORDINGS_DIR=./recordings           # one folder per run_id; survives restarts
RECORD_RETENTION=50                   # keep the last N run recordings (0 = unlimited)
RECORD_INDEX_FILE=./recordings/index.json   # chain ledger: run -> prev_run, pr, flows

# Kane Review — the second, automatic closed loop (§16)
KANE_REVIEW_ENABLED=true
KANE_REVIEW_MODE=chained              # chained | standalone
#   chained    = always review the NEW pr against the PREVIOUS recorded run/PR
#   standalone = review only the current fix, no back-reference
KANE_REVIEW_BUDGET=2                  # how many review->repatch cycles allowed
KANE_REVIEW_BLOCK_ON_REGRESSION=true  # red review = request changes, re-enter loop
KANE_REVIEW_FLOWS_DIR=./flows         # all committed testmd flows replayed as the regression suite
KANE_REVIEW_CARRY_FORWARD=true        # add this run's repro flow into the suite for the NEXT run
KANE_REVIEW_POST_AS=review            # review | comment  (GitHub PR review vs plain comment)

# Kafka intake — Dispatch incident topic (§19). Behind a swappable interface.
INTAKE_MODE=kafka                     # kafka | postgres_queue | webhook
KAFKA_BROKERS=                        # Upstash/Redpanda bootstrap servers (host:9092)
KAFKA_TOPIC=frontend.incidents
KAFKA_GROUP_ID=dispatch-orchestrator
KAFKA_USERNAME=                       # SASL (Upstash uses SCRAM)
KAFKA_PASSWORD=
KAFKA_SASL_MECHANISM=SCRAM-SHA-256

# Datastore — Render Postgres (§20)
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dispatch
DB_POOL_SIZE=5

# Deploy / topology (§17–§18)
PUBLIC_DASHBOARD_URL=https://dispatch-dashboard.onrender.com
STAGING_BASE_URL=https://dispatch-app-under-test.onrender.com   # the app Kane hits (on Render)
LOOP_LOCATION=local                   # local (Kiro+Kane on laptop) — do NOT set to render
STATUS_BUS=postgres                   # postgres | tunnel  (how local loop feeds the public dash)
STATUS_POLL_MS=1000                   # dashboard/orchestrator poll interval

# AgentPhone — voice layer (§21), last to build, tap-to-talk fallback
AGENTPHONE_ENABLED=false              # turn on only after the silent loop is green
AGENTPHONE_API_URL=
AGENTPHONE_API_KEY=
AGENTPHONE_FROM=+10000000000
ONCALL_PHONE=+10000000000
AGENTPHONE_NO_ANSWER_TIMEOUT=45       # seconds before CALLING -> ESCALATED
```

---

## 3. Data models (`app/models.py`)

```python
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field
import time, uuid


class Incident(BaseModel):
    """Normalized incident. Webhooks (PagerDuty/Sentry/JSON) map into this."""
    service: str
    symptom: str                       # human description
    suspect_url: str                   # the browser flow Kane will exercise
    repro_flow: str                    # path to the Kane testmd flow file
    recent_diff_hint: str | None = None  # file/area Kiro should focus on
    source: Literal["pagerduty", "sentry", "manual"] = "manual"


class State(str, Enum):
    INTAKE = "INTAKE"                   # Dispatch: RECEIVED
    REPRODUCE = "REPRODUCE"             # Dispatch: DIAGNOSING (diagnosis loop)
    CALLING = "CALLING"                 # AgentPhone dials + reads diagnosis (voice)
    AWAITING_DECISION = "AWAITING_DECISION"  # waiting on spoken fix/dismiss
    PATCH = "PATCH"                     # Dispatch: FIXING (remediation loop)
    VERIFY = "VERIFY"
    DECIDE = "DECIDE"
    CONFIRM = "CONFIRM"
    HUMAN_GATE = "HUMAN_GATE"           # web-app approval (alt/parallel to CALLING)
    SHIP = "SHIP"                       # Dispatch: PR_OPENING
    REVIEW = "REVIEW"                   # second loop: kane_review vs. previous
    REVIEW_DECIDE = "REVIEW_DECIDE"     # regression found -> re-enter fix loop
    RECORD = "RECORD"                   # persist + chain this run
    ESCALATE = "ESCALATE"               # Dispatch: ESCALATED
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"             # engineer declined the fix (voice/web)
    STANDBY = "STANDBY"


class KaneResult(BaseModel):
    """Parsed from Kane's run_end event + exit code."""
    passed: bool
    exit_code: int                     # 0 pass / 1 fail / 2 error / 3 timeout
    summary: str = ""
    one_liner: str = ""
    reason: str = ""
    duration: float = 0.0
    credits: int | None = None
    final_state: dict[str, Any] = Field(default_factory=dict)
    screenshot_path: str | None = None
    run_dir: str | None = None
    test_url: str | None = None        # KaneAI dashboard deep link (proof)


class PatchResult(BaseModel):
    branch: str
    diff_summary: str
    changed_files: list[str] = Field(default_factory=list)
    ok: bool = True


class ReviewResult(BaseModel):
    """Outcome of the kane_review pass against the new PR branch."""
    passed: bool                       # True = no regression vs. the suite
    flows_run: list[str] = Field(default_factory=list)
    regressed_flows: list[str] = Field(default_factory=list)
    review_url: str | None = None      # the posted GitHub PR review
    details: list[KaneResult] = Field(default_factory=list)


class RunState(BaseModel):
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
    prev_run_id: str | None = None     # the run this one reviews against (chain link)
    review_budget: int = 2
    review: ReviewResult | None = None
    recording_dir: str | None = None   # recordings/<run_id>/
```

`prev_run_id` is the chain link: it points at the most recent recorded run, and `kane_review` always replays *that* run's flows (plus the whole accumulated suite) against the new PR. That is the "always review against the previous" requirement — every run is reviewed relative to the one before it, forming an unbroken chain.

---

## 4. The event bus & SSE schema (`app/store.py`, `app/events.py`)

The orchestrator and the SSE endpoint never call each other directly. They communicate through a per-run `asyncio.Queue`. The orchestrator publishes; every connected browser subscribes.

```python
# store.py
import asyncio
from app.models import RunState

class RunStore:
    def __init__(self):
        self._runs: dict[str, RunState] = {}
        self._queues: dict[str, list[asyncio.Queue]] = {}
        self._approvals: dict[str, asyncio.Event] = {}

    def create(self, run: RunState):
        self._runs[run.run_id] = run
        self._queues[run.run_id] = []
        self._approvals[run.run_id] = asyncio.Event()
        return run

    def get(self, run_id): return self._runs.get(run_id)

    async def publish(self, run_id: str, event: dict):
        for q in self._queues.get(run_id, []):
            await q.put(event)

    def subscribe(self, run_id: str) -> asyncio.Queue:
        q = asyncio.Queue()
        self._queues.setdefault(run_id, []).append(q)
        return q

    def approve(self, run_id: str):
        self._approvals[run_id].set()

    async def wait_for_approval(self, run_id: str):
        await self._approvals[run_id].wait()

store = RunStore()
```

**SSE event contract** — every event the front end will ever see. Keep this stable; the UI keys off `event` (the type) and `state`.

| `event` | When | Payload fields |
|---|---|---|
| `state_change` | Orchestrator enters a new state | `state`, `attempt`, `message` |
| `kane_step` | Each Kane progress line (NDJSON, untyped step) | `step`, `status`, `remark` |
| `kane_result` | Kane `run_end` parsed | `passed`, `summary`, `screenshot_url`, `test_url`, `duration` |
| `patch` | Kiro produced a candidate fix | `branch`, `diff_summary`, `changed_files` |
| `awaiting_approval` | HUMAN_GATE reached | `summary`, `confirmation_runs` |
| `pr_opened` | PR created | `pr_url`, `proof_url` |
| `review_result` | kane_review finished a pass | `passed`, `flows_run`, `regressed`, `review_url` |
| `recorded` | Run persisted + chained | `recording_dir`, `prev_run_id`, `chain_length` |
| `escalated` | Retry/review budget exhausted / cannot reproduce | `reason`, `attempts` |
| `done` | Terminal — close the stream | `final_state` (RESOLVED/ESCALATE/STANDBY) |

Each SSE line is `event: <type>\ndata: <json>\n\n`. Use `sse-starlette`'s `EventSourceResponse`.

---

## 5. Kane client (`app/clients/kane.py`) — the verifier

Kane is invoked as a subprocess in `--agent --headless` mode. Stdout is NDJSON (one JSON object per line); the human-readable UI goes to stderr and is ignored. Automation keys off the **`run_end`** event and the **process exit code**.

```python
import asyncio, json, os
from app.models import KaneResult

EXIT_MAP = {0: ("passed", True), 1: ("failed", False),
            2: ("error", False), 3: ("timeout", False)}

async def run_flow(flow_file: str, base_url: str, variables: dict | None,
                   on_step, timeout: int = 120) -> KaneResult:
    """
    Replay a committed testmd flow against the (possibly patched) app.
    `on_step(step_event)` is an async callback used to stream kane_step events.
    """
    cmd = ["kane-cli", "testmd", "run", flow_file, "--agent", "--headless"]
    if variables:
        cmd += ["--variables", json.dumps(variables)]
    # Point the flow at the right environment
    env = {**os.environ, "STAGING_BASE_URL": base_url}

    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, env=env
    )

    run_end: dict | None = None
    try:
        async for raw in _readlines(proc.stdout, timeout):
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if obj.get("type") == "run_end":
                run_end = obj
            elif "step" in obj:                  # untyped progress event
                await on_step(obj)
        code = await asyncio.wait_for(proc.wait(), timeout=10)
    except asyncio.TimeoutError:
        proc.kill()
        code = 3

    status, passed = EXIT_MAP.get(code, ("error", False))
    re = run_end or {}
    screenshot = None
    if re.get("run_dir"):
        cand = os.path.join(re["run_dir"], "screenshot.png")
        screenshot = cand if os.path.exists(cand) else None

    return KaneResult(
        passed=passed, exit_code=code,
        summary=re.get("summary", status),
        one_liner=re.get("one_liner", ""),
        reason=re.get("reason", ""),
        duration=re.get("duration", 0.0),
        credits=re.get("credits"),
        final_state=re.get("final_state", {}),
        screenshot_path=screenshot,
        run_dir=re.get("run_dir"),
        test_url=re.get("test_url"),
    )

async def _readlines(stream, timeout):
    while True:
        line = await asyncio.wait_for(stream.readline(), timeout=timeout)
        if not line:
            return
        yield line.decode().strip()
```

**Why testmd replay, not a fresh `kane-cli run` each time:** the reproduction is captured once as a `*_test.md` flow (committed to `flows/`). Replays are deterministic and cost **zero LLM credits**, which is what makes the confirmation runs and the live demo reliable instead of flaky. Capture it once during prep:

```bash
kane-cli run "Go to $STAGING_BASE_URL/checkout, fill card 4111 1111 1111 1111, \
  click Pay, assert the order confirmation shows an order number" \
  --name checkout --agent
# writes .testmuai/tests/checkout_test.md  → move to backend/flows/checkout_test.md
```

Phrase verification as **assertions** so pass/fail is unambiguous, and use the **`store … as`** pattern for any value the front end should display (e.g. the HTTP error text), which lands in `final_state`.

---

## 6. Kiro client (`app/clients/kiro.py`) — the in-loop fixer

This is the documented risk. Resolve **in hour one**: can the Kiro agent + its hook be driven programmatically from the orchestrator? Build behind an interface either way.

```python
from abc import ABC, abstractmethod
from app.models import Incident, KaneResult, PatchResult

class KiroAgent(ABC):
    @abstractmethod
    async def patch(self, incident: Incident, last_failure: KaneResult | None,
                    attempt: int) -> PatchResult: ...


class KiroHeadlessClient(KiroAgent):
    """Best case: orchestrator invokes Kiro's agent directly, passing the
    Kane failure (NDJSON summary + screenshot path) as context, and waits
    for it to write a fix on a branch + fire its on-save hook."""
    async def patch(self, incident, last_failure, attempt):
        branch = f"shotgun/fix-{incident.service}-{attempt}"
        context = self._build_context(incident, last_failure)
        # Invoke Kiro headless (CLI / API), pointed at KIRO_WORKDIR,
        # with a steering file + the failure context. Kiro writes the branch
        # and its save-hook fires Kane (the literal loop-closing moment).
        await self._invoke_kiro(branch=branch, context=context)
        return PatchResult(branch=branch, diff_summary=await self._git_diffstat(branch),
                           changed_files=await self._changed_files(branch))

    def _build_context(self, incident, last_failure):
        parts = [f"Incident: {incident.symptom}",
                 f"Suspect area: {incident.recent_diff_hint or 'recent diff'}",
                 "You MUST make the committed Kane flow pass before declaring done."]
        if last_failure:
            parts.append(f"Previous Kane failure: {last_failure.summary}")
            if last_failure.screenshot_path:
                parts.append(f"Failure screenshot: {last_failure.screenshot_path}")
        return "\n".join(parts)


class KiroHookClient(KiroAgent):
    """Fallback: Kiro is open in the editor. The orchestrator writes a trigger
    file (KIRO_TRIGGER_FILE); a Kiro hook watches it, the agent patches on a
    branch and the on-save hook fires Kane. Orchestrator polls for the branch."""
    async def patch(self, incident, last_failure, attempt):
        branch = f"shotgun/fix-{incident.service}-{attempt}"
        await self._write_trigger(incident, last_failure, branch)
        await self._poll_for_branch(branch, timeout=90)
        return PatchResult(branch=branch, diff_summary=await self._git_diffstat(branch),
                           changed_files=await self._changed_files(branch))
```

**The steering file** (lives in the app-under-test repo) tells Kiro: the repo conventions, the suspect area (recent diff), and the hard requirement that the committed Kane flow must pass before "done." **The hook** runs the relevant Kane testmd flow on save — that is the moment the loop physically closes. The orchestrator's only job is to hand Kiro a *better* prompt each attempt by injecting the previous Kane failure, so revisions are informed, not random.

> Decision gate: if `KiroHeadlessClient` proves impossible before ~10 AM, set `KIRO_MODE=hook` and move on. Both are legitimate, fully-scored closed loops. Don't burn the day chasing headless.

---

## 7. The orchestrator (`app/orchestrator.py`) — core IP

A bounded, deterministic state machine. Every failure path leads somewhere safe — a human, never silence. Note the exact state table maps 1:1 to the original HLD.

| State | What happens | Exit |
|---|---|---|
| INTAKE | Normalize alert → `Incident` | → REPRODUCE |
| REPRODUCE | Kane runs the failing flow; **expect red** | red → PATCH · green/error → ESCALATE (can't reproduce) |
| PATCH | Kiro reads repo + failure, writes fix on a branch, save fires hook | → VERIFY |
| VERIFY | Kane re-runs the same flow on the patched app | green → CONFIRM · red → DECIDE |
| DECIDE | Feed Kane NDJSON + screenshot back to Kiro; decrement budget | budget>0 → PATCH · budget=0 → ESCALATE |
| CONFIRM | Replay the winning flow N× from cache (free, deterministic) | all green → HUMAN_GATE · any red → DECIDE |
| HUMAN_GATE | Surface "fixed & verified, ran N× green — open PR?"; wait for approval | approve → SHIP · reject → STANDBY |
| SHIP | Open GitHub PR with diff + Kane proof | → REVIEW |
| REVIEW | **Second loop.** `kane_review` replays the full flow suite (this run's repro + every *previous* recorded run's flow) against the new PR branch, then posts a GitHub PR review. | no regression → RECORD · regression → REVIEW_DECIDE |
| REVIEW_DECIDE | Feed the review's red NDJSON back to Kiro; decrement review budget. | budget>0 → PATCH (re-enter fix loop) · budget=0 → ESCALATE (PR left as "changes requested") |
| RECORD | Persist the whole run (every attempt, every Kane run, screenshots, the PR + review) and chain it to the previous run in the ledger. | → RESOLVED |
| ESCALATE | Loop couldn't converge; hand back everything gathered (still recorded) | → done |

```python
import asyncio
from app.models import RunState, State, Incident
from app.store import store
from app.clients import kane, github_pr
from app.clients.kiro import make_kiro_agent
from app.config import settings

async def run_incident(run: RunState):
    kiro = make_kiro_agent()           # picks headless/hook from KIRO_MODE
    inc = run.incident
    run.retry_budget = settings.RETRY_BUDGET

    async def emit(event, **data):
        await store.publish(run.run_id, {"event": event, "state": run.state, **data})

    async def on_step(step):           # stream Kane progress to the UI
        await emit("kane_step", step=step["step"], status=step["status"],
                   remark=step.get("remark", ""))

    async def kane_run() -> "KaneResult":
        res = await kane.run_flow(inc.repro_flow, settings.STAGING_BASE_URL,
                                  variables=None, on_step=on_step,
                                  timeout=settings.KANE_TIMEOUT_SECONDS)
        await emit("kane_result", passed=res.passed, summary=res.summary,
                   duration=res.duration, test_url=res.test_url,
                   screenshot_url=_public(res.screenshot_path))
        run.last_kane = res
        return res

    # REPRODUCE — confirm the bug is real and browser-observable
    run.state = State.REPRODUCE
    await emit("state_change", message="Reproducing the failure with Kane…")
    repro = await kane_run()
    if repro.passed or repro.exit_code == 2:
        return await _escalate(run, emit, "Could not reproduce a red failure.")

    # PATCH → VERIFY → DECIDE loop
    while True:
        run.attempt += 1
        run.state = State.PATCH
        await emit("state_change", attempt=run.attempt, message="Kiro is writing a fix…")
        patch = await kiro.patch(inc, run.last_kane, run.attempt)
        run.branch = patch.branch
        await emit("patch", branch=patch.branch, diff_summary=patch.diff_summary,
                   changed_files=patch.changed_files)

        run.state = State.VERIFY
        await emit("state_change", message="Kane re-verifying the patched app…")
        verify = await kane_run()

        if verify.passed:
            break
        run.state = State.DECIDE
        run.retry_budget -= 1
        if run.retry_budget <= 0:
            return await _escalate(run, emit, "Retry budget exhausted.")
        await emit("state_change", message=f"Still red — re-prompting Kiro "
                   f"({run.retry_budget} attempt(s) left).")

    # CONFIRM — N deterministic replays from cache (free)
    run.state = State.CONFIRM
    await emit("state_change", message=f"Confirming: {settings.CONFIRMATION_RUNS}× replay…")
    for _ in range(settings.CONFIRMATION_RUNS):
        c = await kane_run()
        if not c.passed:
            run.retry_budget -= 1
            if run.retry_budget <= 0:
                return await _escalate(run, emit, "Confirmation runs flaked.")
            run.state = State.DECIDE
            return await run_incident(run)   # re-enter loop with fresh budget hint

    # HUMAN_GATE — never merge autonomously
    run.state = State.HUMAN_GATE
    run.awaiting_approval = True
    await emit("awaiting_approval", summary=run.last_kane.summary,
               confirmation_runs=settings.CONFIRMATION_RUNS)
    await store.wait_for_approval(run.run_id)

    # SHIP
    run.state = State.SHIP
    await emit("state_change", message="Opening the pull request…")
    pr = await github_pr.open_pr(run.branch, run.incident, run.last_kane)
    run.pr_url = pr.url
    await emit("pr_opened", pr_url=pr.url, proof_url=run.last_kane.test_url)

    # REVIEW — the SECOND closed loop: kane_review vs. the previous run (§16)
    if settings.KANE_REVIEW_ENABLED:
        run.review_budget = settings.KANE_REVIEW_BUDGET
        while True:
            run.state = State.REVIEW
            await emit("state_change",
                       message="kane_review: replaying the regression suite vs. previous…")
            review = await kane_review.run(run, on_step=on_step)
            run.review = review
            await emit("review_result", passed=review.passed,
                       flows_run=review.flows_run, regressed=review.regressed_flows,
                       review_url=review.review_url)
            if review.passed:
                break
            # regression vs. a previous run -> request changes, re-enter the FIX loop
            run.state = State.REVIEW_DECIDE
            run.review_budget -= 1
            if run.review_budget <= 0 or not settings.KANE_REVIEW_BLOCK_ON_REGRESSION:
                return await _escalate(run, emit,
                    f"kane_review found regressions: {review.regressed_flows}")
            # feed the regression back to Kiro as a fresh failure and patch again
            run.last_kane = review.details[0] if review.details else run.last_kane
            await emit("state_change",
                       message=f"Regression caught — re-prompting Kiro "
                               f"({run.review_budget} review attempt(s) left).")
            patch = await kiro.patch(inc, run.last_kane, run.attempt + 1)
            run.attempt += 1
            run.branch = patch.branch
            await emit("patch", branch=patch.branch, diff_summary=patch.diff_summary,
                       changed_files=patch.changed_files)
            # push the new commit onto the SAME PR branch, then re-review
            await kane_run()

    # RECORD — persist everything + chain this run to the previous (§15)
    run.state = State.RECORD
    await emit("state_change", message="Recording the loop and chaining it…")
    rec = await recorder.finalize(run)            # writes recordings/<run_id>/, updates ledger
    run.recording_dir = rec.dir
    run.state = State.RESOLVED
    await emit("recorded", recording_dir=rec.dir, prev_run_id=run.prev_run_id,
               chain_length=rec.chain_length)
    await emit("done", final_state="RESOLVED")


async def _escalate(run, emit, reason):
    run.state = State.ESCALATE
    await emit("escalated", reason=reason, attempts=run.attempt)
    await recorder.finalize(run)                  # escalated runs are recorded too
    await emit("done", final_state="ESCALATE")
```

> Note the orchestrator now imports `kane_review` and `recorder` (§16, §15). On entry, `run.prev_run_id` is set from the recording ledger so every run is reviewed against the one before it — an automatic, continuously chained closed loop.

**Hard rule (from the original HLD, enforced in code):** the demo and the real tool are the **same codebase** fed a known input. No `if service == "checkout": return canned_fix`. The orchestrator really calls Kiro and really parses Kane's real output; only the *inputs* (staging app, seeded bug, repo state) are rehearsed.

---

## 8. GitHub PR with proof (`app/clients/github_pr.py`)

```python
import httpx
from app.config import settings
from app.models import Incident, KaneResult

class PR(BaseModel := __import__("pydantic").BaseModel):
    url: str

async def open_pr(branch: str, inc: Incident, kane: KaneResult) -> "PR":
    body = _pr_body(inc, kane)
    async with httpx.AsyncClient(
        base_url="https://api.github.com",
        headers={"Authorization": f"Bearer {settings.GITHUB_TOKEN}",
                 "Accept": "application/vnd.github+json"}) as c:
        r = await c.post(f"/repos/{settings.GITHUB_REPO}/pulls",
                         json={"title": f"Shotgun fix: {inc.symptom}",
                               "head": branch, "base": "main", "body": body})
        r.raise_for_status()
        return PR(url=r.json()["html_url"])

def _pr_body(inc, kane):
    return (
        f"## Shotgun verified fix\n\n"
        f"**Incident:** {inc.symptom}\n"
        f"**Service:** {inc.service}\n\n"
        f"### Proof (Kane)\n"
        f"- Status: ✅ {kane.summary}\n"
        f"- Duration: {kane.duration:.1f}s\n"
        f"- Replayable trace: {kane.test_url}\n"
        f"- Extracted state: `{kane.final_state}`\n\n"
        f"_Generated by Shotgun. Human approval required before merge._"
    )
```

The PR body embeds the **Kane proof**: pass record, the replayable KaneAI dashboard link, and the extracted `final_state`. The reviewer sees exactly what ran. That's the trust artifact.

---

## 9. API surface

| Method | Path | Purpose | Request | Response |
|---|---|---|---|---|
| POST | `/incidents` | Start a run. Normalizes payload → `Incident`, spawns orchestrator task. | PagerDuty/Sentry/JSON incident | `{run_id, state}` |
| GET | `/incidents/{run_id}/stream` | SSE live feed of the loop (see §4 contract). | — | `text/event-stream` |
| POST | `/incidents/{run_id}/approve` | Human gate: open the PR. | `{approve: true}` | `{ok: true}` |
| POST | `/incidents/{run_id}/reject` | Human gate: stand down. | — | `{ok: true}` |
| GET | `/incidents/{run_id}` | Snapshot of current `RunState` (debug / reconnect). | — | `RunState` |
| GET | `/healthz` | Liveness; checks `kane-cli whoami` + GitHub token. | — | `{kane, github, kiro}` |

**`POST /incidents` handler (sketch):**

```python
@router.post("/incidents")
async def create_incident(payload: dict, bg: BackgroundTasks):
    incident = normalize(payload)                  # maps PagerDuty/Sentry/JSON → Incident
    run = store.create(RunState(incident=incident))
    bg.add_task(run_incident, run)                 # orchestrator runs detached
    return {"run_id": run.run_id, "state": run.state}
```

**SSE endpoint:**

```python
@router.get("/incidents/{run_id}/stream")
async def stream(run_id: str):
    q = store.subscribe(run_id)
    async def gen():
        while True:
            ev = await q.get()
            yield {"event": ev["event"], "data": json.dumps(ev)}
            if ev["event"] == "done":
                break
    return EventSourceResponse(gen())
```

---

## 10. Minimal Next.js front end (Phase 3)

One page. Trigger an incident, watch the loop, approve the gate, see the PR. Keep it ruthlessly minimal — the *loop* is the star, not the UI framework.

**`lib/useIncidentStream.ts`:**

```typescript
import { useEffect, useState } from "react";

export type LoopEvent = { event: string; state: string; [k: string]: any };

export function useIncidentStream(runId: string | null) {
  const [events, setEvents] = useState<LoopEvent[]>([]);
  useEffect(() => {
    if (!runId) return;
    const es = new EventSource(`${process.env.NEXT_PUBLIC_API}/incidents/${runId}/stream`);
    const types = ["state_change","kane_step","kane_result","patch",
                   "awaiting_approval","pr_opened","escalated","done"];
    types.forEach(t => es.addEventListener(t, (e: MessageEvent) =>
      setEvents(prev => [...prev, JSON.parse(e.data)])));
    es.addEventListener("done", () => es.close());
    return () => es.close();
  }, [runId]);
  return events;
}
```

**`app/page.tsx` (shape):**

```tsx
"use client";
import { useState } from "react";
import { useIncidentStream } from "@/lib/useIncidentStream";

export default function Home() {
  const [runId, setRunId] = useState<string | null>(null);
  const events = useIncidentStream(runId);
  const last = events[events.length - 1];
  const awaiting = last?.event === "awaiting_approval";
  const pr = events.find(e => e.event === "pr_opened");

  async function trigger() {
    const r = await fetch(`${process.env.NEXT_PUBLIC_API}/incidents`, {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify(require("../examples/checkout-500.json")) });
    setRunId((await r.json()).run_id);
  }
  async function approve() {
    await fetch(`${process.env.NEXT_PUBLIC_API}/incidents/${runId}/approve`,
      {method:"POST", headers:{"Content-Type":"application/json"},
       body: JSON.stringify({approve:true})});
  }

  return (
    <main style={{display:"grid", gridTemplateColumns:"1fr 1fr", gap:24, padding:24}}>
      {/* LEFT: the loop timeline (state_change + patch events) */}
      <LoopTimeline events={events} />
      {/* RIGHT: Kane screen — current status, steps, screenshot */}
      <KaneScreen events={events} />
      {/* footer controls */}
      <div style={{gridColumn:"1 / -1"}}>
        {!runId && <button onClick={trigger}>🔔 Trigger incident</button>}
        {awaiting && <button onClick={approve}>✅ Open the PR</button>}
        {pr && <PrCard url={pr.pr_url} proof={pr.proof_url} />}
      </div>
    </main>
  );
}
```

The split screen *is* the money shot: left side shows REPRODUCE → PATCH → VERIFY ticking; right side shows Kane red, then the timeline cycles, then Kane green and a PR card slides in. ~40 seconds, no narration needed.

---

## 11. Three-phase build plan

Each phase is independently demoable and clears the bar above it. **Build ugly first; polish last.** Map to the original L-layers in brackets.

### Phase 1 — The Silent Loop (the engine) · clears all three "ready to ship" bars alone [L1]

**Goal:** `POST /incidents` (or a CLI trigger) drives a real, full loop in the terminal and prints `green — PR #` (or just `green` if PR-out isn't wired yet). No frontend.

| Build | Detail |
|---|---|
| FastAPI skeleton | `main.py`, `config.py`, `/healthz`. `healthz` shells `kane-cli whoami` so you fail fast on auth. |
| Models | All of §3. |
| Kane runner | §5. Verify against the live staging app; parse `run_end` + exit code. |
| testmd repro flow | Capture `flows/checkout_test.md` once; commit it. Confirm it goes **red** on the seeded bug and **green** after a manual fix — before wiring Kiro. |
| Kiro client | Pick `headless` or `hook` (decide by 10 AM). Get *one* real Kiro patch to flow through. |
| Orchestrator | §7 minus CONFIRM and HUMAN_GATE if pressed for time — but keep the retry budget and ESCALATE. |
| Trigger | A thin `scripts/incident.py` or `POST /incidents` you run from **Warp**: `python -m app.cli examples/checkout-500.json`. |

**Exit check:** from Warp, fire the seeded incident → watch Kane go red → Kiro patches → Kane goes green → prints success. **This is a complete, winning-eligible submission.** Stop here and you still qualify.

### Phase 2 — Real intake, PR-out, live stream [L2 + L3]

**Goal:** turn the script into a product the front end can consume, with a tangible artifact.

| Build | Detail |
|---|---|
| Webhook normalization | `normalize()` maps PagerDuty/Sentry/plain JSON → `Incident`. Accept arbitrary payloads. |
| Event bus + SSE | §4 + the `/stream` endpoint. Orchestrator publishes every transition. |
| Confirmation runs | CONFIRM state: N deterministic testmd replays from cache (free). Guards against flaky greens. |
| Human gate | HUMAN_GATE + `/approve` + `/reject`. Orchestrator blocks on `wait_for_approval`. |
| GitHub PR | §8. PR body embeds Kane proof (status, trace link, final_state). |
| Screenshot serving | Mount Kane's `run_dir` screenshots under a static route so the UI can show them. |

**Exit check:** `POST /incidents` with a raw payload → SSE stream emits the full sequence → human approves → a real PR opens with the Kane trace attached. Backend is now demo-complete even with a bare UI.

### Phase 3 — Minimal Next.js front end + perfect demo [L4-replacement + L5]

**Goal:** the web app *is* the demo. Replace voice entirely with a split-screen the room can read from across the room.

| Build | Detail |
|---|---|
| Next.js app | §10. Single page, `EventSource` hook, three components. |
| Split-screen | Left = loop timeline; right = Kane screen (status + steps + screenshot). |
| Trigger + approve | Big buttons. The seeded incident JSON ships in the repo. |
| PR card | Slides in on `pr_opened` with the proof link. |
| Polish | Smooth red→green transition; auto-scroll the step log; a status banner per state. |
| Demo runbook | §12. Rehearse the exact arc 3×. |

**Exit check:** click "Trigger incident" → the loop plays out on screen → red→green→PR card → you click "Open the PR." Zero terminal visible to the audience (run the backend in Warp behind the screen).

---

## 12. Demo runbook — engineered so nothing breaks

**Pre-flight (do this 30 min before, every time):**

```bash
# 1. Kane auth is live and has credits
kane-cli whoami && kane-cli balance

# 2. Staging app is up and the seeded bug is RED
kane-cli testmd run backend/flows/checkout_test.md --agent --headless   # expect exit 1

# 3. Repo is on the known clean state (the bug present, no stray branches)
cd $KIRO_WORKDIR && git checkout main && git reset --hard origin/main
git branch | grep shotgun/ | xargs -r git branch -D

# 4. Backend healthy
curl -s localhost:8000/healthz | jq          # kane:true github:true kiro:true

# 5. Frontend pointed at the backend
echo $NEXT_PUBLIC_API
```

**The 3-minute arc:**

1. **0:00 — Setup line.** "On-call gets paged mid-commute. The agent says it fixed it — but you can't check from the road. Shotgun makes 'I fixed it' provable." Big screen shows the empty console.
2. **0:20 — Trigger.** Click **Trigger incident** (or `npm run incident ./examples/checkout-500.json` in Warp). REPRODUCE lights up.
3. **0:35 — Kane red.** Right pane shows the checkout flow failing, screenshot of the dead Pay button. "Confirmed — it's really broken."
4. **0:50 — Kiro patches.** PATCH lights up; the branch + changed file appears. *Kiro is doing the thinking — Shotgun just orchestrates.*
5. **1:05 — The money shot.** VERIFY → Kane goes **green**. Confirmation replays tick 3× green. ~40s, let it breathe, no narration.
6. **1:50 — Human gate.** "Verified, ran it three times, all green. Open the PR?" Click **Open the PR**.
7. **2:10 — PR appears** with the Kane proof trace embedded. "A proven fix, waiting for one tap."
8. **2:30 — Honesty line.** "The incident is seeded; the loop is live — same codebase, real Kiro, real Kane output."

**Judge-runnable fallback (keep in the repo):**

```bash
npm run incident ./examples/checkout-500.json
# they watch red → green → PR in < 30s without your laptop
```

**Demo failure modes & instant recovery:**

| If… | Do this |
|---|---|
| Live Kiro patch is slow/erratic on stage | The CONFIRM/VERIFY replays are cached and free — they always behave. Worst case, narrate over a 10–15s Kiro pause; it reads as "the agent is thinking." |
| Kane network blips | testmd replay is deterministic; re-run is idempotent. Have a pre-recorded green `run_dir` to point the UI at as last resort (disclose it). |
| Staging app down | Run it locally and set `STAGING_BASE_URL=http://localhost:PORT`. Verify in pre-flight. |
| SSE drops | `GET /incidents/{id}` returns a full snapshot; the UI can rehydrate on reconnect. |

---

## 13. Risks & mitigations (backend-specific)

| Risk | Mitigation |
|---|---|
| Kiro can't be driven headlessly | `KiroAgent` interface + `KiroHookClient` fallback. Decide by 10 AM; both score full marks. |
| Live runs flaky / burn credits | Reproduction saved as testmd → all verification & confirmation runs replay from cache: deterministic, zero credits. |
| Orchestrator deadlocks on approval | HUMAN_GATE uses `asyncio.Event`; add a configurable auto-timeout → STANDBY so a hung gate never freezes the demo. |
| Bug isn't browser-observable | Scope to UI-visible regressions (Kane's wheelhouse). State it as a feature, not a gap. |
| Subprocess zombies / port clashes | Kane auto-launches Chrome on 9222–9230; pre-flight kills stray Chrome (`pkill -f remote-debugging-port`). Always `--headless` on the demo machine. |
| "Autonomous prod fix" spooks judges | The human gate is load-bearing and visible. Frame as "a verified draft waiting for one tap," never "merged for you." |
| Scope creep | Phase 1 is a complete submission. Phases 2–3 only raise the ceiling. If behind, ship the last green phase. |

---

## 14. Definition of done per phase

- **Phase 1 done:** one command from Warp drives a real red→patch→green loop against staging and reports success. Clears all three ship bars.
- **Phase 2 done:** arbitrary incident payload in → SSE stream out → human approve → real PR with Kane proof attached.
- **Phase 3 done:** the Next.js split-screen plays the loop start-to-finish on click, ending in a PR card; backend runs hidden in Warp; the 3-minute arc rehearsed clean 3×.

> *Build the silent loop first; let Kane make it trustworthy; let the web app make it unforgettable.*

---

## 15. Recording every loop (`app/recorder.py`)

Every run — successful or escalated — is written to disk as a self-contained bundle and linked into a chain ledger. This is what makes the second loop possible (you can only "review against the previous" if the previous is recorded) and it doubles as an audit trail and a growing regression suite.

**On-disk layout (one folder per run):**

```
recordings/
├── index.json                       # the chain ledger (see below)
└── <run_id>/
    ├── run.json                      # full RunState snapshot (final)
    ├── events.ndjson                 # every SSE event, in order (replayable timeline)
    ├── attempts/
    │   ├── 1/ kane_verify.json  screenshot.png
    │   ├── 2/ kane_verify.json  screenshot.png
    │   └── …
    ├── repro/ kane_repro.json  screenshot.png
    ├── review/ review.json            # kane_review outcome + per-flow results
    ├── flow.md                        # this run's testmd flow (carried forward)
    └── pr.json                        # pr_url, review_url, branch, diff summary
```

**The chain ledger (`index.json`)** — the spine of the "always review against the previous" requirement:

```json
{
  "head": "9f3a1c4b22d0",
  "runs": [
    {"run_id": "a1b2c3", "prev": null,       "pr": "…/pull/12", "flow": "recordings/a1b2c3/flow.md", "status": "RESOLVED", "ts": 1},
    {"run_id": "d4e5f6", "prev": "a1b2c3",    "pr": "…/pull/15", "flow": "recordings/d4e5f6/flow.md", "status": "RESOLVED", "ts": 2},
    {"run_id": "9f3a1c4b22d0", "prev": "d4e5f6", "pr": "…/pull/18", "flow": "…/flow.md", "status": "RESOLVED", "ts": 3}
  ]
}
```

**Recorder API:**

```python
import json, os, shutil, time
from app.config import settings
from app.models import RunState

class Recording:
    def __init__(self, dir: str, chain_length: int):
        self.dir, self.chain_length = dir, chain_length

def link_previous(run: RunState) -> str | None:
    """Called at INTAKE. Returns the prior run_id so this run reviews against it."""
    idx = _load_index()
    run.prev_run_id = idx.get("head")
    return run.prev_run_id

async def finalize(run: RunState) -> Recording:
    d = os.path.join(settings.RECORDINGS_DIR, run.run_id)
    os.makedirs(os.path.join(d, "attempts"), exist_ok=True)
    # 1. snapshot state + the live event timeline (drained from the run's queue mirror)
    _write(os.path.join(d, "run.json"), run.model_dump())
    # events.ndjson is appended live by the bus; nothing to do here if so
    # 2. carry this run's repro flow forward into the suite
    if settings.KANE_REVIEW_CARRY_FORWARD and os.path.exists(run.incident.repro_flow):
        shutil.copy(run.incident.repro_flow, os.path.join(d, "flow.md"))
    # 3. persist PR + review pointers
    _write(os.path.join(d, "pr.json"),
           {"pr_url": run.pr_url,
            "review_url": run.review.review_url if run.review else None,
            "branch": run.branch})
    # 4. update the chain ledger (this run becomes the new head)
    idx = _load_index()
    idx.setdefault("runs", []).append({
        "run_id": run.run_id, "prev": run.prev_run_id, "pr": run.pr_url,
        "flow": os.path.join(d, "flow.md"), "status": run.state.value,
        "ts": time.time()})
    idx["head"] = run.run_id
    _save_index(idx)
    _enforce_retention(idx)
    return Recording(d, chain_length=len(idx["runs"]))

def previous_flows(run: RunState) -> list[str]:
    """The regression suite for kane_review: every recorded run's flow,
    newest-previous first. With CARRY_FORWARD this set only ever grows."""
    idx = _load_index()
    return [r["flow"] for r in idx.get("runs", []) if os.path.exists(r["flow"])]

def _load_index():
    p = settings.RECORD_INDEX_FILE
    return json.load(open(p)) if os.path.exists(p) else {"head": None, "runs": []}

def _save_index(idx):
    os.makedirs(os.path.dirname(settings.RECORD_INDEX_FILE), exist_ok=True)
    json.dump(idx, open(settings.RECORD_INDEX_FILE, "w"), indent=2)
```

Wire `link_previous(run)` into the INTAKE step so `run.prev_run_id` is set before anything else. Mirror every published SSE event into `recordings/<run_id>/events.ndjson` from the event bus (one extra `append` in `store.publish`), so the timeline is captured for free and the front end can *replay any past run* by streaming the file back.

---

## 16. The second closed loop — `kane_review` (`app/clients/kane_review.py`)

This is the "automatic complex closed loop" you asked for. After a fix ships, `kane_review` does **not** just re-check the one flow — it replays the **entire accumulated suite** (this run's repro flow plus every previous recorded run's flow) against the new PR branch. If any *previous* scenario now fails, that's a regression the naive single-flow loop would miss; the review posts "changes requested" on the PR and kicks the run back into the fix loop. Pass → it posts an approving review and the run records and chains.

**Why this scores well:** it's a loop *on top of* a loop (fix loop ⟲ review loop), it makes Kane load-bearing twice, and the chain ledger means each PR is provably reviewed against its predecessor — a continuously self-reinforcing closed system, not a one-shot check.

```
   SHIP (PR open)
        │
        ▼
   ┌──────────── REVIEW (kane_review) ────────────┐
   │  replay suite = [this.flow, prev.flow, …]     │
   │  against the NEW pr branch                    │
   └───────────────────────────────────────────────┘
        │ all green                 │ any previous flow red
        ▼                           ▼
   post APPROVE review        post CHANGES-REQUESTED review
        │                           │  feed regression → Kiro
        ▼                           ▼  re-patch same branch
   RECORD + chain          ──► back into REVIEW (budget--)
```

```python
import os
from app.config import settings
from app.models import RunState, ReviewResult, KaneResult
from app.clients import kane, github_pr
from app import recorder

async def run(run: RunState, on_step) -> ReviewResult:
    # Build the regression suite. In chained mode, always include the PREVIOUS
    # run's flow(s); in standalone mode, just this run's flow.
    if settings.KANE_REVIEW_MODE == "chained":
        suite = recorder.previous_flows(run)            # whole chain, incl. previous
        if run.incident.repro_flow not in suite:
            suite.append(run.incident.repro_flow)
    else:
        suite = [run.incident.repro_flow]

    # Verify the patched branch against the staging deploy of that branch.
    results: list[KaneResult] = []
    regressed: list[str] = []
    for flow in suite:
        res = await kane.run_flow(flow, settings.STAGING_BASE_URL,
                                  variables=None, on_step=on_step,
                                  timeout=settings.KANE_TIMEOUT_SECONDS)
        results.append(res)
        if not res.passed:
            regressed.append(flow)

    passed = not regressed
    body = _review_body(run, suite, regressed, results)
    event = "APPROVE" if passed else "REQUEST_CHANGES"
    review_url = None
    if settings.KANE_REVIEW_POST_AS == "review":
        review_url = await github_pr.post_review(run.pr_url, event, body)
    else:
        review_url = await github_pr.post_comment(run.pr_url, body)

    return ReviewResult(passed=passed, flows_run=suite, regressed_flows=regressed,
                        review_url=review_url, details=[r for r in results if not r.passed] or results[:1])

def _review_body(run, suite, regressed, results):
    head = "✅ kane_review passed" if not regressed else "❌ kane_review found regressions"
    lines = [f"## {head}",
             f"Reviewed PR **{run.pr_url}** against the chained suite "
             f"(prev run: `{run.prev_run_id or 'none'}`).",
             f"- Flows replayed: {len(suite)}",
             f"- Regressed: {regressed or 'none'}", ""]
    for r in results:
        mark = "✅" if r.passed else "❌"
        lines.append(f"{mark} `{r.summary}`  ({r.duration:.1f}s)  {r.test_url or ''}")
    lines.append("\n_Each PR is reviewed against the previous one. Chain is unbroken._")
    return "\n".join(lines)
```

**Two new helpers in `github_pr.py`:**

```python
async def post_review(pr_url: str, event: str, body: str) -> str:
    number = pr_url.rstrip("/").split("/")[-1]
    async with _client() as c:
        r = await c.post(f"/repos/{settings.GITHUB_REPO}/pulls/{number}/reviews",
                         json={"event": event, "body": body})   # APPROVE | REQUEST_CHANGES
        r.raise_for_status()
        return r.json()["html_url"]

async def post_comment(pr_url: str, body: str) -> str:
    number = pr_url.rstrip("/").split("/")[-1]
    async with _client() as c:
        r = await c.post(f"/repos/{settings.GITHUB_REPO}/issues/{number}/comments",
                         json={"body": body})
        r.raise_for_status()
        return r.json()["html_url"]
```

**Behavior knobs (all in `.env`):**

- `KANE_REVIEW_MODE=chained` — always reference the previous run; `standalone` reviews only the current fix.
- `KANE_REVIEW_BUDGET=2` — how many review→re-patch cycles before ESCALATE.
- `KANE_REVIEW_BLOCK_ON_REGRESSION=true` — a red review re-enters the fix loop; `false` records anyway and just leaves "changes requested" on the PR.
- `KANE_REVIEW_CARRY_FORWARD=true` — each run's repro flow is added to the suite for the next run, so coverage compounds over the chain.

**Phase placement & demo note:** `kane_review` + recording belong in **Phase 2** (right after PR-out — it's the same Kane runner pointed at a suite, plus a ledger file). For the demo, after the green PR card you can show a second beat: *"and it just reviewed itself against the last fix — here's the approving review, with the previous scenario still green."* That second loop is exactly the kind of "weirder, tighter integration" the judges said they're hoping to see. Keep it behind `KANE_REVIEW_ENABLED` so you can toggle it off if you're tight on the 3-minute clock.

---

# Part C — Dispatch (CEO spec) integration & Render deployment

> The CEO handed down **Dispatch-HLD-LLD**. Dispatch and Shotgun are the **same product**; Dispatch is the enterprise framing. This part reconciles the two, adds the pieces Dispatch needs that Shotgun didn't have (Kafka, Postgres, voice), and answers the operational question: **what runs on Render, what stays local, and how to keep it fast.**

## 17. Same product — component reconciliation

Roughly 70% of Dispatch is already specified above. The deltas are Kafka intake, a Postgres datastore, the AgentPhone voice layer, and the diagnosis/remediation "before vs. after" framing.

| Dispatch component | This doc's module | Status |
|---|---|---|
| Incident Consumer (Kafka) | `intake/kafka_consumer.py` + `normalize.py` | **New** — §19 |
| Orchestrator (state machine) | `orchestrator.py` (§7) | Exists; states aligned in §22 |
| Kiro Bridge (file-watch seam) | `KiroHookClient` (§6) | **This IS the Bridge** — implement the two-file protocol in §18 |
| Kiro + Kane loop | `kiro.py` + `kane.py` (§5–§6) | Exists — both already in the loop |
| AgentPhone service | `clients/agentphone.py` | **New** — §21 |
| PR Service | `github_pr.py` (§8) | Exists |
| Artifact store (before/after) | `recorder.py` (§15) | Exists; re-shaped to `artifacts/<id>/before|after` in §20 |
| Web app + SSE | Next.js (§10) + `/stream` (§4) | Exists; add before/after + diff views |
| Datastore (Postgres) | `db.py` | **New** — §20 |

**State-name alignment** (so the team reads the same machine): Dispatch `RECEIVED→DIAGNOSING→DIAGNOSED→CALLING→AWAITING_DECISION→FIXING→VERIFYING→PR_OPENING→RESOLVED` maps to this doc's `INTAKE→REPRODUCE→(CALLING→AWAITING_DECISION)→PATCH→VERIFY→…→SHIP→REVIEW→RECORD→RESOLVED`. The `State` enum (§3) now carries both vocabularies. The two human-decision paths are interchangeable: **CALLING/AWAITING_DECISION** is the voice gate (Dispatch), **HUMAN_GATE** is the web-app gate (Shotgun) — same transition, pick one per demo.

## 18. Deployment topology — the one constraint that decides everything

**Kiro cannot run on Render.** It is an interactive desktop IDE, and the Kiro Bridge is a **shared-filesystem seam** (orchestrator writes `.dispatch/incidents/<id>.json`, Kiro's local hook reads it; Kiro writes `.dispatch/results/<id>.json`, orchestrator reads it). That only works when the orchestrator and Kiro are on the **same machine**. Therefore the orchestrator + Kiro Bridge + Kane CLI (it needs a real Chrome) all live **locally**, and Render hosts the **stateless / public / stateful-data** pieces.

**Decision taken (flip via `.env`):** `LOOP_LOCATION=local`, `STATUS_BUS=postgres`.

```
        ┌──────────────────────── RENDER (always-on) ─────────────────────────┐
        │                                                                      │
        │   App Under Test  ◄───── Kane drives local Chrome against this ──────┼──┐
        │   (seeded buggy staging app, stable public URL)                      │  │
        │                                                                      │  │
        │   Postgres (managed)  ◄── status/artifacts written by local loop ────┼──┤
        │        ▲                                                             │  │
        │        │ reads incidents + status                                    │  │
        │   Public Dashboard (Next.js)  ── SSE/poll ──► judges' browser        │  │
        │        ▲                                                             │  │
        │   Kafka (Upstash/Redpanda, managed)  ── frontend.incidents ──┐       │  │
        └──────────────────────────────────────────────────────────────┼──────┘  │
                                                                         │         │
        ┌──────────────────────── LOCAL LAPTOP ─────────────────────────┼─────────┼┐
        │                                                                ▼         ││
        │   FastAPI Orchestrator ── consumes Kafka ── runs state machine          ││
        │        │            ▲                                                   ││
        │   Kiro Bridge (.dispatch/ files)   ──► Kiro IDE (open) ── writes branch ││
        │        │                                                                ││
        │   Kane CLI ── local headless Chrome ──────────────────────────────────┘│
        │        └── verifies the Render-hosted App Under Test, replays testmd     │
        └──────────────────────────────────────────────────────────────────────────┘
```

Why this is correct *and* fast: the latency-sensitive loop (Kiro file-watch, Kane subprocess) has **zero network hops** — it's all on the laptop. Render holds the public URL the judges hit and the stable staging app Kane targets. The local loop writes status rows to Render Postgres; the dashboard polls them. No tunnel required.

**`STATUS_BUS` options:** `postgres` (local loop writes rows, dashboard polls every `STATUS_POLL_MS`; robust, no tunnel) or `tunnel` (expose the local orchestrator's SSE via cloudflared/ngrok so the dashboard streams live; lower latency, depends on tunnel stability). Default `postgres`.

### 18.1 Render services & "very fast" checklist

| Render service | Type | Notes |
|---|---|---|
| `dispatch-app-under-test` | Web Service (Docker/native) | The seeded buggy app. **Always-on.** This is the single best use of Render — Kane needs a stable, fast public URL. |
| `dispatch-db` | Render Postgres | incidents / runs / artifacts (§20). |
| `dispatch-dashboard` | Web Service (Next.js) or Static | Public URL for judges; reads Postgres / streams status. |
| *(optional)* `dispatch-intake` | Web Service | Only if you want a cloud webhook that enqueues to Postgres/Kafka; otherwise intake is the local consumer. |

**Speed rules (non-negotiable for a perfect demo):**

- **Never use Render's free tier on the demo path.** Free instances spin down and cold-start ~50s — it will destroy your 3 minutes. Use the always-on Starter tier; spin them up the morning of.
- Pick the Render **region closest to the venue**.
- Keep **Kane and Kiro local** — do not route the loop through a cloud browser grid; the local Chrome hitting the Render staging URL is faster and simpler.
- Lean on **Kane `testmd` cached replays** for every verify/confirm/review run — deterministic, zero model credits, fast. This is your speed *and* your reliability.
- Pre-warm: a `/healthz` pinger every 4 min keeps Render services hot if you're forced onto a tier that idles.

## 19. Kafka intake (`app/intake/`)

Dispatch's front door is a Kafka topic `frontend.incidents`, consumer group `dispatch-orchestrator`, **idempotent on `incident_id`** so a redelivery never starts a second loop. Hide the broker behind an interface so the same orchestrator serves Kafka, a Postgres queue, or a plain webhook.

**Decision taken (flip via `.env`):** `INTAKE_MODE=kafka` using **Upstash Kafka or Redpanda** (both Kafka-API compatible, managed, fast). Fallback `INTAKE_MODE=postgres_queue` keeps the *exact same message contract* but enqueues rows to Postgres — stand up zero brokers, swap later without touching the orchestrator.

```python
# intake/kafka_consumer.py
import json, asyncio
from aiokafka import AIOKafkaConsumer
from app.config import settings
from app.intake.normalize import to_incident
from app.models import RunState
from app.store import store
from app.orchestrator import run_incident
from app import recorder, db

async def consume():
    c = AIOKafkaConsumer(
        settings.KAFKA_TOPIC, bootstrap_servers=settings.KAFKA_BROKERS,
        group_id=settings.KAFKA_GROUP_ID, enable_auto_commit=False,
        security_protocol="SASL_SSL", sasl_mechanism=settings.KAFKA_SASL_MECHANISM,
        sasl_plain_username=settings.KAFKA_USERNAME,
        sasl_plain_password=settings.KAFKA_PASSWORD,
        value_deserializer=lambda b: json.loads(b))
    await c.start()
    try:
        async for msg in c:
            payload = msg.value
            iid = payload["incident_id"]
            if await db.incident_exists(iid):          # idempotency guard
                await c.commit(); continue
            incident = to_incident(payload)
            await db.insert_incident(iid, incident)
            run = store.create(RunState(incident=incident))
            run.run_id = iid                            # use the Kafka id as the run id
            recorder.link_previous(run)                 # chain to the previous recorded run
            asyncio.create_task(run_incident(run))
            await c.commit()                            # commit only after we own the work
    finally:
        await c.stop()
```

The Kafka message (CEO contract — keep verbatim): `incident_id, service, symptom, url, repo, commit_sha, severity, repro_hint, detected_at`. `normalize.to_incident()` maps `url→suspect_url`, `repro_hint→repro_flow` lookup, `commit_sha→recent_diff_hint`. Start the consumer from FastAPI's lifespan so it runs alongside the API.

## 20. Postgres datastore (`app/db.py`)

Replaces the in-memory store for anything that must survive a restart or be read by the Render dashboard. Use the CEO's schema verbatim so the handoff is clean.

```sql
CREATE TABLE incidents (
  id text PRIMARY KEY,                 -- inc_01HX… (also the run_id)
  service text, symptom text, url text, repo text, commit_sha text,
  severity text, status text,          -- state-machine value
  diagnosis text, decision text,       -- fix | dismiss | null
  pr_url text, created_at timestamptz DEFAULT now(), updated_at timestamptz);

CREATE TABLE runs (                     -- one row per Kane run
  id text PRIMARY KEY, incident_id text REFERENCES incidents(id),
  phase text,                          -- repro | verify | review
  status text, attempt int,
  run_dir text, replay_url text, screenshot text,
  created_at timestamptz DEFAULT now());

CREATE TABLE artifacts (
  incident_id text REFERENCES incidents(id),
  kind text,                           -- before_shot|after_shot|before_replay|after_replay|diff
  uri text);
```

`db.py` exposes async helpers (`insert_incident`, `incident_exists`, `update_status`, `insert_run`, `add_artifact`, `get_incident`, `list_incidents`) over an `asyncpg`/SQLAlchemy-async pool sized by `DB_POOL_SIZE`. **Write-through pattern:** the orchestrator's `emit()` (§7) gains one extra line — mirror each significant transition into `update_status()` and each Kane result into `insert_run()` — so Render Postgres always reflects live state for the dashboard. Artifacts written by `recorder.finalize()` (§15) are registered here as `before_*` / `after_*` rows.

**Before vs. after (Dispatch framing):** the failing repro run in REPRODUCE is the **before** (`before_shot` + `before_replay`); the first green run in VERIFY is the **after** (`after_shot` + `after_replay`). The web detail view shows them side by side with the diff.

## 21. AgentPhone voice layer (`app/clients/agentphone.py`)

Two short calls: one delivers the diagnosis and captures a fix/dismiss decision, one confirms the PR. **Build last, behind `AGENTPHONE_ENABLED=false`, with a tap-to-talk web fallback** so a bad transcript never blocks the demo.

```python
import httpx, asyncio
from app.config import settings
from app.store import store

async def place_decision_call(incident_id: str, say: str):
    async with httpx.AsyncClient() as c:
        await c.post(f"{settings.AGENTPHONE_API_URL}/call",
            headers={"Authorization": f"Bearer {settings.AGENTPHONE_API_KEY}"},
            json={"to": settings.ONCALL_PHONE, "from": settings.AGENTPHONE_FROM,
                  "incident_id": incident_id, "say": say, "expect": "decision"})

async def wait_for_decision(incident_id: str, timeout: int) -> str:
    """Resolved by the decision webhook; times out -> ESCALATE."""
    try:
        return await asyncio.wait_for(store.wait_for_decision(incident_id), timeout)
    except asyncio.TimeoutError:
        return "no_answer"
```

```python
# routes/incidents.py — the spoken decision comes back here
@router.post("/webhooks/agentphone/decision")
async def decision(body: dict):
    store.set_decision(body["incident_id"], body["decision"])  # "fix" | "dismiss"
    return {"ok": True}
```

Orchestrator wiring: after REPRODUCE (diagnosis), if `AGENTPHONE_ENABLED`, go `CALLING → AWAITING_DECISION`; `fix → PATCH`, `dismiss → DISMISSED`, `no_answer → ESCALATE`. The diagnosis spoken aloud uses Kane's `final_state` (the real extracted error text), not canned filler. If voice is off, the web `HUMAN_GATE` plays the same role.

## 22. Merged build order (Dispatch + Shotgun)

Both source docs agree: **build the Kiro Bridge and the silent loop first; everything hangs off a working loop.** Each layer is independently demoable and winning-eligible at the line marked ✅.

| Step | Build | Validates | Stop-here value |
|---|---|---|---|
| 1 | **Kiro Bridge** — orchestrator writes `.dispatch/incidents/<id>.json`, Kiro hook fires, orchestrator reads `results/<id>.json` | The single highest-risk seam (§6, §18) | — |
| 2 | **Silent loop** — incident JSON → diagnose (Kane red) → Kiro patch → Kane green → PR opened, terminal-only, run from Warp | The whole closed loop | ✅ clears all three ship bars |
| 3 | **Render: app-under-test + Postgres** — deploy the seeded staging app (stable URL Kane hits) and the DB; orchestrator write-through | Fast, stable target + persistence | ✅ real infra |
| 4 | **PR proof + before/after artifacts + recording + `kane_review`** (§8, §15, §16, §20) | Output is tangible; the second loop | ✅ demo artifact + tight integration |
| 5 | **Render: dashboard** — Next.js reads Postgres / SSE; before/after + diff + live mode | The money shot on a public URL | ✅ visible autonomy |
| 6 | **Kafka in front** — replace manual trigger with the `frontend.incidents` consumer (§19) | Turns a script into a product | ✅ enterprise-shaped |
| 7 | **AgentPhone** — voice call + spoken decision, tap fallback (§21) | The beat that makes the room lean in | optional; not graded core |

**Hard rule still applies:** demo and real tool are the **same codebase** fed a seeded input — no demo fork. Only the inputs (Render staging app, seeded bug, repo state) are rehearsed.

> *Build the Kiro Bridge and the silent loop first. Put the app-under-test and Postgres on always-on Render. Keep Kiro and Kane local so the loop is instant. Add Kafka, then voice, only once the loop is green.*
