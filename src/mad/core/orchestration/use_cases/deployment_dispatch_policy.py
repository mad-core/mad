"""Deployment-wide dispatch policy use cases (issue #45).

``GET``/``PUT /v1/dispatch_policy`` read and set the single process-global
default that inheriting sessions honour. Setting it emits
``dispatch_policy.default.updated`` under the reserved
``DEPLOYMENT_SESSION_ID`` log so the singleton is rebuilt on restart by
replaying that log (hard rule 6).

``bootstrap_deployment_policy`` is called once at app startup to replay
the reserved log into the live holder before the dispatcher starts.
"""

from __future__ import annotations

from dataclasses import dataclass

from mad.core.events.emitter import EventEmitter
from mad.core.orchestration.domain.deployment_policy import (
    DEPLOYMENT_SESSION_ID,
    DeploymentDispatchPolicy,
)
from mad.core.orchestration.domain.dispatch_policy import (
    DispatchPolicy,
    ImmediatePolicy,
    InvalidDispatchPolicy,
    policy_from_dict,
    policy_to_dict,
)
from mad.core.sessions.ports.outbound.session_repository import SessionRepository


@dataclass(frozen=True)
class SetDeploymentDispatchPolicyInput:
    policy: DispatchPolicy


@dataclass(frozen=True)
class DeploymentDispatchPolicyOutput:
    policy: DispatchPolicy


class GetDeploymentDispatchPolicyUseCase:
    """Return the current deployment default, or ``ImmediatePolicy`` when unset.

    ``ImmediatePolicy`` is the effective default when no deployment policy
    has been configured, so returning it (rather than null) keeps the GET
    response describing actual dispatch behaviour.
    """

    def __init__(self, deployment: DeploymentDispatchPolicy) -> None:
        self._deployment = deployment

    def execute(self) -> DeploymentDispatchPolicyOutput:
        policy = self._deployment.default or ImmediatePolicy()
        return DeploymentDispatchPolicyOutput(policy=policy)


class SetDeploymentDispatchPolicyUseCase:
    """Set the deployment default and persist it via the event log."""

    def __init__(
        self,
        deployment: DeploymentDispatchPolicy,
        emitter: EventEmitter,
    ) -> None:
        self._deployment = deployment
        self._emitter = emitter

    async def execute(
        self, payload: SetDeploymentDispatchPolicyInput
    ) -> DeploymentDispatchPolicyOutput:
        self._deployment.default = payload.policy
        await self._emitter.emit(
            DEPLOYMENT_SESSION_ID,
            "dispatch_policy.default.updated",
            policy_to_dict(payload.policy),
        )
        return DeploymentDispatchPolicyOutput(policy=payload.policy)


def bootstrap_deployment_policy(
    deployment: DeploymentDispatchPolicy,
    repo: SessionRepository,
) -> None:
    """Replay the reserved deployment log into ``deployment`` at startup.

    Applies every ``dispatch_policy.default.updated`` event in order so the
    last one wins. Malformed payloads are skipped defensively. A missing
    log leaves ``deployment.default`` as ``None`` (no default configured).
    """
    if not repo.exists(DEPLOYMENT_SESSION_ID):
        return
    for event in repo.read_events(DEPLOYMENT_SESSION_ID):
        if event.get("type") != "dispatch_policy.default.updated":
            continue
        _meta = {"type", "timestamp", "session_id", "event_id"}
        payload = {k: v for k, v in event.items() if k not in _meta}
        try:
            deployment.default = policy_from_dict(payload)
        except InvalidDispatchPolicy:
            continue
