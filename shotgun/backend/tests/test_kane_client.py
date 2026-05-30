"""
Integration tests for the Kane CLI client (app/clients/kane.py).

Instead of mocking asyncio, we replace the `kane-cli` binary with a real
Python script that emits caller-supplied NDJSON on stdout and exits with a
chosen code. This exercises the genuine subprocess spawn + line-by-line
parser + the run_end / exit-code mapping path.

To dodge all shell-quoting pitfalls, the fake reads its raw output lines
from a file and its exit code from an env var — nothing is interpolated
into source.
"""

from __future__ import annotations

import os
import sys

import pytest

from app.clients import kane


pytestmark = pytest.mark.integration

# A tiny fake CLI: print each line of $KANE_LINES verbatim, exit $KANE_EXIT.
_FAKE_SRC = (
    "import os, sys\n"
    "p = os.environ.get('KANE_LINES')\n"
    "if p:\n"
    "    with open(p, encoding='utf-8') as f:\n"
    "        sys.stdout.write(f.read())\n"
    "        sys.stdout.flush()\n"
    "sys.exit(int(os.environ.get('KANE_EXIT', '0')))\n"
)


async def _run(monkeypatch, tmp_path, lines: list[str], exit_code: int):
    """Spawn the real client against a fake kane-cli emitting `lines`."""
    impl = tmp_path / "fake_kane.py"
    impl.write_text(_FAKE_SRC, encoding="utf-8")

    lines_file = tmp_path / "lines.ndjson"
    lines_file.write_text("".join(l + "\n" for l in lines), encoding="utf-8")

    monkeypatch.setenv("KANE_LINES", str(lines_file))
    monkeypatch.setenv("KANE_EXIT", str(exit_code))

    import app.clients.kane as kane_mod
    orig = kane_mod.asyncio.create_subprocess_exec

    async def patched(*cmd, **kw):
        # Replace the "kane-cli" argv[0] with: python fake_kane.py …
        new_cmd = (sys.executable, str(impl)) + tuple(cmd[1:])
        return await orig(*new_cmd, **kw)

    monkeypatch.setattr(kane_mod.asyncio, "create_subprocess_exec", patched)

    steps: list[dict] = []

    async def on_step(s):
        steps.append(s)

    res = await kane.run_flow("flows/x.md", "http://localhost", on_step=on_step, timeout=10)
    return res, steps


async def test_parses_run_end_and_passes(monkeypatch, tmp_path):
    lines = [
        '{"step": "open", "status": "ok"}',
        '{"type": "run_end", "summary": "order #1", "duration": 2.5,'
        ' "test_url": "https://k/r/1", "final_state": {"order": "1"}}',
    ]
    res, steps = await _run(monkeypatch, tmp_path, lines, exit_code=0)

    assert res.passed is True
    assert res.exit_code == 0
    assert res.summary == "order #1"
    assert res.duration == 2.5
    assert res.test_url == "https://k/r/1"
    assert res.final_state == {"order": "1"}
    assert len(steps) == 1


async def test_failed_exit_code_maps_to_not_passed(monkeypatch, tmp_path):
    lines = ['{"type": "run_end", "summary": "pay dead"}']
    res, _ = await _run(monkeypatch, tmp_path, lines, exit_code=1)
    assert res.passed is False
    assert res.exit_code == 1
    assert res.summary == "pay dead"


async def test_garbage_lines_are_ignored(monkeypatch, tmp_path):
    lines = [
        "not json at all",
        '{"step": "s1", "status": "run"}',
        "<<< human readable >>>",
        '{"type": "run_end", "summary": "ok"}',
    ]
    res, steps = await _run(monkeypatch, tmp_path, lines, exit_code=0)
    assert res.passed is True
    assert res.summary == "ok"
    assert len(steps) == 1  # only the valid step object


async def test_error_exit_code_two(monkeypatch, tmp_path):
    lines = ['{"type": "run_end", "summary": "infra"}']
    res, _ = await _run(monkeypatch, tmp_path, lines, exit_code=2)
    assert res.passed is False
    assert res.exit_code == 2


async def test_missing_run_end_defaults(monkeypatch, tmp_path):
    """No run_end object: result still derives pass/fail from the exit code."""
    lines = ['{"step": "only", "status": "ok"}']
    res, steps = await _run(monkeypatch, tmp_path, lines, exit_code=0)
    assert res.passed is True
    assert res.summary == "passed"  # EXIT_MAP label fallback
    assert len(steps) == 1


async def test_screenshot_detected_when_present(monkeypatch, tmp_path):
    """When run_end.run_dir contains screenshot.png, it is surfaced."""
    run_dir = tmp_path / "kane_run"
    run_dir.mkdir()
    (run_dir / "screenshot.png").write_bytes(b"\x89PNG")

    safe = str(run_dir).replace("\\", "\\\\")
    lines = ['{"type": "run_end", "summary": "ok", "run_dir": "' + safe + '"}']
    res, _ = await _run(monkeypatch, tmp_path, lines, exit_code=0)

    assert res.run_dir == str(run_dir)
    assert res.screenshot_path == os.path.join(str(run_dir), "screenshot.png")
