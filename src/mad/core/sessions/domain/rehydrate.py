"""Rehydrate a Session entity from its persisted JSONL events.

Pure domain helper — no I/O, no port dependencies. Callers read the
events from a SessionRepository and pass them in. Used by GetSession
and ListSessions to recover sessions that are not in the in-memory
index (hard rule 6: JSONL is the source of truth).
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from mad.core.sessions.domain.entities.session import Session


def rehydrate_from_events(session_id: str, events: list[dict[str, Any]]) -> Session:
    """Build a minimal Session entity from its persisted event stream.

    ``created_at`` is the timestamp of the ``session.created`` event (or the
    earliest event if none is present); ``updated_at`` is the timestamp of
    the latest event. Events without a parseable timestamp are skipped for
    the timestamp computation but still drive the status transitions.
    """
    agent: dict[str, Any] = {}
    workspace = ""
    status = "created"
    created_at: datetime | None = None
    latest_at: datetime | None = None

    for event in events:
        etype = event.get("type", "")
        if etype == "session.created":
            agent = {"name": event.get("agent", ""), "provider": "unknown"}
        elif etype == "session.status_running":
            status = "running"
        elif etype == "session.status_idle":
            status = "idle"
        elif etype == "session.error":
            status = "error"
        elif etype == "session.deleted":
            status = "deleted"

        ts = _parse_timestamp(event.get("timestamp"))
        if ts is None:
            continue
        if etype == "session.created" and created_at is None:
            created_at = ts
        if latest_at is None or ts > latest_at:
            latest_at = ts

    if created_at is None and latest_at is not None:
        created_at = latest_at
    if created_at is None:
        created_at = datetime.fromtimestamp(0, tz=UTC)
    if latest_at is None:
        latest_at = created_at

    return Session(
        session_id=session_id,
        agent=agent,
        workspace=workspace,
        status=status,
        created_at=created_at,
        updated_at=latest_at,
    )


def _parse_timestamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts
