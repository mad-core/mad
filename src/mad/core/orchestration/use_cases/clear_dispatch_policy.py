"""ClearDispatchPolicyUseCase — drop a session's per-session override (issue #45).

``DELETE /v1/sessions/{id}/dispatch_policy`` removes the session's pinned
policy so it resumes inheriting the deployment default. Emits
``dispatch_policy.cleared`` so the cleared state survives a restart via
JSONL replay (hard rule 6).

Clearing is idempotent: a DELETE on a session that already inherits is a
no-op success (it still emits the event — replay converges to ``None``
either way and the operator gets a 200, not a 409).
"""

from __future__ import annotations

from dataclasses import dataclass

from mad.core.events.emitter import EventEmitter
from mad.core.orchestration.domain.deployment_policy import (
    DeploymentDispatchPolicy,
    resolve_effective_policy,
)
from mad.core.orchestration.domain.dispatch_policy import DispatchPolicy
from mad.core.sessions.domain.entities.session import Session
from mad.core.sessions.domain.exceptions.base import SessionNotFound


@dataclass(frozen=True)
class ClearDispatchPolicyInput:
    session_id: str


@dataclass(frozen=True)
class ClearDispatchPolicyOutput:
    session_id: str
    effective_policy: DispatchPolicy


class ClearDispatchPolicyUseCase:
    """Clear a session's override and re-inherit the deployment default."""

    def __init__(
        self,
        sessions_index: dict[str, Session],
        deployment: DeploymentDispatchPolicy,
        emitter: EventEmitter,
    ) -> None:
        self._sessions = sessions_index
        self._deployment = deployment
        self._emitter = emitter

    async def execute(self, payload: ClearDispatchPolicyInput) -> ClearDispatchPolicyOutput:
        if payload.session_id not in self._sessions:
            raise SessionNotFound(payload.session_id)
        session = self._sessions[payload.session_id]

        session.dispatch_policy = None
        # Drain counter is policy-mode-specific; a stale one from a prior
        # ManualPolicy override must not leak into the inherited policy.
        session.manual_drain_remaining = 0

        await self._emitter.emit(
            payload.session_id,
            "dispatch_policy.cleared",
            None,
        )

        return ClearDispatchPolicyOutput(
            session_id=payload.session_id,
            effective_policy=resolve_effective_policy(session, self._deployment),
        )
