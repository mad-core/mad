"""Unit tests for the deployment-wide dispatch policy use cases (issue #45).

Covers ``GetDeploymentDispatchPolicyUseCase`` (unset → immediate; set →
echoes), ``SetDeploymentDispatchPolicyUseCase`` (mutates the holder AND
emits exactly one ``dispatch_policy.default.updated`` under the reserved
deployment id), ``bootstrap_deployment_policy`` (last-write-wins replay;
missing log → ``None``), and ``resolve_effective_policy`` (override →
default → immediate).

Fakes come from ``tests/support`` (heuristic 3): ``FakeEventStore`` +
``RecordingEventBus`` drive the emitter; ``FakeSessionRepository`` (the
``DualInterfaceEventStore``) provides the ``read_events`` / ``exists``
surface ``bootstrap_deployment_policy`` reads.
"""

from __future__ import annotations

from datetime import time
from zoneinfo import ZoneInfo

from mad.core.events.emitter import EventEmitter
from mad.core.orchestration.domain.deployment_policy import (
    DEPLOYMENT_SESSION_ID,
    DeploymentDispatchPolicy,
    resolve_effective_policy,
)
from mad.core.orchestration.domain.dispatch_policy import (
    ImmediatePolicy,
    ManualPolicy,
    Window,
    WorkWindowPolicy,
    policy_to_dict,
)
from mad.core.orchestration.use_cases.deployment_dispatch_policy import (
    GetDeploymentDispatchPolicyUseCase,
    SetDeploymentDispatchPolicyInput,
    SetDeploymentDispatchPolicyUseCase,
    bootstrap_deployment_policy,
)
from mad.core.sessions.domain.entities.session import Session
from support.events import FakeEventStore, RecordingEventBus
from support.sessions import FakeSessionRepository


def _session(session_id: str = "sesn_a") -> Session:
    return Session(
        session_id=session_id,
        agent={"name": "t", "provider": "fake"},
        workspace="/tmp/mad_t",
        tokens_to_redact=[],
    )


# -- GetDeploymentDispatchPolicyUseCase ---------------------------------------


def test_get_returns_immediate_when_no_default_configured() -> None:
    """With ``default=None`` the GET reports the effective fallback every
    inheriting session uses rather than null."""
    use_case = GetDeploymentDispatchPolicyUseCase(deployment=DeploymentDispatchPolicy())

    output = use_case.execute()

    assert isinstance(output.policy, ImmediatePolicy)


def test_get_returns_the_configured_default() -> None:
    """Negative twin: a set holder is echoed verbatim, not coerced to
    immediate."""
    deployment = DeploymentDispatchPolicy(default=ManualPolicy())
    use_case = GetDeploymentDispatchPolicyUseCase(deployment=deployment)

    output = use_case.execute()

    assert isinstance(output.policy, ManualPolicy)


# -- SetDeploymentDispatchPolicyUseCase ---------------------------------------


async def test_set_mutates_holder_and_emits_one_default_updated_event() -> None:
    deployment = DeploymentDispatchPolicy()
    store = FakeEventStore()
    emitter = EventEmitter(store=store, bus=RecordingEventBus())
    use_case = SetDeploymentDispatchPolicyUseCase(deployment=deployment, emitter=emitter)

    output = await use_case.execute(SetDeploymentDispatchPolicyInput(policy=ManualPolicy()))

    assert isinstance(output.policy, ManualPolicy)
    assert isinstance(deployment.default, ManualPolicy)
    # Exactly one event, of the right type, under the reserved deployment id.
    default_updates = [c for c in store.calls if c[1] == "dispatch_policy.default.updated"]
    assert len(default_updates) == 1
    session_id, _type, data = default_updates[0]
    assert session_id == DEPLOYMENT_SESSION_ID
    assert data == policy_to_dict(ManualPolicy())


async def test_set_does_not_emit_under_a_real_session_id() -> None:
    """Negative twin: the deployment default is a process-global stream, NOT
    attributed to any user session. Nothing must land under a real id."""
    deployment = DeploymentDispatchPolicy()
    store = FakeEventStore()
    emitter = EventEmitter(store=store, bus=RecordingEventBus())
    use_case = SetDeploymentDispatchPolicyUseCase(deployment=deployment, emitter=emitter)

    await use_case.execute(SetDeploymentDispatchPolicyInput(policy=ManualPolicy()))

    assert all(c[0] == DEPLOYMENT_SESSION_ID for c in store.calls)
    assert not any(c[0] == "sesn_a" for c in store.calls)


async def test_set_work_window_emits_full_serialized_payload() -> None:
    deployment = DeploymentDispatchPolicy()
    store = FakeEventStore()
    emitter = EventEmitter(store=store, bus=RecordingEventBus())
    use_case = SetDeploymentDispatchPolicyUseCase(deployment=deployment, emitter=emitter)
    policy = WorkWindowPolicy(
        windows=(
            Window(
                start=time(18, 0),
                end=time(8, 0),
                timezone=ZoneInfo("America/Mexico_City"),
            ),
        )
    )

    await use_case.execute(SetDeploymentDispatchPolicyInput(policy=policy))

    default_updates = [c for c in store.calls if c[1] == "dispatch_policy.default.updated"]
    assert len(default_updates) == 1
    data = default_updates[0][2]
    assert data["kind"] == "work_window"
    assert data["windows"][0]["start"] == "18:00"
    assert data["windows"][0]["end"] == "08:00"
    assert data["windows"][0]["timezone"] == "America/Mexico_City"


# -- bootstrap_deployment_policy ----------------------------------------------


def test_bootstrap_replays_last_default_updated_wins() -> None:
    """Two ``dispatch_policy.default.updated`` events in the reserved log →
    the LAST one wins after replay (hard rule 6)."""
    repo = FakeSessionRepository()
    repo.append_event(
        DEPLOYMENT_SESSION_ID,
        "dispatch_policy.default.updated",
        policy_to_dict(ManualPolicy()),
    )
    repo.append_event(
        DEPLOYMENT_SESSION_ID,
        "dispatch_policy.default.updated",
        policy_to_dict(ImmediatePolicy()),
    )
    deployment = DeploymentDispatchPolicy()

    bootstrap_deployment_policy(deployment, repo)

    assert isinstance(deployment.default, ImmediatePolicy)


def test_bootstrap_missing_log_leaves_default_none() -> None:
    """Negative twin: no reserved log → no default configured (``None``),
    so sessions fall back to ImmediatePolicy at dispatch time."""
    repo = FakeSessionRepository()
    deployment = DeploymentDispatchPolicy()

    bootstrap_deployment_policy(deployment, repo)

    assert deployment.default is None


# -- resolve_effective_policy -------------------------------------------------


def test_resolve_prefers_session_override_over_deployment_default() -> None:
    session = _session()
    session.dispatch_policy = ImmediatePolicy()
    deployment = DeploymentDispatchPolicy(default=ManualPolicy())

    resolved = resolve_effective_policy(session, deployment)

    assert isinstance(resolved, ImmediatePolicy)


def test_resolve_falls_back_to_deployment_default_when_no_override() -> None:
    session = _session()
    assert session.dispatch_policy is None
    deployment = DeploymentDispatchPolicy(default=ManualPolicy())

    resolved = resolve_effective_policy(session, deployment)

    assert isinstance(resolved, ManualPolicy)


def test_resolve_falls_back_to_immediate_when_nothing_configured() -> None:
    session = _session()
    assert session.dispatch_policy is None

    resolved = resolve_effective_policy(session, DeploymentDispatchPolicy(default=None))

    assert isinstance(resolved, ImmediatePolicy)
