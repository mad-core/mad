"""Test-only AgentLauncher implementations.

Lives under tests/ on purpose: production code in src/ should not carry
fixtures or fakes. Each test that needs scripted agent output instantiates
ScriptedLauncher and feeds it a list of event sequences.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any


class ScriptedLauncher:
    """AgentLauncher test double. Each call to run() consumes the next
    scripted run from the queue and emits its events in order.
    """

    def __init__(self) -> None:
        self._queue: deque[list[dict]] = deque()

    def script(self, runs: list[list[dict]]) -> None:
        self._queue = deque(runs)

    async def run(
        self,
        prompt: str,
        workspace: Path,
        emit: Callable[[str, dict | None], Coroutine[Any, Any, None]],
    ) -> None:
        if self._queue:
            events = self._queue.popleft()
        else:
            events = [{"type": "session.status_idle", "stop_reason": "end_turn"}]
        for event in events:
            await emit(event["type"], event)
