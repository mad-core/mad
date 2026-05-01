"""Unit tests for SessionStore — the per-process in-memory index.

Pure dict + asyncio.Queue container, so a single happy-path test is enough.
"""

from __future__ import annotations

import asyncio

import pytest

from mad.core.sessions import SessionStore


def test_session_store_starts_empty():
    store = SessionStore()
    assert store.sessions == {}
    assert store.idempotency == {}
    assert store.sse_queues == {}


@pytest.mark.asyncio
async def test_get_or_create_queue_creates_once_then_returns_same():
    store = SessionStore()
    q1 = store.get_or_create_queue("sesn_a")
    q2 = store.get_or_create_queue("sesn_a")
    assert q1 is q2
    assert isinstance(q1, asyncio.Queue)


@pytest.mark.asyncio
async def test_push_event_enqueues_when_queue_exists():
    store = SessionStore()
    q = store.get_or_create_queue("sesn_a")
    store.push_event("sesn_a", {"type": "agent.output"})
    event = await asyncio.wait_for(q.get(), timeout=0.1)
    assert event == {"type": "agent.output"}


def test_push_event_is_noop_when_queue_missing():
    store = SessionStore()
    # Must not raise
    store.push_event("sesn_unknown", {"type": "anything"})
