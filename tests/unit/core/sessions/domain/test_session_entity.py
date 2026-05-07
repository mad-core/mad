"""Unit tests for the Session entity.

Validates state transitions and invariants.
No HTTP, no I/O — pure domain logic.
"""

from __future__ import annotations

import pytest

from mad.core.sessions.domain.entities.session import Session


def _make_session(**kwargs) -> Session:
    defaults = dict(
        session_id="sesn_test001",
        agent={"name": "test", "provider": "fake"},
        workspace="/tmp/mad_sesn_test001",
    )
    defaults.update(kwargs)
    return Session(**defaults)


def test_initial_status_is_created():
    s = _make_session()
    assert s.status == "created"


def _apply_transition(s: Session, transition: str) -> None:
    s.mark_running()
    if transition == "idle":
        s.mark_idle()
    elif transition == "error":
        s.mark_error(reason="timeout")
    elif transition == "deleted":
        s.mark_deleted()


@pytest.mark.parametrize(
    "transition, expected_status",
    [
        ("running", "running"),
        ("idle", "idle"),
        ("error", "error"),
        ("deleted", "deleted"),
    ],
    ids=["running", "idle", "error", "deleted"],
)
def test_status_transitions(transition, expected_status):
    s = _make_session()
    _apply_transition(s, transition)
    assert s.status == expected_status


def test_to_dict_excludes_tokens():
    s = _make_session(tokens_to_redact=["ghp_secret"])
    d = s.to_dict()
    assert "tokens_to_redact" not in d
    raw = str(d)
    assert "ghp_secret" not in raw


def test_from_dict_round_trip():
    s = _make_session(status="idle")
    d = s.to_dict()
    s2 = Session.from_dict(d)
    assert s2.session_id == s.session_id
    assert s2.status == "idle"
    assert s2.workspace == s.workspace


def test_base_branch_persisted_through_round_trip():
    s = _make_session(base_branch="develop")
    d = s.to_dict()
    assert d["base_branch"] == "develop"
    s2 = Session.from_dict(d)
    assert s2.base_branch == "develop"


def test_base_branch_defaults_to_none():
    s = _make_session()
    assert s.base_branch is None
    assert s.to_dict()["base_branch"] is None


# ---------------------------------------------------------------------------
# Timestamps (issue #17)
# ---------------------------------------------------------------------------


def test_default_created_at_and_updated_at_are_aware_utc():
    """Timestamps default to a tz-aware UTC ``datetime`` so downstream
    comparisons (filters, rehydration) never mix naive and aware.
    """
    from datetime import UTC

    s = _make_session()
    assert s.created_at.tzinfo is not None
    assert s.created_at.utcoffset() == UTC.utcoffset(s.created_at)
    assert s.updated_at == s.created_at


def test_touch_advances_updated_at_only_forward():
    """``touch`` is monotonic — replaying a stale event must not pull the
    timestamp backwards (rehydration may feed older events into a live
    entity).
    """
    from datetime import UTC, datetime, timedelta

    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    s = _make_session(created_at=base, updated_at=base)

    s.touch(base + timedelta(minutes=5))
    assert s.updated_at == base + timedelta(minutes=5)

    s.touch(base + timedelta(minutes=1))
    assert s.updated_at == base + timedelta(minutes=5)


def test_to_dict_round_trip_preserves_timestamps():
    """``to_dict`` / ``from_dict`` must round-trip both timestamps as
    ISO-8601 — JSONL persistence relies on this.
    """
    from datetime import UTC, datetime

    created = datetime(2026, 5, 6, 9, 0, tzinfo=UTC)
    updated = datetime(2026, 5, 6, 9, 30, tzinfo=UTC)
    s = _make_session(created_at=created, updated_at=updated)

    d = s.to_dict()
    assert d["created_at"] == "2026-05-06T09:00:00+00:00"
    assert d["updated_at"] == "2026-05-06T09:30:00+00:00"

    s2 = Session.from_dict(d)
    assert s2.created_at == created
    assert s2.updated_at == updated
