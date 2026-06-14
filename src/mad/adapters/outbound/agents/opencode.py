from __future__ import annotations

import asyncio
import os
import shutil
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from mad.adapters.outbound.agents._subprocess import _scrub, _subprocess_env
from mad.adapters.outbound.agents.hook_socket import resolve_hook_socket_path


class OpenCodeProvider:
    async def run(
        self,
        session_id: str,
        prompt: str,
        workspace: Path,
        emit: Callable[[str, dict | None], Coroutine[Any, Any, None]],
        model: str | None = None,
    ) -> None:
        executable = os.environ.get("MAD_OPENCODE_BIN") or shutil.which("opencode")
        if not executable:
            await emit(
                "session.error",
                {"type": "session.error", "error": "opencode CLI binary not found"},
            )
            return

        timeout = float(os.environ.get("MAD_OPENCODE_TIMEOUT_S", "600"))

        env = _subprocess_env()
        env["MAD_SESSION_ID"] = session_id
        env["MAD_HOOK_SOCKET"] = resolve_hook_socket_path()
        env["MAD_PROVIDER"] = "opencode"

        args = [executable, "run"]
        if model is not None:
            args += ["--model", model]
        args.append(prompt)

        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        try:
            async with asyncio.timeout(timeout):
                async for line_bytes in proc.stdout:
                    line = line_bytes.decode(errors="replace").rstrip("\n")
                    await emit("agent.output", {"type": "agent.output", "line": line})
                await proc.wait()
        except TimeoutError:
            proc.kill()
            await proc.wait()
            await emit(
                "session.error",
                {"type": "session.error", "error": f"timed out after {timeout}s"},
            )
            return
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
