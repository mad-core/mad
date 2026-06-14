"""Deployment-wide model config use cases (issue #55).

``GET``/``PUT /v1/model`` read and set the single process-global model
default that inheriting sessions honour.  Setting it emits
``model.default.updated`` under the reserved ``DEPLOYMENT_MODEL_SESSION_ID``
log so the singleton is rebuilt on restart by replaying that log (hard rule 6).

``bootstrap_deployment_model_config`` is called once at app startup to replay
the reserved log into the live holder before the dispatcher starts.
"""

from __future__ import annotations

from dataclasses import dataclass

from mad.core.events.emitter import EventEmitter
from mad.core.orchestration.domain.model_config import (
    DEPLOYMENT_MODEL_SESSION_ID,
    DeploymentModelConfig,
)
from mad.core.sessions.ports.outbound.session_repository import SessionRepository


@dataclass(frozen=True)
class SetDeploymentModelInput:
    model: str


@dataclass(frozen=True)
class DeploymentModelOutput:
    model: str | None


class GetDeploymentModelUseCase:
    """Return the current deployment model default, or ``None`` when unset."""

    def __init__(self, config: DeploymentModelConfig) -> None:
        self._config = config

    def execute(self) -> DeploymentModelOutput:
        return DeploymentModelOutput(model=self._config.default_model)


class SetDeploymentModelUseCase:
    """Set the deployment model default and persist it via the event log."""

    def __init__(
        self,
        config: DeploymentModelConfig,
        emitter: EventEmitter,
    ) -> None:
        self._config = config
        self._emitter = emitter

    async def execute(self, payload: SetDeploymentModelInput) -> DeploymentModelOutput:
        self._config.default_model = payload.model
        await self._emitter.emit(
            DEPLOYMENT_MODEL_SESSION_ID,
            "model.default.updated",
            {"model": payload.model},
        )
        return DeploymentModelOutput(model=payload.model)


class ClearDeploymentModelUseCase:
    """Clear the deployment model default (revert to provider-chosen default)."""

    def __init__(
        self,
        config: DeploymentModelConfig,
        emitter: EventEmitter,
    ) -> None:
        self._config = config
        self._emitter = emitter

    async def execute(self) -> DeploymentModelOutput:
        self._config.default_model = None
        await self._emitter.emit(
            DEPLOYMENT_MODEL_SESSION_ID,
            "model.default.cleared",
            {},
        )
        return DeploymentModelOutput(model=None)


def bootstrap_deployment_model_config(
    config: DeploymentModelConfig,
    repo: SessionRepository,
) -> None:
    """Replay the reserved deployment model log into ``config`` at startup.

    Applies every ``model.default.updated`` / ``model.default.cleared`` event
    in order so the last one wins.  A missing log leaves ``config.default_model``
    as ``None`` (no default configured).
    """
    if not repo.exists(DEPLOYMENT_MODEL_SESSION_ID):
        return
    for event in repo.read_events(DEPLOYMENT_MODEL_SESSION_ID):
        etype = event.get("type")
        if etype == "model.default.updated":
            config.default_model = event.get("model")
        elif etype == "model.default.cleared":
            config.default_model = None
