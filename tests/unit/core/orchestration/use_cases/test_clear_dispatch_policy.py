"""Unit tests for ``ClearDispatchPolicyUseCase`` (issue #45).

``DELETE /v1/sessions/{id}/dispatch_policy`` drops the per-session
override so the session re-inherits the deployment default. Covers the
happy path (override cleared, drain counter reset, one
``dispatch_policy.cleared`` emitted, effective policy reflects the
inherited default), the idempotent no-op twin (already inheriting →
still 200/emits), and the unknown-session twin (``SessionNotFound``).

Fakes come from ``tests/support`` (heuristic 3).
"""

from __future__ import annotations

import pytest

from mad.core.events.emitter import EventEmitter
from mad.core.orchestration.domain.deployment_policy import DeploymentDispatchPolicy
from mad.core.orchestration.domain.dispatch_policy import (
    ImmediatePolicy,
    ManualPolicy,
)
from mad.core.orchestration.use_cases.clear_dispatch_policy import (
    ClearDispatchPolicyInput,
    ClearDispatchPolicyUseCase,
)
from mad.core.sessions.domain.entities.session import Session
from mad.core.sessions.domain.exceptions.base import SessionNotFound
from support.events import FakeEventStore, RecordingEventBus


def _session(session_id: str = "sesn_a") -> Session:
    return Session(
        session_id=session_id,
        agent={"name": "t", "provider": "fake"},
        workspace="/tmp/mad_t",
        tokens_to_redact=[],
    )


def _make_use_case(
    sessions: dict[str, Session],
    deployment: DeploymentDispatchPolicy,
) -> tuple[ClearDispatchPolicyUseCase, FakeEventStore]:
    store = FakeEventStore()
    emitter = EventEmitter(store=store, bus=RecordingEventBus())
    use_case = ClearDispatchPolicyUseCase(
        sessions_index=sessions,
        deployment=deployment,
        emitter=emitter,
    )
    return use_case, store


async def test_clear_existing_override_reinherits_deployment_default() -> None:
    session = _session()
    session.dispatch_policy = ImmediatePolicy()
    session.manual_drain_remaining = 3
    sessions = {"sesn_a": session}
    deployment = DeploymentDispatchPolicy(default=ManualPolicy())
    use_case, store = _make_use_case(sessions, deployment)

    output = await use_case.execute(ClearDispatchPolicyInput(session_id="sesn_a"))

    # Override dropped; session now inherits the deployment manual default.
    assert session.dispatch_policy is None
    assert session.manual_drain_remaining == 0
    assert isinstance(output.effective_policy, ManualPolicy)
    assert output.session_id == "sesn_a"
    # Exactly one cleared event under the session id, with no payload.
    cleared = [c for c in store.calls if c[1] == "dispatch_policy.cleared"]
    assert len(cleared) == 1
    assert cleared[0][0] == "sesn_a"
    assert cleared[0][2] is None


async def test_clear_already_inheriting_session_is_noop_success() -> None:
    """Idempotent twin: the session has no override; clearing still succeeds
    and still emits ``dispatch_policy.cleared`` (replay converges to None
    either way). With no deployment default, the effective policy is
    immediate."""
    session = _session()
    assert session.dispatch_policy is None
    sessions = {"sesn_a": session}
    deployment = DeploymentDispatchPolicy(default=None)
    use_case, store = _make_use_case(sessions, deployment)

    output = await use_case.execute(ClearDispatchPolicyInput(session_id="sesn_a"))

    assert session.dispatch_policy is None
    assert isinstance(output.effective_policy, ImmediatePolicy)
    cleared = [c for c in store.calls if c[1] == "dispatch_policy.cleared"]
    assert len(cleared) == 1


async def test_clear_unknown_session_raises_session_not_found() -> None:
    """Negative twin: an unknown id raises ``SessionNotFound`` and emits
    nothing."""
    sessions: dict[str, Session] = {}
    deployment = DeploymentDispatchPolicy(default=ManualPolicy())
    use_case, store = _make_use_case(sessions, deployment)

    with pytest.raises(SessionNotFound):
        await use_case.execute(ClearDispatchPolicyInput(session_id="sesn_missing"))

    assert store.calls == []
