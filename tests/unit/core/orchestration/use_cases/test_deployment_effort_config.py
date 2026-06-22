"""Unit tests for the deployment-wide effort config use cases (issue #60).

Covers ``GetDeploymentEffortUseCase`` (unset → None; set → echoes effort
string), ``SetDeploymentEffortUseCase`` (mutates the holder AND emits
exactly one ``effort.default.updated`` under the reserved deployment id),
``ClearDeploymentEffortUseCase`` (resets to None + emits
``effort.default.cleared``), and ``bootstrap_deployment_effort_config``
(last-write-wins replay from the reserved log; cleared after updated →
None; missing log → stays None).

Mirrors the deployment-model test shape (issue #55). Fakes come from
``tests/support`` (heuristic 3): ``FakeEventStore`` + ``RecordingEventBus``
drive the emitter; ``FakeSessionRepository`` provides the ``read_events`` /
``exists`` surface that ``bootstrap_deployment_effort_config`` reads.
"""

from __future__ import annotations

from mad.core.events.emitter import EventEmitter
from mad.core.orchestration.domain.effort_config import (
    DEPLOYMENT_EFFORT_SESSION_ID,
    DeploymentEffortConfig,
)
from mad.core.orchestration.use_cases.deployment_effort_config import (
    ClearDeploymentEffortUseCase,
    GetDeploymentEffortUseCase,
    SetDeploymentEffortInput,
    SetDeploymentEffortUseCase,
    bootstrap_deployment_effort_config,
)
from support.events import FakeEventStore, RecordingEventBus
from support.sessions import FakeSessionRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_set_use_case(
    config: DeploymentEffortConfig | None = None,
) -> tuple[SetDeploymentEffortUseCase, FakeEventStore]:
    cfg = config if config is not None else DeploymentEffortConfig()
    store = FakeEventStore()
    emitter = EventEmitter(store=store, bus=RecordingEventBus())
    return SetDeploymentEffortUseCase(config=cfg, emitter=emitter), store


def _make_clear_use_case(
    config: DeploymentEffortConfig | None = None,
) -> tuple[ClearDeploymentEffortUseCase, FakeEventStore]:
    cfg = config if config is not None else DeploymentEffortConfig()
    store = FakeEventStore()
    emitter = EventEmitter(store=store, bus=RecordingEventBus())
    return ClearDeploymentEffortUseCase(config=cfg, emitter=emitter), store


# ---------------------------------------------------------------------------
# GetDeploymentEffortUseCase
# ---------------------------------------------------------------------------


def test_get_returns_none_when_no_effort_configured() -> None:
    """With ``default_effort=None`` the GET reports None (caller omits the flag)."""
    use_case = GetDeploymentEffortUseCase(config=DeploymentEffortConfig())

    output = use_case.execute()

    assert output.effort is None


def test_get_returns_configured_effort_string() -> None:
    """Negative twin: a set holder echoes the effort string verbatim."""
    config = DeploymentEffortConfig(default_effort="high")
    use_case = GetDeploymentEffortUseCase(config=config)

    output = use_case.execute()

    assert output.effort == "high"


# ---------------------------------------------------------------------------
# SetDeploymentEffortUseCase
# ---------------------------------------------------------------------------


async def test_set_mutates_holder_and_emits_one_effort_default_updated_event() -> None:
    config = DeploymentEffortConfig()
    use_case, store = _make_set_use_case(config)

    output = await use_case.execute(SetDeploymentEffortInput(effort="high"))

    assert output.effort == "high"
    assert config.default_effort == "high"
    # Exactly one event of the right type under the reserved deployment id.
    effort_updates = [c for c in store.calls if c[1] == "effort.default.updated"]
    assert len(effort_updates) == 1
    session_id, _type, data = effort_updates[0]
    assert session_id == DEPLOYMENT_EFFORT_SESSION_ID
    assert data == {"effort": "high"}


async def test_set_does_not_emit_under_a_real_session_id() -> None:
    """Negative twin: the deployment effort default must land under the
    reserved id only — never attributed to a user session."""
    use_case, store = _make_set_use_case()

    await use_case.execute(SetDeploymentEffortInput(effort="low"))

    assert all(c[0] == DEPLOYMENT_EFFORT_SESSION_ID for c in store.calls)
    assert not any(c[0] == "sesn_a" for c in store.calls)


# ---------------------------------------------------------------------------
# ClearDeploymentEffortUseCase
# ---------------------------------------------------------------------------


async def test_clear_resets_to_none_and_emits_effort_default_cleared() -> None:
    config = DeploymentEffortConfig(default_effort="high")
    use_case, store = _make_clear_use_case(config)

    output = await use_case.execute()

    assert output.effort is None
    assert config.default_effort is None
    cleared = [c for c in store.calls if c[1] == "effort.default.cleared"]
    assert len(cleared) == 1
    session_id, _type, data = cleared[0]
    assert session_id == DEPLOYMENT_EFFORT_SESSION_ID
    assert data == {}


async def test_clear_already_none_is_idempotent_success() -> None:
    """Negative twin: clearing when already None still emits and returns None."""
    config = DeploymentEffortConfig(default_effort=None)
    use_case, store = _make_clear_use_case(config)

    output = await use_case.execute()

    assert output.effort is None
    cleared = [c for c in store.calls if c[1] == "effort.default.cleared"]
    assert len(cleared) == 1


# ---------------------------------------------------------------------------
# bootstrap_deployment_effort_config
# ---------------------------------------------------------------------------


def test_bootstrap_replays_last_updated_wins() -> None:
    """Two ``effort.default.updated`` events → the LAST one wins (hard rule 6)."""
    repo = FakeSessionRepository()
    repo.append_event(
        DEPLOYMENT_EFFORT_SESSION_ID,
        "effort.default.updated",
        {"effort": "high"},
    )
    repo.append_event(
        DEPLOYMENT_EFFORT_SESSION_ID,
        "effort.default.updated",
        {"effort": "low"},
    )
    config = DeploymentEffortConfig()

    bootstrap_deployment_effort_config(config, repo)

    assert config.default_effort == "low"


def test_bootstrap_cleared_after_updated_results_in_none() -> None:
    """Cleared wins over an earlier updated (last-write-wins)."""
    repo = FakeSessionRepository()
    repo.append_event(
        DEPLOYMENT_EFFORT_SESSION_ID,
        "effort.default.updated",
        {"effort": "high"},
    )
    repo.append_event(
        DEPLOYMENT_EFFORT_SESSION_ID,
        "effort.default.cleared",
        {},
    )
    config = DeploymentEffortConfig()

    bootstrap_deployment_effort_config(config, repo)

    assert config.default_effort is None


def test_bootstrap_missing_log_leaves_default_none() -> None:
    """Negative twin: no reserved log → default_effort stays None (no opinion)."""
    repo = FakeSessionRepository()
    config = DeploymentEffortConfig()

    bootstrap_deployment_effort_config(config, repo)

    assert config.default_effort is None


def test_bootstrap_ignores_unrelated_event_types() -> None:
    """Unrecognised event types in the log are silently skipped."""
    repo = FakeSessionRepository()
    repo.append_event(
        DEPLOYMENT_EFFORT_SESSION_ID,
        "session.created",
        {"irrelevant": "data"},
    )
    repo.append_event(
        DEPLOYMENT_EFFORT_SESSION_ID,
        "effort.default.updated",
        {"effort": "high"},
    )
    config = DeploymentEffortConfig()

    bootstrap_deployment_effort_config(config, repo)

    assert config.default_effort == "high"
