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


class RecordingLauncher:
    """AgentLauncher test double that records the prompt of every run
    and emits a single ``session.status_idle`` event per call.

    Used by tests that only care about *which prompts* the use case
    invokes the launcher with (e.g. issue #8 auto-sync verifies that
    a second post-run invocation receives the auto-sync prompt).
    """

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.session_ids: list[str] = []
        self.models: list[str | None] = []
        self.conversation_ids: list[str | None] = []

    async def run(
        self,
        session_id: str,
        prompt: str,
        workspace: Path,
        emit: Callable[[str, dict | None], Coroutine[Any, Any, None]],
        model: str | None = None,
        conversation_id: str | None = None,
    ) -> str | None:
        self.session_ids.append(session_id)
        self.calls.append(prompt)
        self.models.append(model)
        self.conversation_ids.append(conversation_id)
        await emit("session.status_idle", {"stop_reason": "end_turn"})
        return None


class RaisingLauncher:
    """AgentLauncher test double that raises a fixed exception on every
    ``run`` call. Used by tests that exercise the dispatcher's
    launcher-failure path (``task.failed`` emission) without needing
    scripted bus events. Lives here per heuristic 3 so a contract
    drift on ``AgentLauncher.run`` fails one place, not many.
    """

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def run(
        self,
        session_id: str,
        prompt: str,
        workspace: Path,
        emit: Callable[[str, dict | None], Coroutine[Any, Any, None]],
        model: str | None = None,
        conversation_id: str | None = None,
    ) -> str | None:
        raise self._exc


class ScriptedLauncher:
    """AgentLauncher test double. Each call to run() consumes the next
    scripted run from the queue and emits its events in order.

    The optional ``return_conversation_id`` constructor argument provides
    the conversation id that every run returns (default ``None``).
    Per-run overrides can be set via ``script_with_ids``.
    """

    def __init__(self, return_conversation_id: str | None = None) -> None:
        self._queue: deque[list[dict]] = deque()
        self._ids: deque[str | None] = deque()
        self._default_id = return_conversation_id
        self.calls: list[dict[str, Any]] = []

    def script(self, runs: list[list[dict]]) -> None:
        self._queue = deque(runs)
        self._ids = deque()

    def script_with_ids(self, runs: list[tuple[list[dict], str | None]]) -> None:
        """Script runs where each run may return a specific conversation id.

        ``runs`` is a list of ``(events, conversation_id)`` tuples.
        """
        self._queue = deque(r for r, _ in runs)
        self._ids = deque(cid for _, cid in runs)

    async def run(
        self,
        session_id: str,
        prompt: str,
        workspace: Path,
        emit: Callable[[str, dict | None], Coroutine[Any, Any, None]],
        model: str | None = None,
        conversation_id: str | None = None,
    ) -> str | None:
        self.calls.append(
            {
                "session_id": session_id,
                "prompt": prompt,
                "workspace": workspace,
                "model": model,
                "conversation_id": conversation_id,
            }
        )
        if self._queue:
            events = self._queue.popleft()
        else:
            events = [{"type": "session.status_idle", "stop_reason": "end_turn"}]
        for event in events:
            await emit(event["type"], event)
        if self._ids:
            return self._ids.popleft()
        return self._default_id
