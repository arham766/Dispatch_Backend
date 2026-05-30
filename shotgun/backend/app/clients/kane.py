"""
Shotgun — Kane CLI runner + NDJSON parser.

Kane is invoked as a subprocess in --agent --headless mode. Stdout is
NDJSON (one JSON object per line); the human-readable UI goes to stderr
and is ignored. Automation keys off the `run_end` event (stable schema)
and the process exit code.

Exit code mapping:
    0 → passed (True)
    1 → failed (False)
    2 → error  (False)
    3 → timeout (False)

Why testmd replay, not a fresh kane-cli run each time:
    The reproduction is captured once as a *_test.md flow (committed to flows/).
    Replays are deterministic and cost zero LLM credits, which is what makes
    the confirmation runs and the live demo reliable instead of flaky.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, AsyncIterator, Callable, Coroutine

from app.models import KaneResult

logger = logging.getLogger(__name__)

# Exit code → (human label, passed bool)
EXIT_MAP: dict[int, tuple[str, bool]] = {
    0: ("passed", True),
    1: ("failed", False),
    2: ("error", False),
    3: ("timeout", False),
}

# Kane NDJSON event "type" values that carry per-step progress.
# The UI's KaneScreen step log forwards each one as a `kane_step` SSE/WS
# event so the user sees Kane's progress in real time.
_KANE_STEP_TYPES = {
    "step_start",       # Kane began a new testmd step
    "step_end",         # Step finished (status: passed|failed|skipped)
    "step_event",       # Inner action: screenshot, evaluation, type, click…
}


def _is_step_event(obj: dict) -> bool:
    """True if this NDJSON line is a per-step progress event worth showing."""
    t = obj.get("type")
    if t in _KANE_STEP_TYPES:
        return True
    # Backwards-compat: older Kane versions used a "step" key directly.
    return "step" in obj


def _normalize_step(obj: dict) -> dict:
    """Map Kane's heterogeneous step events to the {step, status, remark}
    shape the UI expects.

    For step_start: status="running"
    For step_end:   status="passed"|"failed"|... (real verdict)
    For step_event: status=the inner event name ("action","screenshot",…)
    """
    t = obj.get("type", "step")
    idx = obj.get("index") or obj.get("step")
    step_label = f"Step {idx}" if idx is not None else (obj.get("step") or "step")

    if t == "step_start":
        status = "running"
    elif t == "step_end":
        status = obj.get("status") or "done"
    elif t == "step_event":
        status = obj.get("event") or "event"
    else:
        status = obj.get("status", "?")

    remark = (
        obj.get("summary")
        or obj.get("detail")
        or obj.get("objective")
        or obj.get("remark")
        or ""
    )
    return {
        "step": step_label,
        "status": status,
        "remark": str(remark)[:240],
        "type": t,
        "index": idx,
    }


async def run_flow(
    flow_file: str,
    base_url: str,
    variables: dict[str, Any] | None = None,
    on_step: Callable[[dict], Coroutine] | None = None,
    timeout: int = 120,
) -> KaneResult:
    """Replay a committed testmd flow against the (possibly patched) app.

    Args:
        flow_file:  Path to the .md flow file (e.g. ``flows/checkout_test.md``).
        base_url:   The staging URL Kane should target.
        variables:  Optional dict of variables to pass to Kane.
        on_step:    Async callback for each progress event (streamed to SSE).
        timeout:    Max seconds for the entire Kane run.

    Returns:
        A ``KaneResult`` parsed from the run_end event + exit code.
    """
    # Instead of relying on --variables parsing which is buggy on Windows,
    # let's rewrite the markdown file to a temp file and run that.
    if variables:
        with open(flow_file, "r", encoding="utf-8") as f:
            content = f.read()
        for k, v in variables.items():
            content = content.replace(f"${k}", v)
            content = content.replace(f"{{{{{k}}}}}", v)
            
        temp_file = flow_file.replace(".md", "_temp.md")
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(content)
        flow_file = temp_file

    cmd = ["kane-cli", "testmd", "run", flow_file, "--agent", "--headless"]

    # Point the flow at the right environment
    env = {**os.environ, "STAGING_BASE_URL": base_url}

    logger.info("Kane: ==============================================")
    logger.info("Kane: CMD   = %s", " ".join(cmd))
    logger.info("Kane: FLOW  = %s", flow_file)
    logger.info("Kane: URL   = %s", base_url)
    logger.info("Kane: TIMEOUT = %ds", timeout)
    logger.info("Kane: ==============================================")
    try:
        # On Windows, kane-cli is a .cmd batch file — must use shell=True
        if os.name == "nt":
            cmd_str = " ".join(cmd)
            logger.info("Kane: [spawn] shell=%s", cmd_str)
            proc = await asyncio.create_subprocess_shell(
                cmd_str,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
    except (FileNotFoundError, OSError) as exc:
        logger.error("Kane: failed to spawn kane-cli — %s", exc)
        return KaneResult(
            passed=False, exit_code=2,
            summary=f"kane-cli spawn error: {exc}",
            reason="Install with: npm i -g @testmuai/kane-cli",
        )

    run_end: dict | None = None
    line_count = 0

    # Start a task to log stderr in parallel
    async def _drain_stderr():
        if proc.stderr:
            async for raw in _readlines(proc.stderr, timeout):
                logger.info("Kane: [stderr] %s", raw[:200])
    import asyncio as _aio
    stderr_task = _aio.create_task(_drain_stderr())

    try:
        async for raw in _readlines(proc.stdout, timeout):
            line_count += 1
            logger.info("Kane: [stdout:%d] %s", line_count, raw[:300])
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Kane: [non-json] %s", raw[:200])
                continue

            event_type = obj.get("type", obj.get("event", "unknown"))
            logger.info(
                "Kane: [event] type=%s idx=%s status=%s detail=%s",
                event_type,
                obj.get("index", obj.get("step", "-")),
                obj.get("status", "-"),
                str(obj.get("detail") or obj.get("summary") or obj.get("remark") or "-")[:80],
            )

            if obj.get("type") == "run_end":
                run_end = obj
                logger.info("Kane: [run_end] summary=%s", obj.get("summary", "?")[:200])
            elif on_step and _is_step_event(obj):
                await on_step(_normalize_step(obj))

        code = await asyncio.wait_for(proc.wait(), timeout=10)
        logger.info("Kane: [exit] code=%d lines=%d", code, line_count)
    except asyncio.TimeoutError:
        logger.warning("Kane: TIMED OUT after %ds (read %d lines), killing process", timeout, line_count)
        proc.kill()
        code = 3
    finally:
        stderr_task.cancel()

    status, passed = EXIT_MAP.get(code, ("error", False))
    re = run_end or {}

    # Detect screenshot
    screenshot: str | None = None
    if re.get("run_dir"):
        cand = os.path.join(re["run_dir"], "screenshot.png")
        screenshot = cand if os.path.exists(cand) else None

    result = KaneResult(
        passed=passed,
        exit_code=code,
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
    logger.info("Kane: ============ RESULT ============")
    logger.info("Kane:   passed     = %s", result.passed)
    logger.info("Kane:   exit_code  = %d", code)
    logger.info("Kane:   summary    = %s", result.summary[:200])
    logger.info("Kane:   one_liner  = %s", result.one_liner[:200] if result.one_liner else "-")
    logger.info("Kane:   reason     = %s", result.reason[:200] if result.reason else "-")
    logger.info("Kane:   duration   = %.1fs", result.duration)
    logger.info("Kane:   test_url   = %s", result.test_url or "-")
    logger.info("Kane:   screenshot = %s", result.screenshot_path or "-")
    logger.info("Kane:   run_dir    = %s", result.run_dir or "-")
    logger.info("Kane: =================================")
    return result


async def check_auth() -> bool:
    """Quick health check: shells ``kane-cli whoami`` and returns True if it succeeds."""
    try:
        if os.name == "nt":
            proc = await asyncio.create_subprocess_shell(
                "kane-cli whoami",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                "kane-cli", "whoami",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        code = await asyncio.wait_for(proc.wait(), timeout=15)
        return code == 0
    except (FileNotFoundError, asyncio.TimeoutError, OSError):
        return False


async def _readlines(
    stream: asyncio.StreamReader | None,
    timeout: int,
) -> AsyncIterator[str]:
    """Async generator that yields stripped lines from a stream with a per-line timeout."""
    if stream is None:
        return
    while True:
        try:
            line = await asyncio.wait_for(stream.readline(), timeout=timeout)
        except asyncio.TimeoutError:
            raise
        if not line:
            return
        yield line.decode().strip()
