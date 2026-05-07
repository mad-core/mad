"""EventEmitter — the single write gateway for the session event log.

Every event written to the log MUST go through ``emit()`` (CLAUDE.md
hard rule 11). Use cases receive an EventEmitter as an injected dependency
and never call EventStore.append or EventBus.publish directly.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mad.core.events.domain.event import Event
from mad.core.events.ports.event_bus import EventBus
from mad.core.events.ports.event_store import EventStore


class EventEmitter:
    """Persist an event then publish it to live subscribers.

    An optional ``on_emit`` hook is invoked synchronously after publish.
    The hook is the seam that lets the sessions module observe writes
    (e.g. to bump ``Session.updated_at``) without coupling this module
    to the sessions domain — keeping ADR-0004 intact.
    """

    def __init__(
        self,
        store: EventStore,
        bus: EventBus,
        on_emit: Callable[[Event], None] | None = None,
    ) -> None:
        self._store = store
        self._bus = bus
        self._on_emit = on_emit

    async def emit(
        self,
        session_id: str,
        type: str,
        data: dict[str, Any] | None = None,
    ) -> Event:
        event = self._store.append(session_id, type, data)
        await self._bus.publish(event)
        if self._on_emit is not None:
            self._on_emit(event)
        return event
