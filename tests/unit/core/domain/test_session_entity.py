"""Unit tests for the Session entity.

Validates state transitions and invariants.
No HTTP, no I/O — pure domain logic.
"""

from __future__ import annotations

import pytest

from mad.core.domain.entities.session import Session


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
