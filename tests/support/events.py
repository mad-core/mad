"""Test-only ``EventBus`` and ``EventLogQuery`` doubles.

Live under ``tests/`` per ADR-0003 — production code in ``src/`` does
not carry fakes. Use cases inject these to verify orchestration
without touching the real asyncio fanout or filesystem walk.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from mad.core.events.domain.event import Event
from mad.core.events.ports.event_bus import EventFilter
from mad.core.events.ports.event_log_query import EventQuery


class FakeEventBus:
    """Records every published event and supports a single async iterator
    subscription per filter. Pre-subscribe publishes are buffered and
    drained on subscribe — that lets test ordering not depend on
    whether the consumer task has been scheduled yet, which keeps
    use-case tests readable. The real asyncio-fanout adapter is
    exercised in ``tests/integration/adapters/events/``.
    """

    def __init__(self) -> None:
        self.published: list[Event] = []
        self._pending: list[Event] = []
        self._subscriber_queue: asyncio.Queue[Event | None] | None = None
        self._subscriber_filter: EventFilter | None = None

    async def publish(self, event: Event) -> None:
        self.published.append(event)
        if self._subscriber_queue is None or self._subscriber_filter is None:
            self._pending.append(event)
            return
        if _matches(event, self._subscriber_filter):
            await self._subscriber_queue.put(event)

    def subscribe(self, event_filter: EventFilter) -> AsyncIterator[Event]:
        queue: asyncio.Queue[Event | None] = asyncio.Queue()
        self._subscriber_queue = queue
        self._subscriber_filter = event_filter
        for event in self._pending:
            if _matches(event, event_filter):
                queue.put_nowait(event)
        self._pending.clear()
        return _drain(queue)

    async def close_subscriber(self) -> None:
        """Signal the active subscription to stop iterating."""
        if self._subscriber_queue is not None:
            await self._subscriber_queue.put(None)


async def _drain(queue: asyncio.Queue[Event | None]) -> AsyncIterator[Event]:
    while True:
        item = await queue.get()
        if item is None:
            return
        yield item


def _matches(event: Event, event_filter: EventFilter) -> bool:
    if (
        event_filter.session_id is not None
        and event.session_id != event_filter.session_id
    ):
        return False
    if event_filter.kind is not None and event.type != event_filter.kind:
        return False
    return not (
        event_filter.session_ids_for_agent is not None
        and event.session_id not in event_filter.session_ids_for_agent
    )


class FakeEventLogQuery:
    """In-memory ``EventLogQuery`` double. Tests script the available
    events and the agent → session_id resolution.
    """

    def __init__(
        self,
        events: list[Event] | None = None,
        agents_to_sessions: dict[str, frozenset[str]] | None = None,
    ) -> None:
        self.events: list[Event] = list(events) if events is not None else []
        self._agents_to_sessions = agents_to_sessions or {}
        self.queries: list[EventQuery] = []

    def query(self, q: EventQuery) -> list[Event]:
        self.queries.append(q)
        result = [e for e in self.events if _matches_query(e, q)]
        result.sort(key=_event_sort_key)
        return result[: q.limit]

    def session_ids_for_agent(self, agent_name: str) -> frozenset[str]:
        return self._agents_to_sessions.get(agent_name, frozenset())


def _matches_query(event: Event, q: EventQuery) -> bool:
    if q.session_id is not None and event.session_id != q.session_id:
        return False
    if q.kind is not None and event.type != q.kind:
        return False
    if (
        q.session_ids_for_agent is not None
        and event.session_id not in q.session_ids_for_agent
    ):
        return False
    if q.since is not None and event.timestamp < q.since:
        return False
    return not (
        q.after_event_id is not None
        and (event.event_id is None or event.event_id <= q.after_event_id)
    )


def _event_sort_key(event: Event) -> tuple[str, object]:
    eid_str = str(event.event_id) if event.event_id is not None else ""
    return (eid_str, event.timestamp)
