"""Test-only doubles for the orchestration module.

Lives under ``tests/`` per ADR-0003 / testing-heuristic 3. Use cases
inject these to verify orchestration logic without spinning up the
real projection or replaying a JSONL log.
"""

from __future__ import annotations

from pathlib import Path

from mad.core.orchestration.domain.git_result import GitResult
from mad.core.orchestration.domain.task import Task


class FakeGitInspector:
    """In-memory ``GitInspector`` double (issue #88).

    Tests script the baseline SHA returned at dispatch and the
    :class:`GitResult` (or ``None``) returned at completion, then assert on
    the resulting ``task.git_result`` event without touching a real git repo.
    Set ``result`` to ``None`` to exercise the graceful-omission path; set
    ``raises`` to verify a failing inspector never fails the task.
    """

    def __init__(
        self,
        *,
        base_sha: str | None = "base000",
        result: GitResult | None = None,
        raises: bool = False,
    ) -> None:
        self._base_sha = base_sha
        self._result = result
        self._raises = raises
        self.read_head_sha_calls: list[Path] = []
        self.inspect_calls: list[tuple[Path, str | None]] = []

    async def read_head_sha(self, workspace: Path) -> str | None:
        self.read_head_sha_calls.append(workspace)
        if self._raises:
            raise RuntimeError("git read_head_sha boom")
        return self._base_sha

    async def inspect(self, workspace: Path, base_sha: str | None) -> GitResult | None:
        self.inspect_calls.append((workspace, base_sha))
        if self._raises:
            raise RuntimeError("git inspect boom")
        return self._result


class FakeModelCatalog:
    """In-memory ``ModelCatalog`` double.

    Initialise with a canned ``provider -> [models]`` mapping. Tests
    assert on ``InvalidModelError`` for unknown models and on quiet
    completion for known ones — without hitting any real CLI or network.
    """

    def __init__(self, catalog: dict[str, list[str]] | None = None) -> None:
        self._catalog: dict[str, list[str]] = catalog if catalog is not None else {}

    async def discover(self) -> dict[str, list[str]]:
        return dict(self._catalog)


class FakeTaskQueue:
    """In-memory ``TaskQueue`` double.

    Tests script per-session ``queued`` and ``in_flight`` state. The
    projection's actual replay logic is exercised in the integration
    suite (Phase 4).
    """

    def __init__(
        self,
        queued: dict[str, list[Task]] | None = None,
        in_flight: dict[str, Task] | None = None,
    ) -> None:
        self._queued: dict[str, list[Task]] = {
            sid: list(tasks) for sid, tasks in (queued or {}).items()
        }
        self._in_flight: dict[str, Task] = dict(in_flight or {})

    def queued(self, session_id: str) -> list[Task]:
        return list(self._queued.get(session_id, []))

    def in_flight(self, session_id: str) -> Task | None:
        return self._in_flight.get(session_id)

    def pending_session_ids(self) -> list[str]:
        with_queued = {sid for sid, tasks in self._queued.items() if tasks}
        return sorted(with_queued | self._in_flight.keys())
