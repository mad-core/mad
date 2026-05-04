"""Unit tests for StreamSessionEventsUseCase.

Pure dict + asyncio.Queue lookup logic — no HTTP, no SSE machinery.
"""

from __future__ import annotations

import asyncio

import pytest

from mad.core.domain.entities.session import Session
from mad.core.domain.exceptions.base import SessionNotFound
from mad.core.use_cases.sessions.stream_session_events import (
    StreamSessionEventsUseCase,
)


def _make_session(session_id: str = "sesn_s") -> Session:
    return Session(
        session_id=session_id,
        agent={"name": "t", "provider": "fake"},
        workspace="/tmp/mad_" + session_id,
    )


def test_stream_unknown_session_raises():
    uc = StreamSessionEventsUseCase(sessions_index={}, sse_queues={})
    with pytest.raises(SessionNotFound):
        uc.execute("sesn_missing")


@pytest.mark.asyncio
async def test_stream_creates_queue_on_first_call():
    sessions = {"sesn_s": _make_session()}
    sse_queues: dict[str, asyncio.Queue] = {}
    uc = StreamSessionEventsUseCase(sessions_index=sessions, sse_queues=sse_queues)
    q = uc.execute("sesn_s")
    assert isinstance(q, asyncio.Queue)
    assert sse_queues["sesn_s"] is q


@pytest.mark.asyncio
async def test_stream_returns_existing_queue():
    sessions = {"sesn_s": _make_session()}
    existing = asyncio.Queue()
    sse_queues = {"sesn_s": existing}
    uc = StreamSessionEventsUseCase(sessions_index=sessions, sse_queues=sse_queues)
    q = uc.execute("sesn_s")
    assert q is existing
