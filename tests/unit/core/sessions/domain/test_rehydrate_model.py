"""Unit tests for model field rehydration (issue #55).

A ``session.created`` event with a ``model`` key must yield a
``Session`` with the correct ``model`` attribute. Missing key → ``None``.
"""

from __future__ import annotations

from mad.core.sessions.domain.rehydrate import rehydrate_from_events


def test_rehydrate_sets_model_from_session_created_event() -> None:
    """A ``session.created`` event carrying ``model`` must populate
    ``Session.model`` with that value (positive path)."""
    events = [
        {
            "type": "session.created",
            "timestamp": "2026-06-01T12:00:00+00:00",
            "agent": "t",
            "working_directory": "/workspace",
            "model": "opus",
        }
    ]
    session = rehydrate_from_events("sesn_m", events)

    assert session.model == "opus"


def test_rehydrate_model_is_none_when_key_absent() -> None:
    """Negative twin: no ``model`` key in ``session.created`` → ``Session.model is None``."""
    events = [
        {
            "type": "session.created",
            "timestamp": "2026-06-01T12:00:00+00:00",
            "agent": "t",
            "working_directory": "/workspace",
        }
    ]
    session = rehydrate_from_events("sesn_n", events)

    assert session.model is None
