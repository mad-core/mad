"""StreamSessionEvents use case.

Returns the SSE queue for a session so the HTTP layer can stream events.
"""
from __future__ import annotations

import asyncio

from mad.core.domain.entities.session import Session
from mad.core.domain.exceptions.base import SessionNotFound


class StreamSessionEventsUseCase:
    """Retrieve (or create) the SSE queue for a session."""

    def __init__(
        self,
        sessions_index: dict[str, Session],
        sse_queues: dict[str, asyncio.Queue[object]],
    ) -> None:
        self._sessions = sessions_index
        self._sse_queues = sse_queues

    def execute(self, session_id: str) -> asyncio.Queue[object]:
        if session_id not in self._sessions:
            raise SessionNotFound(session_id)
        if session_id not in self._sse_queues:
            self._sse_queues[session_id] = asyncio.Queue[object]()
        return self._sse_queues[session_id]
