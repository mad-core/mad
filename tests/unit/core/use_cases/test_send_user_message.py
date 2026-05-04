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
from support.events import FakeEventBus


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
        event_bus=FakeEventBus(),
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
        event_bus=FakeEventBus(),
    )

    uc.execute(SendUserMessageInput(session_id="sesn_msg", content="hello"))
    while True:
        event = await asyncio.wait_for(sse_queue.get(), timeout=1.0)
        if event is None:
            break

    types = [e["type"] for e in repo.events]
    # Primary run + post-run auto-sync run (issue #8): the launcher is invoked
    # twice, so two status_idle events are emitted.
    assert types == [
        "user.message",
        "session.status_running",
        "agent.output",
        "session.status_idle",
        "agent.output",
        "session.status_idle",
    ]
    assert sessions["sesn_msg"].status == "idle"
    output_events = [e for e in repo.events if e["type"] == "agent.output"]
    for output_event in output_events:
        assert token not in output_event["line"]
        assert "[REDACTED]" in output_event["line"]


async def test_post_run_auto_sync_invokes_second_launcher_run():
    """After the primary run, send_user_message must invoke the launcher a
    second time with the auto-sync instruction prompt (issue #8).
    """
    repo = FakeRepo()
    sessions = {"sesn_msg": _make_session()}
    sessions["sesn_msg"].base_branch = "develop"
    sse_queue: asyncio.Queue = asyncio.Queue()
    sse_queues = {"sesn_msg": sse_queue}

    calls: list[str] = []

    class RecordingLauncher:
        async def run(self, prompt, workspace, emit):
            calls.append(prompt)
            await emit("session.status_idle", {"stop_reason": "end_turn"})

    uc = SendUserMessageUseCase(
        repo=repo,
        sessions_index=sessions,
        sse_queues=sse_queues,
        get_launcher=lambda name: RecordingLauncher(),
        event_bus=FakeEventBus(),
    )

    uc.execute(SendUserMessageInput(session_id="sesn_msg", content="hello"))
    while True:
        event = await asyncio.wait_for(sse_queue.get(), timeout=1.0)
        if event is None:
            break

    assert len(calls) == 2
    assert calls[0] == "hello"
    assert "auto-sync" in calls[1].lower()
    assert "develop" in calls[1]
    assert ".claude/settings.local.json" in calls[1]
    assert ".claude/settings.json" in calls[1]


async def test_post_run_auto_sync_runs_even_when_primary_fails():
    """Auto-sync must run even when the primary launcher raises (issue #8)."""
    repo = FakeRepo()
    sessions = {"sesn_msg": _make_session()}
    sse_queue: asyncio.Queue = asyncio.Queue()
    sse_queues = {"sesn_msg": sse_queue}

    calls: list[str] = []

    class FlakyLauncher:
        async def run(self, prompt, workspace, emit):
            calls.append(prompt)
            if len(calls) == 1:
                raise RuntimeError("primary boom")
            await emit("session.status_idle", {"stop_reason": "end_turn"})

    uc = SendUserMessageUseCase(
        repo=repo,
        sessions_index=sessions,
        sse_queues=sse_queues,
        get_launcher=lambda name: FlakyLauncher(),
        event_bus=FakeEventBus(),
    )

    uc.execute(SendUserMessageInput(session_id="sesn_msg", content="hi"))
    while True:
        event = await asyncio.wait_for(sse_queue.get(), timeout=1.0)
        if event is None:
            break

    assert len(calls) == 2, "second (auto-sync) run must fire even after primary failure"


async def test_post_run_auto_sync_failure_emits_session_error():
    """If the auto-sync run itself raises, surface it as session.error (issue #8)."""
    repo = FakeRepo()
    sessions = {"sesn_msg": _make_session()}
    sse_queue: asyncio.Queue = asyncio.Queue()
    sse_queues = {"sesn_msg": sse_queue}

    calls: list[int] = []

    class AutoSyncBoom:
        async def run(self, prompt, workspace, emit):
            calls.append(1)
            if len(calls) == 1:
                await emit("session.status_idle", {"stop_reason": "end_turn"})
                return
            raise RuntimeError("sync boom")

    uc = SendUserMessageUseCase(
        repo=repo,
        sessions_index=sessions,
        sse_queues=sse_queues,
        get_launcher=lambda name: AutoSyncBoom(),
        event_bus=FakeEventBus(),
    )

    uc.execute(SendUserMessageInput(session_id="sesn_msg", content="hi"))
    while True:
        event = await asyncio.wait_for(sse_queue.get(), timeout=1.0)
        if event is None:
            break

    error_events = [e for e in repo.events if e["type"] == "session.error"]
    assert any("auto-sync failed" in e.get("error", "") for e in error_events)
    assert sessions["sesn_msg"].status == "error"


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
        event_bus=FakeEventBus(),
    )

    uc.execute(SendUserMessageInput(session_id="sesn_msg", content="hi"))
    while True:
        event = await asyncio.wait_for(sse_queue.get(), timeout=1.0)
        if event is None:
            break

    types = [e["type"] for e in repo.events]
    assert "session.error" in types
    assert sessions["sesn_msg"].status == "error"


async def test_publishes_every_appended_event_to_the_event_bus():
    """Issue #10 acceptance: SendUserMessage publishes to the injected
    EventBus for every event it appends to the repository — the
    ``user.message`` it appends synchronously and every lifecycle event
    emitted during the launcher run."""
    repo = FakeRepo()
    sessions = {"sesn_msg": _make_session()}
    sse_queue: asyncio.Queue = asyncio.Queue()
    sse_queues = {"sesn_msg": sse_queue}
    bus = FakeEventBus()

    class ScriptedLauncher:
        async def run(self, prompt, workspace, emit):
            await emit("agent.output", {"line": "hi"})
            await emit("session.status_idle", {"stop_reason": "end_turn"})

    uc = SendUserMessageUseCase(
        repo=repo,
        sessions_index=sessions,
        sse_queues=sse_queues,
        get_launcher=lambda name: ScriptedLauncher(),
        event_bus=bus,
    )

    uc.execute(SendUserMessageInput(session_id="sesn_msg", content="please"))
    while True:
        event = await asyncio.wait_for(sse_queue.get(), timeout=1.0)
        if event is None:
            break

    repo_types = [e["type"] for e in repo.events]
    bus_types = [e.type for e in bus.published]
    # Every event appended to the repo must also appear on the bus, in
    # the same order. Auto-sync (issue #8) fires a second launcher run,
    # so the launcher emits `agent.output` and `session.status_idle`
    # twice in a row — both are persisted and published.
    assert repo_types == bus_types
    assert all(e.session_id == "sesn_msg" for e in bus.published)


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
