"""SendUserMessage use case.

Handles user.message events, launching the agent for each message.
Implements token redaction in agent.output events (CLAUDE.md hard rule 2).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Coroutine

from mad.core.domain.entities.session import Session
from mad.core.domain.exceptions.base import SessionNotFound
from mad.core.ports.outbound.session_repository import SessionRepository
from mad.core.use_cases.sessions.auto_sync_prompt import build_auto_sync_prompt


@dataclass
class SendUserMessageInput:
    session_id: str
    content: str


class SendUserMessageUseCase:
    """Accept a user message and dispatch the agent launcher as a background task.

    Token redaction: collects all authorization_tokens from the session's
    resources_mounted and replaces any occurrence in emitted event data with
    [REDACTED] before persisting to the JSONL log.
    """

    def __init__(
        self,
        repo: SessionRepository,
        sessions_index: dict[str, Session],
        sse_queues: dict[str, asyncio.Queue[Any]],
        get_launcher: Callable[[str], Any],
    ) -> None:
        self._repo = repo
        self._sessions = sessions_index
        self._sse_queues = sse_queues
        self._get_launcher = get_launcher

    def execute(self, payload: SendUserMessageInput) -> None:
        """Validate and schedule the agent run. Returns immediately."""
        if payload.session_id not in self._sessions:
            raise SessionNotFound(payload.session_id)
        session = self._sessions[payload.session_id]
        self._repo.append_event(payload.session_id, "user.message", {"content": payload.content})
        asyncio.create_task(
            _run_launcher(
                repo=self._repo,
                session=session,
                session_id=payload.session_id,
                prompt=payload.content,
                sse_queues=self._sse_queues,
                get_launcher=self._get_launcher,
            )
        )


async def _run_launcher(
    repo: SessionRepository,
    session: Session,
    session_id: str,
    prompt: str,
    sse_queues: dict[str, asyncio.Queue[Any]],
    get_launcher: Callable[[str], Any],
) -> None:
    """Internal coroutine: run the launcher and handle lifecycle events."""
    _emit_and_push(repo, session, session_id, sse_queues, "session.status_running")
    session.mark_running()

    # Collect tokens to redact from this session's resources
    tokens_to_redact = _collect_tokens(session)

    launcher = get_launcher(session.agent["provider"])
    workspace = Path(session.workspace)

    async def emit(event_type: str, data: dict[str, Any] | None = None) -> None:
        redacted_data = _redact_tokens(data, tokens_to_redact) if data and tokens_to_redact else data
        _emit_and_push(repo, session, session_id, sse_queues, event_type, redacted_data)
        if event_type == "session.status_idle":
            session.mark_idle()
        elif event_type == "session.error":
            session.mark_error()

    try:
        await launcher.run(prompt=prompt, workspace=workspace, emit=emit)
    except Exception as exc:
        if session.status == "running":
            _emit_and_push(repo, session, session_id, sse_queues, "session.error", {"error": str(exc)})
            session.mark_error()

    # Post-run auto-sync (issue #8): always launch a second agent run in the
    # same workspace with a fixed instruction prompt that decides whether to
    # branch / commit / push / open a PR. Mad does not interpret the run's
    # output (hard rule 1); events are emitted as agent.output like any other
    # run. Failures here MUST NOT crash the session task — they are surfaced
    # as a session.error event.
    try:
        auto_sync_prompt = build_auto_sync_prompt(session_id, session.base_branch)
        await launcher.run(prompt=auto_sync_prompt, workspace=workspace, emit=emit)
    except Exception as exc:
        _emit_and_push(
            repo,
            session,
            session_id,
            sse_queues,
            "session.error",
            {"error": f"auto-sync failed: {exc}"},
        )
        session.mark_error()
    finally:
        q = sse_queues.get(session_id)
        if q is not None:
            await q.put(None)


def _emit_and_push(
    repo: SessionRepository,
    session: Session,
    session_id: str,
    sse_queues: dict[str, asyncio.Queue[Any]],
    event_type: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append event to log and push to SSE queue."""
    event = repo.append_event(session_id, event_type, data)
    q = sse_queues.get(session_id)
    if q is not None:
        q.put_nowait(event)
    return event


def _collect_tokens(session: Session) -> list[str]:
    """Collect all authorization tokens from session (for redaction).

    Tokens are stored in session.tokens_to_redact at creation time and
    are NEVER persisted to the JSONL log.
    """
    return [t for t in session.tokens_to_redact if t]


def _redact_tokens(data: dict[str, Any], tokens: list[str]) -> dict[str, Any]:
    """Replace token literals in all string values of data dict with [REDACTED]."""
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
