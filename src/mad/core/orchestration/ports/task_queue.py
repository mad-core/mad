"""TaskQueue port — read-side projection of orchestration state per session.

Implementations replay the JSONL event log (ADR-0009 Decision 3) into
an in-memory projection: per session, a ``queued`` list (insertion
order) and at most one ``in_flight`` task. Terminal-state tasks
(completed, cancelled, failed) are not represented here; the event log
remains authoritative.

This is a **read** port. Use cases that mutate orchestration state
emit events through ``EventEmitter`` (hard rule 11); the projection
materialises those events on the next replay or, in a long-lived
process, by tailing the bus.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mad.core.orchestration.domain.task import Task


@dataclass(frozen=True)
class RetryInfo:
    """Snapshot of the current rate-limit retry state for an in-flight task.

    Exposed by ``TaskQueue.retry_info`` so the HTTP/MCP surface can show an
    explicit ``"retrying"`` status rather than the same ``"dispatched"`` shown
    during a normal run.
    """

    attempt: int
    retry_after_s: float
    reason: str


class TaskQueue(Protocol):
    """Read-side projection of the orchestration state."""

    def queued(self, session_id: str) -> list[Task]:
        """Return the queued tasks for ``session_id`` in insertion order."""
        ...

    def in_flight(self, session_id: str) -> Task | None:
        """Return the currently-dispatched task for ``session_id``, if any."""
        ...

    def retry_info(self, session_id: str) -> RetryInfo | None:
        """Return rate-limit retry metadata for the in-flight task, if any.

        ``None`` means the task is running normally (no backoff in progress).
        Non-``None`` means the task is sleeping between retry attempts and the
        status should be rendered as ``"retrying"`` on the HTTP/MCP surface.
        """
        ...

    def pending_session_ids(self) -> list[str]:
        """Return ids of sessions with at least one queued or in-flight task.

        Cross-session read (issue #46): startup rehydration uses it to
        decide which sessions to rebuild into the live index, and
        ``GET /v1/queue`` uses it to scope the global queue view.
        """
        ...
