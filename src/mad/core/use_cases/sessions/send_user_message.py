"""SendUserMessage use case.

Handles ``user.message`` events, launching the agent for each message.
Implements token redaction in ``agent.output`` events (CLAUDE.md
hard rule 2).

Every event the use case appends to the repository is also published
to the injected ``EventBus`` so the cross-session observability surface
(issue #10) sees a live copy of every state change.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mad.core.domain.entities.session import Session
from mad.core.domain.exceptions.base import SessionNotFound
from mad.core.events.domain.event import event_from_persisted
from mad.core.events.ports.event_bus import EventBus
from mad.core.ports.outbound.session_repository import SessionRepository
from mad.core.use_cases.sessions.auto_sync_prompt import build_auto_sync_prompt


@dataclass
class SendUserMessageInput:
    session_id: str
    content: str


class SendUserMessageUseCase:
    """Accept a user message and dispatch the agent launcher as a
    background task.

    Token redaction: collects all ``authorization_token`` values from
    the session's ``resources_mounted`` and replaces any occurrence in
    emitted event data with ``[REDACTED]`` before persisting to the
    JSONL log.
    """

    def __init__(
        self,
        repo: SessionRepository,
        sessions_index: dict[str, Session],
        get_launcher: Callable[[str], Any],
        event_bus: EventBus,
    ) -> None:
        self._repo = repo
        self._sessions = sessions_index
        self._get_launcher = get_launcher
        self._event_bus = event_bus

    def execute(self, payload: SendUserMessageInput) -> None:
        """Validate and schedule the agent run. Returns immediately."""
        if payload.session_id not in self._sessions:
            raise SessionNotFound(payload.session_id)
        session = self._sessions[payload.session_id]
        event_dict = self._repo.append_event(
            payload.session_id, "user.message", {"content": payload.content}
        )
        # Fire-and-forget publish: execute() is sync but FastAPI's event
        # loop is running, so create_task is safe.
        asyncio.create_task(
            self._event_bus.publish(
                event_from_persisted(event_dict, payload.session_id)
            )
        )
        asyncio.create_task(
            _run_launcher(
                repo=self._repo,
                session=session,
                session_id=payload.session_id,
                prompt=payload.content,
                get_launcher=self._get_launcher,
                event_bus=self._event_bus,
            )
        )


async def _run_launcher(
    repo: SessionRepository,
    session: Session,
    session_id: str,
    prompt: str,
    get_launcher: Callable[[str], Any],
    event_bus: EventBus,
) -> None:
    """Internal coroutine: run the launcher and handle lifecycle events."""
    await _emit(repo, session, session_id, event_bus, "session.status_running")
    session.mark_running()

    tokens_to_redact = _collect_tokens(session)

    launcher = get_launcher(session.agent["provider"])
    workspace = Path(session.workspace)

    async def emit(event_type: str, data: dict[str, Any] | None = None) -> None:
        redacted_data = (
            _redact_tokens(data, tokens_to_redact)
            if data and tokens_to_redact
            else data
        )
        await _emit(repo, session, session_id, event_bus, event_type, redacted_data)
        if event_type == "session.status_idle":
            session.mark_idle()
        elif event_type == "session.error":
            session.mark_error()

    try:
        await launcher.run(prompt=prompt, workspace=workspace, emit=emit)
    except Exception as exc:
        if session.status == "running":
            await _emit(
                repo,
                session,
                session_id,
                event_bus,
                "session.error",
                {"error": str(exc)},
            )
            session.mark_error()

    # Post-run auto-sync (issue #8): always launch a second agent run in
    # the same workspace with a fixed instruction prompt that decides
    # whether to branch / commit / push / open a PR. Mad does not
    # interpret the run's output (hard rule 1); events are emitted as
    # agent.output like any other run. Failures here MUST NOT crash the
    # session task — they are surfaced as a session.error event.
    try:
        auto_sync_prompt = build_auto_sync_prompt(session_id, session.base_branch)
        await launcher.run(prompt=auto_sync_prompt, workspace=workspace, emit=emit)
    except Exception as exc:
        await _emit(
            repo,
            session,
            session_id,
            event_bus,
            "session.error",
            {"error": f"auto-sync failed: {exc}"},
        )
        session.mark_error()


async def _emit(
    repo: SessionRepository,
    session: Session,
    session_id: str,
    event_bus: EventBus,
    event_type: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append event to log and publish to the event bus."""
    event_dict = repo.append_event(session_id, event_type, data)
    await event_bus.publish(event_from_persisted(event_dict, session_id))
    return event_dict


def _collect_tokens(session: Session) -> list[str]:
    """Collect all authorization tokens from session (for redaction).

    Tokens are stored in ``session.tokens_to_redact`` at creation time
    and are NEVER persisted to the JSONL log.
    """
    return [t for t in session.tokens_to_redact if t]


def _redact_tokens(data: dict[str, Any], tokens: list[str]) -> dict[str, Any]:
    """Replace token literals in all string values of ``data`` with ``[REDACTED]``."""
    if not tokens:
        return data
    result = {}
    for k, v in data.items():
        if isinstance(v, str):
            for token in tokens:
                if token:
                    v = v.replace(token, "[REDACTED]")
        result[k] = v
    return result
