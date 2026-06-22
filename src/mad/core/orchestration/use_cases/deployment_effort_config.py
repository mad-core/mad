"""Deployment-wide effort config use cases (issue #60).

``GET``/``PUT /v1/effort`` read and set the single process-global reasoning
effort default that inheriting sessions honour. Setting it emits
``effort.default.updated`` under the reserved ``DEPLOYMENT_EFFORT_SESSION_ID``
log so the singleton is rebuilt on restart by replaying that log (hard rule 6).

``bootstrap_deployment_effort_config`` is called once at app startup to replay
the reserved log into the live holder before the dispatcher starts.

Mirrors ``deployment_model_config`` exactly — effort is the parallel knob.
Effort is an opaque pass-through string: no validation or enumeration (v1).
"""

from __future__ import annotations

from dataclasses import dataclass

from mad.core.events.emitter import EventEmitter
from mad.core.orchestration.domain.effort_config import (
    DEPLOYMENT_EFFORT_SESSION_ID,
    DeploymentEffortConfig,
)
from mad.core.sessions.ports.outbound.session_repository import SessionRepository


@dataclass(frozen=True)
class SetDeploymentEffortInput:
    effort: str


@dataclass(frozen=True)
class DeploymentEffortOutput:
    effort: str | None


class GetDeploymentEffortUseCase:
    """Return the current deployment effort default, or ``None`` when unset."""

    def __init__(self, config: DeploymentEffortConfig) -> None:
        self._config = config

    def execute(self) -> DeploymentEffortOutput:
        return DeploymentEffortOutput(effort=self._config.default_effort)


class SetDeploymentEffortUseCase:
    """Set the deployment effort default and persist it via the event log."""

    def __init__(
        self,
        config: DeploymentEffortConfig,
        emitter: EventEmitter,
    ) -> None:
        self._config = config
        self._emitter = emitter

    async def execute(self, payload: SetDeploymentEffortInput) -> DeploymentEffortOutput:
        self._config.default_effort = payload.effort
        await self._emitter.emit(
            DEPLOYMENT_EFFORT_SESSION_ID,
            "effort.default.updated",
            {"effort": payload.effort},
        )
        return DeploymentEffortOutput(effort=payload.effort)


class ClearDeploymentEffortUseCase:
    """Clear the deployment effort default (revert to provider-chosen default)."""

    def __init__(
        self,
        config: DeploymentEffortConfig,
        emitter: EventEmitter,
    ) -> None:
        self._config = config
        self._emitter = emitter

    async def execute(self) -> DeploymentEffortOutput:
        self._config.default_effort = None
        await self._emitter.emit(
            DEPLOYMENT_EFFORT_SESSION_ID,
            "effort.default.cleared",
            {},
        )
        return DeploymentEffortOutput(effort=None)


def bootstrap_deployment_effort_config(
    config: DeploymentEffortConfig,
    repo: SessionRepository,
) -> None:
    """Replay the reserved deployment effort log into ``config`` at startup.

    Applies every ``effort.default.updated`` / ``effort.default.cleared`` event
    in order so the last one wins. A missing log leaves ``config.default_effort``
    as ``None`` (no default configured).
    """
    if not repo.exists(DEPLOYMENT_EFFORT_SESSION_ID):
        return
    for event in repo.read_events(DEPLOYMENT_EFFORT_SESSION_ID):
        etype = event.get("type")
        if etype == "effort.default.updated":
            config.default_effort = event.get("effort")
        elif etype == "effort.default.cleared":
            config.default_effort = None
