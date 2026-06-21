from __future__ import annotations

import asyncio
import os
import re
import sys
from collections.abc import AsyncIterator
from pathlib import Path

# StreamReader buffers each subprocess pipe up to this many bytes before
# raising LimitOverrunError. asyncio's default is 64 KB, which a single long
# stdout line blows past — common with `--output-format stream-json` (a large
# tool_result, a big diff, verbose `npm install`/`terraform` output) — and that
# kills the launcher task with `session.error`. 64 MB covers realistic agent
# output while still bounding memory. See issue #70.
_STDOUT_BUFFER_LIMIT = 64 * 1024 * 1024


async def _iter_stdout_lines(stream: asyncio.StreamReader) -> AsyncIterator[str]:
    """Yield decoded, newline-stripped lines from a subprocess stdout stream.

    Robust against lines that still exceed ``_STDOUT_BUFFER_LIMIT``: rather than
    letting ``LimitOverrunError`` propagate out of ``async for`` (which kills the
    launcher task — issue #70), the oversized line is dropped and iteration
    continues. ``StreamReader.readline`` drains the offending bytes from its
    buffer before raising, so the next call resumes cleanly on the following
    line. A long-but-bounded line (≤ the limit) is yielded intact.
    """
    while True:
        try:
            line_bytes = await stream.readline()
        except (asyncio.LimitOverrunError, ValueError):
            # Line exceeded the buffer limit; readline already discarded it.
            # Skip rather than crash so the rest of the stream is still read.
            continue
        if not line_bytes:
            break
        yield line_bytes.decode(errors="replace").rstrip("\n")


def _scrub(text: str) -> str:
    text = re.sub(r"sk-ant-[A-Za-z0-9_-]+", "[REDACTED]", text)
    text = re.sub(r"(?i)(token|key|secret|password)[=:\s]+\S+", r"\1=[REDACTED]", text)
    return text


def _subprocess_env() -> dict[str, str]:
    """Build an env dict for the subprocess.

    Ensures PATH includes the directory of the current Python interpreter so
    that shebang lines (#!/usr/bin/env python3) work even when the calling
    process has a restricted PATH (e.g. during tests).
    """
    env = dict(os.environ)
    python_dir = str(Path(sys.executable).parent)
    current_path = env.get("PATH", "")
    path_entries = current_path.split(os.pathsep) if current_path else []
    standard = ["/usr/local/bin", "/usr/bin", "/bin", python_dir]
    for entry in standard:
        if entry not in path_entries:
            path_entries.append(entry)
    env["PATH"] = os.pathsep.join(path_entries)
    return env
