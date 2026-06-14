"""Integration tests for the OpenCode provider.

AC → test mapping:
  AC-1  stdout lines → agent.output events                  → test_opencode_ac1_*
  AC-2  exit 0 → session.status_idle                        → test_opencode_ac2_*
  AC-3  exit 1 + token in stderr → session.error/redacted   → test_opencode_ac3_*
  AC-4  timeout → session.error < 4s, no zombie             → test_opencode_ac4_*
  AC-5  MAD_OPENCODE_BIN custom path is invoked              → test_opencode_ac5_*
  AC-6  env vars exported correctly (MAD_PROVIDER=opencode)  → test_opencode_ac6_*
  AC-7  --model flag present when model set; absent when None → test_opencode_ac7_*
  AC-8  binary not found → session.error (no crash)          → test_opencode_ac8_*

Tests use fake binary scripts in tmp_path — no real `opencode` binary is invoked.
"""

from __future__ import annotations

import stat
import textwrap
import time
from pathlib import Path

import pytest

from mad.adapters.outbound.agents.opencode import OpenCodeProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_executable_script(path: Path, source: str) -> Path:
    """Write a Python shebang script, make it executable, and return its path."""
    path.write_text("#!/usr/bin/env python3\n" + textwrap.dedent(source))
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


async def _collect_emit(
    launcher: OpenCodeProvider,
    prompt: str,
    workspace: Path,
    session_id: str = "test-session-id",
    model: str | None = None,
) -> list[dict]:
    """Run the launcher and collect all emitted events into a list."""
    collected: list[dict] = []

    async def capture(event_type: str, event: dict) -> None:
        collected.append(event)

    await launcher.run(
        session_id=session_id, prompt=prompt, workspace=workspace, emit=capture, model=model
    )
    return collected


# ---------------------------------------------------------------------------
# AC-1: stdout lines → 3 agent.output events with correct content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_opencode_ac1_stdout_lines_emitted_as_agent_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Three stdout lines from the fake binary must produce 3 agent.output events."""
    fake_bin = _make_executable_script(
        tmp_path / "fake_opencode",
        """\
        import sys
        print("first output line")
        print("second output line")
        print("third output line")
        sys.exit(0)
        """,
    )
    monkeypatch.setenv("MAD_OPENCODE_BIN", str(fake_bin))

    launcher = OpenCodeProvider()
    events = await _collect_emit(launcher, prompt="test", workspace=tmp_path)

    output_events = [e for e in events if e.get("type") == "agent.output"]
    assert len(output_events) == 3, (
        f"Expected 3 agent.output events, got {len(output_events)}: {output_events}"
    )
    lines = [e["line"] for e in output_events]
    assert "first output line" in lines
    assert "second output line" in lines
    assert "third output line" in lines


# ---------------------------------------------------------------------------
# AC-2: exit 0 → session.status_idle; TWIN: exit 1 → session.error (not idle)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_opencode_ac2_exit_zero_emits_status_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A subprocess exit code 0 must produce session.status_idle(stop_reason='end_turn')."""
    fake_bin = _make_executable_script(
        tmp_path / "fake_opencode",
        """\
        import sys
        print("done")
        sys.exit(0)
        """,
    )
    monkeypatch.setenv("MAD_OPENCODE_BIN", str(fake_bin))

    launcher = OpenCodeProvider()
    events = await _collect_emit(launcher, prompt="test", workspace=tmp_path)

    idle_events = [e for e in events if e.get("type") == "session.status_idle"]
    assert len(idle_events) >= 1, (
        f"Expected session.status_idle, got event types: {[e.get('type') for e in events]}"
    )
    assert idle_events[-1].get("stop_reason") == "end_turn", (
        f"session.status_idle must carry stop_reason='end_turn', got: {idle_events[-1]}"
    )


@pytest.mark.asyncio
async def test_opencode_ac2_exit_nonzero_emits_error_not_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative twin: exit code 1 must produce session.error — NOT session.status_idle."""
    fake_bin = _make_executable_script(
        tmp_path / "fake_opencode",
        """\
        import sys
        print("failure output", file=sys.stderr)
        sys.exit(1)
        """,
    )
    monkeypatch.setenv("MAD_OPENCODE_BIN", str(fake_bin))

    launcher = OpenCodeProvider()
    events = await _collect_emit(launcher, prompt="test", workspace=tmp_path)

    error_events = [e for e in events if e.get("type") == "session.error"]
    idle_events = [e for e in events if e.get("type") == "session.status_idle"]
    assert len(error_events) >= 1, (
        f"Expected session.error on exit 1, got types: {[e.get('type') for e in events]}"
    )
    assert len(idle_events) == 0, (
        f"session.status_idle must NOT be emitted on exit 1, got: {idle_events}"
    )
    assert error_events[-1].get("exit_code") == 1, (
        f"session.error must carry exit_code=1, got: {error_events[-1]}"
    )


# ---------------------------------------------------------------------------
# AC-3: exit 1 with token in stderr → session.error with token REDACTED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_opencode_ac3_nonzero_exit_emits_error_with_redacted_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A subprocess exit code 1 with a token in stderr → session.error; token must be [REDACTED]."""
    secret_token = "sk-ant-api03-supersecret-token-value-ABCDEF12345"
    fake_bin = _make_executable_script(
        tmp_path / "fake_opencode",
        f"""\
        import sys
        print("{secret_token}", file=sys.stderr)
        sys.exit(1)
        """,
    )
    monkeypatch.setenv("MAD_OPENCODE_BIN", str(fake_bin))

    launcher = OpenCodeProvider()
    events = await _collect_emit(launcher, prompt="test", workspace=tmp_path)

    error_events = [e for e in events if e.get("type") == "session.error"]
    assert len(error_events) >= 1, (
        f"Expected session.error on exit 1, got types: {[e.get('type') for e in events]}"
    )
    error_payload = str(error_events[-1])
    assert secret_token not in error_payload, (
        f"Token must be redacted in session.error payload, but found it in: {error_payload}"
    )
    assert "[REDACTED]" in error_payload, (
        f"Expected [REDACTED] in session.error payload, got: {error_payload}"
    )


@pytest.mark.asyncio
async def test_opencode_ac3_key_value_in_stderr_is_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative twin: token=SECRET in stderr must be redacted; literal value absent."""
    secret_value = "MYSUPERSECRETVALUE123"
    fake_bin = _make_executable_script(
        tmp_path / "fake_opencode",
        f"""\
        import sys
        print("token={secret_value}", file=sys.stderr)
        sys.exit(1)
        """,
    )
    monkeypatch.setenv("MAD_OPENCODE_BIN", str(fake_bin))

    launcher = OpenCodeProvider()
    events = await _collect_emit(launcher, prompt="test", workspace=tmp_path)

    error_events = [e for e in events if e.get("type") == "session.error"]
    assert len(error_events) >= 1, (
        f"Expected session.error on exit 1, got types: {[e.get('type') for e in events]}"
    )
    error_payload = str(error_events[-1])
    assert secret_value not in error_payload, (
        f"Secret value must be redacted in session.error payload, but found it in: {error_payload}"
    )
    assert "[REDACTED]" in error_payload, (
        f"Expected [REDACTED] in session.error payload, got: {error_payload}"
    )


# ---------------------------------------------------------------------------
# AC-4: timeout kills subprocess; TWIN: fast binary under same timeout → idle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_opencode_ac4_timeout_kills_subprocess_and_emits_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A blocking subprocess must be killed after timeout; session.error emitted; no zombie."""
    fake_bin = _make_executable_script(
        tmp_path / "fake_opencode",
        """\
        import time
        time.sleep(100)
        """,
    )
    monkeypatch.setenv("MAD_OPENCODE_BIN", str(fake_bin))
    monkeypatch.setenv("MAD_OPENCODE_TIMEOUT_S", "0.5")

    launcher = OpenCodeProvider()

    start = time.monotonic()
    events = await _collect_emit(launcher, prompt="test", workspace=tmp_path)
    elapsed = time.monotonic() - start

    assert elapsed < 4.0, f"Timeout should fire within ~2s of the 0.5s limit; took {elapsed:.2f}s"

    error_events = [e for e in events if e.get("type") == "session.error"]
    assert len(error_events) >= 1, (
        f"Expected session.error after timeout, got: {[e.get('type') for e in events]}"
    )
    assert "timed out" in error_events[-1].get("error", ""), (
        f"Expected 'timed out' in error message, got: {error_events[-1]}"
    )


@pytest.mark.asyncio
async def test_opencode_ac4_fast_binary_under_timeout_emits_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative twin: a fast binary under the same timeout must produce session.status_idle."""
    fake_bin = _make_executable_script(
        tmp_path / "fake_opencode",
        """\
        import sys
        print("quick done")
        sys.exit(0)
        """,
    )
    monkeypatch.setenv("MAD_OPENCODE_BIN", str(fake_bin))
    monkeypatch.setenv("MAD_OPENCODE_TIMEOUT_S", "0.5")

    launcher = OpenCodeProvider()
    events = await _collect_emit(launcher, prompt="test", workspace=tmp_path)

    idle_events = [e for e in events if e.get("type") == "session.status_idle"]
    error_events = [e for e in events if e.get("type") == "session.error"]
    assert len(idle_events) >= 1, (
        f"Expected session.status_idle for fast binary, got: {[e.get('type') for e in events]}"
    )
    assert len(error_events) == 0, f"Expected no session.error for fast binary, got: {error_events}"


# ---------------------------------------------------------------------------
# AC-5: MAD_OPENCODE_BIN custom path is invoked (not $PATH opencode)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_opencode_ac5_custom_bin_path_is_invoked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Setting MAD_OPENCODE_BIN must cause that exact binary to be invoked."""
    invoked_marker = tmp_path / "was_invoked"
    fake_bin = _make_executable_script(
        tmp_path / "my_fake_opencode",
        f"""\
        import sys
        open("{invoked_marker}", "w").close()
        print("custom binary invoked")
        sys.exit(0)
        """,
    )
    monkeypatch.setenv("MAD_OPENCODE_BIN", str(fake_bin))
    monkeypatch.setenv("PATH", str(tmp_path / "empty_bin_dir"))

    launcher = OpenCodeProvider()
    await _collect_emit(launcher, prompt="test", workspace=tmp_path)

    assert invoked_marker.exists(), (
        f"Custom binary at {fake_bin} was not invoked — marker file not created. "
        "MAD_OPENCODE_BIN override must be respected."
    )


# ---------------------------------------------------------------------------
# AC-6: env vars exported (MAD_PROVIDER="opencode", MAD_SESSION_ID matches)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_opencode_ac6_env_vars_exported_correctly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MAD_PROVIDER must be 'opencode' and MAD_SESSION_ID must match session_id."""
    env_file = tmp_path / "env_dump.txt"
    fake_bin = _make_executable_script(
        tmp_path / "fake_opencode",
        f"""\
        import os, sys
        with open("{env_file}", "w") as f:
            f.write(f"MAD_SESSION_ID={{os.environ.get('MAD_SESSION_ID', '')}}\\n")
            f.write(f"MAD_PROVIDER={{os.environ.get('MAD_PROVIDER', '')}}\\n")
        sys.exit(0)
        """,
    )
    monkeypatch.setenv("MAD_OPENCODE_BIN", str(fake_bin))

    launcher = OpenCodeProvider()
    await _collect_emit(launcher, prompt="test", workspace=tmp_path, session_id="my-session-123")

    env_text = env_file.read_text()
    assert "MAD_SESSION_ID=my-session-123" in env_text, (
        f"MAD_SESSION_ID must match session_id, got: {env_text}"
    )
    assert "MAD_PROVIDER=opencode" in env_text, f"MAD_PROVIDER must be 'opencode', got: {env_text}"
    assert "MAD_PROVIDER=claude_cli" not in env_text, (
        f"MAD_PROVIDER must NOT be 'claude_cli' for opencode provider, got: {env_text}"
    )


# ---------------------------------------------------------------------------
# AC-7: --model flag; TWIN: model=None → --model absent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_opencode_ac7_model_flag_present_when_model_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When model is provided, argv must contain 'run', '--model', and the model value."""
    marker = tmp_path / "argv.txt"
    fake_bin = _make_executable_script(
        tmp_path / "fake_opencode",
        f"""\
        import sys
        open("{marker}", "w").write(" ".join(sys.argv))
        print("done")
        sys.exit(0)
        """,
    )
    monkeypatch.setenv("MAD_OPENCODE_BIN", str(fake_bin))

    launcher = OpenCodeProvider()
    collected: list[dict] = []

    async def capture(event_type: str, event: dict) -> None:
        collected.append(event)

    await launcher.run(
        session_id="s1",
        prompt="hello",
        workspace=tmp_path,
        emit=capture,
        model="anthropic/claude-sonnet-4-5",
    )

    argv_text = marker.read_text()
    assert "run" in argv_text, f"Expected 'run' subcommand in argv, got: {argv_text}"
    assert "--model" in argv_text, f"Expected --model in argv, got: {argv_text}"
    assert "anthropic/claude-sonnet-4-5" in argv_text, (
        f"Expected model id in argv, got: {argv_text}"
    )


@pytest.mark.asyncio
async def test_opencode_ac7_model_flag_absent_when_model_is_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative twin: when model=None, --model must NOT appear in argv."""
    marker = tmp_path / "argv.txt"
    fake_bin = _make_executable_script(
        tmp_path / "fake_opencode",
        f"""\
        import sys
        open("{marker}", "w").write(" ".join(sys.argv))
        print("done")
        sys.exit(0)
        """,
    )
    monkeypatch.setenv("MAD_OPENCODE_BIN", str(fake_bin))

    launcher = OpenCodeProvider()
    collected: list[dict] = []

    async def capture(event_type: str, event: dict) -> None:
        collected.append(event)

    await launcher.run(
        session_id="s1", prompt="hello", workspace=tmp_path, emit=capture, model=None
    )

    argv_text = marker.read_text()
    assert "run" in argv_text, f"Expected 'run' subcommand in argv, got: {argv_text}"
    assert "--model" not in argv_text, f"Expected --model absent from argv, got: {argv_text}"


# ---------------------------------------------------------------------------
# AC-8: binary not found → single session.error "not found", no crash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_opencode_ac8_binary_not_found_emits_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When opencode is not on PATH and MAD_OPENCODE_BIN is unset, emit session.error."""
    monkeypatch.delenv("MAD_OPENCODE_BIN", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path / "empty_bin_dir"))

    launcher = OpenCodeProvider()
    events = await _collect_emit(launcher, prompt="test", workspace=tmp_path)

    error_events = [e for e in events if e.get("type") == "session.error"]
    assert len(error_events) == 1, (
        f"Expected exactly 1 session.error on binary not found, got: {events}"
    )
    assert "opencode CLI binary not found" in error_events[0].get("error", ""), (
        f"Expected 'opencode CLI binary not found' in error, got: {error_events[0]}"
    )
