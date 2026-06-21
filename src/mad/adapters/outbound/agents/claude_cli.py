from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from mad.adapters.outbound.agents._subprocess import _scrub, _subprocess_env
from mad.adapters.outbound.agents.hook_socket import resolve_hook_socket_path
from mad.core.orchestration.domain.exceptions.rate_limit import RateLimitError

# Errors the CLI reports in system/api_retry events that are retriable.
_RETRIABLE_ERRORS = frozenset({"rate_limit", "overloaded"})

# Stderr substrings that confirm a rate-limit exit when structured events
# are unavailable (e.g. the process exits before emitting api_retry).
_RATE_LIMIT_STDERR_PATTERNS = (
    "rate_limit",
    "429",
    "overloaded",
    "529",
    "session limit",
    "resets ",
    "temporarily limiting",
    "at capacity",
)


class ClaudeCLIError(Exception):
    def __init__(self, exit_code: int, stderr_tail: str) -> None:
        self.exit_code = exit_code
        self.stderr_tail = stderr_tail
        super().__init__(f"claude CLI exited {exit_code}: {stderr_tail}")


class ClaudeCLIProvider:
    async def run(
        self,
        session_id: str,
        prompt: str,
        workspace: Path,
        emit: Callable[[str, dict | None], Coroutine[Any, Any, None]],
        model: str | None = None,
        conversation_id: str | None = None,
    ) -> str | None:
        executable = os.environ.get("MAD_CLAUDE_CLI_BIN") or shutil.which("claude")
        if not executable:
            await emit(
                "session.error",
                {"type": "session.error", "error": "claude CLI binary not found"},
            )
            return None

        timeout = float(os.environ.get("MAD_CLAUDE_CLI_TIMEOUT_S", "600"))

        env = _subprocess_env()
        env["MAD_SESSION_ID"] = session_id
        env["MAD_HOOK_SOCKET"] = resolve_hook_socket_path()
        env["MAD_PROVIDER"] = "claude_cli"
        # Disable the CLI's own retry loop so Mad owns the full retry
        # schedule and can emit task.retrying events with correct backoff.
        env["CLAUDE_CODE_MAX_RETRIES"] = "0"

        args = [
            executable,
            "--dangerously-skip-permissions",
            "--output-format",
            "stream-json",
            "--verbose",
            "-p",
            prompt,
        ]
        if conversation_id is not None:
            args += ["--resume", conversation_id]
        if model is not None:
            args += ["--model", model]

        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        captured_id: str | None = None
        conversation_started_emitted = False
        rate_limit_detected = False
        rate_limit_reason = "rate_limit"

        try:
            async with asyncio.timeout(timeout):
                async for line_bytes in proc.stdout:
                    line = line_bytes.decode(errors="replace").rstrip("\n")
                    await emit("agent.output", {"type": "agent.output", "line": line})
                    # Parse every JSON line. The stream-json format carries
                    # session_id on system/init (first line), api_retry, and
                    # result. Parsing every line lets us detect rate-limit
                    # signals from api_retry events even after conversation
                    # start is already recorded.
                    try:
                        obj = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue

                    # Update conversation ID from any event that carries it.
                    sid = obj.get("session_id")
                    if sid and isinstance(sid, str) and captured_id is None:
                        captured_id = sid

                    # Emit agent.conversation_started once, as soon as we
                    # have an ID.
                    if not conversation_started_emitted and captured_id:
                        conversation_started_emitted = True
                        await emit(
                            "agent.conversation_started",
                            {
                                "conversation_id": captured_id,
                                "provider": "claude_cli",
                            },
                        )

                    # Detect rate-limit signal. system/api_retry carries the
                    # error enum and session_id, even on the attempt that
                    # ultimately exhausts retries.
                    if obj.get("type") == "system" and obj.get("subtype") == "api_retry":
                        error = obj.get("error", "rate_limit")
                        if error in _RETRIABLE_ERRORS:
                            rate_limit_detected = True
                            rate_limit_reason = error
                            # api_retry events include session_id — prefer
                            # this as the most recent capture point.
                            retry_sid = obj.get("session_id")
                            if retry_sid and isinstance(retry_sid, str):
                                captured_id = retry_sid

                await proc.wait()
        except TimeoutError:
            proc.kill()
            await proc.wait()
            await emit(
                "session.error",
                {"type": "session.error", "error": f"timed out after {timeout}s"},
            )
            return captured_id
        except asyncio.CancelledError:
            proc.kill()
            await proc.wait()
            await emit("session.error", {"type": "session.error", "error": "cancelled"})
            raise

        if proc.returncode == 0:
            await emit(
                "session.status_idle",
                {"type": "session.status_idle", "stop_reason": "end_turn"},
            )
            return captured_id

        # Non-zero exit: read stderr for error detail and rate-limit fallback.
        stderr_raw = b""
        if proc.stderr:
            stderr_raw = await proc.stderr.read()
        stderr_text = stderr_raw.decode(errors="replace")
        stderr_tail = stderr_text[-2000:]

        # Stderr pattern fallback: detect rate-limit even when no
        # system/api_retry event appeared in stdout (e.g. process crashed
        # before emitting the structured event).
        if not rate_limit_detected:
            lower = stderr_tail.lower()
            if any(pat in lower for pat in _RATE_LIMIT_STDERR_PATTERNS):
                rate_limit_detected = True

        if rate_limit_detected:
            # Do NOT emit session.error — the dispatcher will retry and
            # only emits task.failed after the ceiling is exhausted.
            raise RateLimitError(captured_id=captured_id, reason=rate_limit_reason)

        scrubbed = _scrub(stderr_tail)
        await emit(
            "session.error",
            {
                "type": "session.error",
                "error": scrubbed,
                "exit_code": proc.returncode,
            },
        )
        return captured_id
