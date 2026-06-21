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

        args = [
            executable,
            "--dangerously-skip-permissions",
            "--output-format",
            "stream-json",
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

        try:
            async with asyncio.timeout(timeout):
                async for line_bytes in proc.stdout:
                    line = line_bytes.decode(errors="replace").rstrip("\n")
                    await emit("agent.output", {"type": "agent.output", "line": line})
                    # Parse each JSON line for session_id. The stream-json
                    # format carries it on system/init (first event), api_retry,
                    # and result — so we capture it as early as the first line.
                    if not conversation_started_emitted:
                        try:
                            obj = json.loads(line)
                        except (json.JSONDecodeError, ValueError):
                            continue
                        sid = obj.get("session_id")
                        if sid and isinstance(sid, str):
                            captured_id = sid
                            conversation_started_emitted = True
                            await emit(
                                "agent.conversation_started",
                                {
                                    "conversation_id": sid,
                                    "provider": "claude_cli",
                                },
                            )
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
        else:
            stderr_raw = b""
            if proc.stderr:
                stderr_raw = await proc.stderr.read()
            stderr_text = stderr_raw.decode(errors="replace")
            scrubbed = _scrub(stderr_text[-2000:])
            await emit(
                "session.error",
                {
                    "type": "session.error",
                    "error": scrubbed,
                    "exit_code": proc.returncode,
                },
            )
        return captured_id
