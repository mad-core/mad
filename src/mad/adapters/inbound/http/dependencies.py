"""Composition root — builds default infrastructure dependencies.

``build_dependencies`` is called by ``create_app`` when callers do not
supply explicit overrides (the common production path). Tests pass
their own fakes via the ``create_app`` keyword arguments and never go
through this function.
"""

from __future__ import annotations

from mad.adapters.outbound.agents.model_catalog import ModelCatalogAdapter
from mad.adapters.outbound.events.in_memory_event_bus import InMemoryEventBus
from mad.adapters.outbound.events.jsonl_event_log_query import JsonlEventLogQuery
from mad.adapters.outbound.orchestration.projection import InMemoryTaskProjection
from mad.adapters.outbound.orchestration.system_clock import SystemClock
from mad.adapters.outbound.persistence.jsonl_session_repository import (
    JsonlSessionRepository,
)
from mad.adapters.outbound.persistence.local_workspace_provisioner import (
    LocalWorkspaceProvisioner,
)
from mad.core.events.domain.event import Event
from mad.core.events.emitter import EventEmitter
from mad.core.events.ports.event_bus import EventBus
from mad.core.events.ports.event_log_query import EventLogQuery
from mad.core.orchestration.domain.deployment_policy import DeploymentDispatchPolicy
from mad.core.orchestration.domain.model_config import DeploymentModelConfig
from mad.core.orchestration.ports.clock import Clock
from mad.core.orchestration.ports.model_catalog import ModelCatalog
from mad.core.sessions import SessionStore
from mad.core.sessions.ports.outbound.session_repository import SessionRepository
from mad.core.sessions.ports.outbound.workspace_provisioner import WorkspaceProvisioner


def build_dependencies() -> tuple[
    SessionStore,
    SessionRepository,
    WorkspaceProvisioner,
    EventBus,
    EventLogQuery,
    EventEmitter,
    InMemoryTaskProjection,
    Clock,
    DeploymentDispatchPolicy,
    ModelCatalog,
    DeploymentModelConfig,
]:
    """Return the production defaults for every injected port."""
    store = SessionStore()
    repo = JsonlSessionRepository()
    bus = InMemoryEventBus()
    emitter = EventEmitter(store=repo, bus=bus, on_emit=touch_session(store))
    projection = InMemoryTaskProjection()
    clock: Clock = SystemClock()
    deployment_policy = DeploymentDispatchPolicy()
    deployment_model_config = DeploymentModelConfig()
    return (
        store,
        repo,
        LocalWorkspaceProvisioner(),
        bus,
        JsonlEventLogQuery(),
        emitter,
        projection,
        clock,
        deployment_policy,
        ModelCatalogAdapter(),
        deployment_model_config,
    )


def touch_session(store: SessionStore):
    """Return an ``on_emit`` hook that bumps ``Session.updated_at`` for the
    in-memory entity matching ``event.session_id`` (if any), and captures
    the Claude CLI conversation ID from ``agent.claude_cli.hook.SessionStart``
    events.

    Sessions only present on disk (rehydrated lazily by use cases) derive
    their ``updated_at`` from the persisted event stream, not from this
    hook — so missing entries here are not a bug.

    The ``SessionStart`` hook fires ~1 s after the subprocess starts —
    before any tool runs and well before the 600 s timeout — so the
    conversation ID is available even for runs that time out before the
    ``result`` event reaches stdout.
    """

    def _on_emit(event: Event) -> None:
        session = store.sessions.get(event.session_id)
        if session is not None:
            session.touch(event.timestamp)
            if (
                event.type == "agent.claude_cli.hook.SessionStart"
                and event.data is not None
                and isinstance(event.data.get("session_id"), str)
            ):
                session.last_conversation_id = event.data["session_id"]

    return _on_emit
