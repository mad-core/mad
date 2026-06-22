"""Unit tests for effort field rehydration (issue #60).

A ``session.created`` event with an ``effort`` key must yield a
``Session`` with the correct ``effort`` attribute. Missing key → ``None``.
Mirrors ``test_rehydrate_model`` — effort is the parallel field.
"""

from __future__ import annotations

from mad.core.sessions.domain.rehydrate import rehydrate_from_events


def test_rehydrate_sets_effort_from_session_created_event() -> None:
    """A ``session.created`` event carrying ``effort`` must populate
    ``Session.effort`` with that value (positive path)."""
    events = [
        {
            "type": "session.created",
            "timestamp": "2026-06-01T12:00:00+00:00",
            "agent": "t",
            "working_directory": "/workspace",
            "effort": "high",
        }
    ]
    session = rehydrate_from_events("sesn_e", events)

    assert session.effort == "high"


def test_rehydrate_effort_is_none_when_key_absent() -> None:
    """Negative twin: no ``effort`` key in ``session.created`` →
    ``Session.effort is None`` (legacy logs predate the field)."""
    events = [
        {
            "type": "session.created",
            "timestamp": "2026-06-01T12:00:00+00:00",
            "agent": "t",
            "working_directory": "/workspace",
        }
    ]
    session = rehydrate_from_events("sesn_n", events)

    assert session.effort is None
