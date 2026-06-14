from __future__ import annotations

import os
import re
import sys
from pathlib import Path


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
