"""DeleteSession use case."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from mad.core.domain.entities.session import Session
from mad.core.domain.exceptions.base import SessionNotFound
from mad.core.ports.outbound.workspace_provisioner import WorkspaceProvisioner


@dataclass
class DeleteSessionOutput:
    session_id: str
    status: str


class DeleteSessionUseCase:
    """Delete a session and destroy its workspace."""

    def __init__(
        self,
        provisioner: WorkspaceProvisioner,
        sessions_index: dict[str, Session],
        sse_queues: dict[str, asyncio.Queue[object]],
    ) -> None:
        self._provisioner = provisioner
        self._sessions = sessions_index
        self._sse_queues = sse_queues

    def execute(self, session_id: str) -> DeleteSessionOutput:
        if session_id not in self._sessions:
            raise SessionNotFound(session_id)

        session = self._sessions[session_id]
        self._provisioner.destroy(session_id)
        session.mark_deleted()
        self._sse_queues.pop(session_id, None)

        return DeleteSessionOutput(session_id=session_id, status="deleted")
