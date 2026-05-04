"""Unit tests for SendUserMessageUseCase.

Tests the synchronous validation path. The async launcher run is tested
via integration tests.
"""

from __future__ import annotations

import asyncio

import pytest

from mad.core.domain.entities.session import Session
from mad.core.domain.exceptions.base import SessionNotFound
from mad.core.use_cases.sessions.send_user_message import (
    SendUserMessageInput,
    SendUserMessageUseCase,
    _redact_tokens,
)


class FakeRepo:
    def __init__(self):
        self.events: list[dict] = []

    def append_event(self, session_id, event_type, data=None):
        event = {"type": event_type, **(data or {})}
        self.events.append(event)
        return event

    def read_events(self, session_id):
        return self.events

    def exists(self, session_id):
        return True


def _make_session(session_id="sesn_msg", tokens=None):
    return Session(
        session_id=session_id,
        agent={"name": "t", "provider": "fake"},
        workspace="/tmp/mad_sesn_msg",
        tokens_to_redact=tokens or [],
    )


def test_send_message_session_not_found():
    sessions: dict = {}
    uc = SendUserMessageUseCase(
        repo=FakeRepo(),
        sessions_index=sessions,
        sse_queues={},
        get_launcher=lambda name: None,
    )
    with pytest.raises(SessionNotFound):
        uc.execute(SendUserMessageInput(session_id="sesn_missing", content="hi"))


async def test_send_message_runs_launcher_and_redacts_tokens():
    """Background task drives the full lifecycle: status_running →
    forward emitted events through redaction → status_idle on success.
    """
    repo = FakeRepo()
    token = "ghp_secretXYZ"
    sessions = {"sesn_msg": _make_session(tokens=[token])}
    sse_queue: asyncio.Queue = asyncio.Queue()
    sse_queues = {"sesn_msg": sse_queue}

    class ScriptedLauncher:
        async def run(self, prompt, workspace, emit):
            await emit("agent.output", {"line": f"leak {token} bye"})
            await emit("session.status_idle", {"stop_reason": "end_turn"})

    uc = SendUserMessageUseCase(
        repo=repo,
        sessions_index=sessions,
        sse_queues=sse_queues,
        get_launcher=lambda name: ScriptedLauncher(),
    )

    uc.execute(SendUserMessageInput(session_id="sesn_msg", content="hello"))
    while True:
        event = await asyncio.wait_for(sse_queue.get(), timeout=1.0)
        if event is None:
            break

    types = [e["type"] for e in repo.events]
    assert types == [
        "user.message",
        "session.status_running",
        "agent.output",
        "session.status_idle",
    ]
    assert sessions["sesn_msg"].status == "idle"
    output_event = next(e for e in repo.events if e["type"] == "agent.output")
    assert token not in output_event["line"]
    assert "[REDACTED]" in output_event["line"]


async def test_send_message_records_session_error_when_launcher_raises():
    repo = FakeRepo()
    sessions = {"sesn_msg": _make_session()}
    sse_queue: asyncio.Queue = asyncio.Queue()
    sse_queues = {"sesn_msg": sse_queue}

    class BoomLauncher:
        async def run(self, prompt, workspace, emit):
            raise RuntimeError("kaboom")

    uc = SendUserMessageUseCase(
        repo=repo,
        sessions_index=sessions,
        sse_queues=sse_queues,
        get_launcher=lambda name: BoomLauncher(),
    )

    uc.execute(SendUserMessageInput(session_id="sesn_msg", content="hi"))
    while True:
        event = await asyncio.wait_for(sse_queue.get(), timeout=1.0)
        if event is None:
            break

    types = [e["type"] for e in repo.events]
    assert "session.error" in types
    assert sessions["sesn_msg"].status == "error"


@pytest.mark.parametrize(
    "data, tokens, check",
    [
        (
            {"line": "output containing ghp_secret and more"},
            ["ghp_secret"],
            lambda r: "ghp_secret" not in r["line"] and "[REDACTED]" in r["line"],
        ),
        (
            {"count": 42, "flag": True},
            ["ghp_secret"],
            lambda r: r["count"] == 42 and r["flag"] is True,
        ),
        (
            {"line": "nothing to redact"},
            [],
            lambda r: r == {"line": "nothing to redact"},
        ),
    ],
    ids=["string-redacted", "non-string-unchanged", "empty-tokens-unchanged"],
)
def test_redact_tokens(data, tokens, check):
    result = _redact_tokens(data, tokens)
    assert check(result)
