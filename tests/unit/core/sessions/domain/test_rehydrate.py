"""Unit tests for ``rehydrate_from_events``.

The rehydration helper drives both ``GetSessionUseCase`` (when a session
is missing from memory) and ``ListSessionsUseCase`` (when listings span
restarts). Issue #17 added timestamps — this file pins the contract.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mad.core.sessions.domain.rehydrate import rehydrate_from_events


def test_rehydrate_uses_session_created_event_for_created_at() -> None:
    """``created_at`` is taken from the ``session.created`` event, not the
    earliest event in the log — out-of-order writes of ancestor events
    must not corrupt the timestamp.
    """
    events = [
        {
            "type": "session.created",
            "timestamp": "2026-05-06T09:00:00+00:00",
            "agent": "t",
        },
        {
            "type": "session.status_running",
            "timestamp": "2026-05-06T09:05:00+00:00",
        },
    ]
    s = rehydrate_from_events("sesn_x", events)

    assert s.created_at == datetime(2026, 5, 6, 9, 0, tzinfo=UTC)


def test_rehydrate_updated_at_is_latest_event_timestamp() -> None:
    """``updated_at`` is the maximum event timestamp — that's how filters
    on ``updated_after`` find sessions whose last activity is recent.
    """
    events = [
        {
            "type": "session.created",
            "timestamp": "2026-05-06T09:00:00+00:00",
            "agent": "t",
        },
        {
            "type": "agent.output",
            "timestamp": "2026-05-06T09:30:00+00:00",
        },
        {
            "type": "session.status_idle",
            "timestamp": "2026-05-06T10:00:00+00:00",
        },
    ]
    s = rehydrate_from_events("sesn_x", events)

    assert s.updated_at == datetime(2026, 5, 6, 10, 0, tzinfo=UTC)
    assert s.status == "idle"


def test_rehydrate_skips_unparseable_timestamps_but_preserves_status() -> None:
    """A bad timestamp on one event must not crash rehydration nor pull
    ``updated_at`` to the wrong value; the well-formed events still drive
    the timestamp and status.
    """
    events = [
        {
            "type": "session.created",
            "timestamp": "2026-05-06T09:00:00+00:00",
            "agent": "t",
        },
        {"type": "agent.output", "timestamp": "not-a-real-timestamp"},
        {
            "type": "session.status_idle",
            "timestamp": "2026-05-06T09:30:00+00:00",
        },
    ]
    s = rehydrate_from_events("sesn_x", events)

    assert s.status == "idle"
    assert s.created_at == datetime(2026, 5, 6, 9, 0, tzinfo=UTC)
    assert s.updated_at == datetime(2026, 5, 6, 9, 30, tzinfo=UTC)


def test_rehydrate_empty_events_yields_epoch_timestamps() -> None:
    """An empty event log should not crash; both timestamps fall back to
    the Unix epoch in UTC so they sort first in any listing.
    """
    s = rehydrate_from_events("sesn_x", [])

    assert s.created_at == datetime.fromtimestamp(0, tz=UTC)
    assert s.updated_at == s.created_at
    assert s.status == "created"
