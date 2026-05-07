"""Unit tests for ListSessionsUseCase."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mad.core.sessions.domain.entities.session import Session
from mad.core.sessions.use_cases.list_sessions import (
    ListSessionsInput,
    ListSessionsUseCase,
)
from support.sessions import FakeSessionRepository


_T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _make_session(
    session_id,
    status="created",
    *,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
):
    created = created_at or _T0
    updated = updated_at or created
    return Session(
        session_id=session_id,
        agent={"name": "t", "provider": "fake"},
        workspace="/tmp/mad_" + session_id,
        status=status,
        created_at=created,
        updated_at=updated,
    )


@pytest.fixture
def repo() -> FakeSessionRepository:
    return FakeSessionRepository()


def test_list_sessions_returns_all_in_memory(repo: FakeSessionRepository) -> None:
    sessions = {
        "sesn_001": _make_session("sesn_001", "created"),
        "sesn_002": _make_session("sesn_002", "idle"),
    }
    uc = ListSessionsUseCase(sessions_index=sessions, repo=repo)
    result = uc.execute().sessions
    by_id = {s.session_id: s for s in result}
    assert by_id["sesn_001"].status == "created"
    assert by_id["sesn_002"].status == "idle"
    assert len(result) == 2


def test_list_sessions_includes_persisted_sessions_not_in_memory(
    repo: FakeSessionRepository,
) -> None:
    """Sessions persisted to JSONL but absent from the in-memory index
    must still appear — otherwise restarting the server drops them from
    /v1/sessions even though their event logs survive (hard rule 6).
    """
    repo.append_event("sesn_disk_1", "session.created", {"agent": "t"})
    repo.append_event("sesn_disk_1", "session.status_idle")
    repo.append_event("sesn_disk_2", "session.created", {"agent": "t"})

    uc = ListSessionsUseCase(sessions_index={}, repo=repo)
    result = uc.execute().sessions

    by_id = {s.session_id: s for s in result}
    assert by_id["sesn_disk_1"].status == "idle"
    assert by_id["sesn_disk_2"].status == "created"
    assert len(result) == 2


def test_list_sessions_in_memory_status_wins_over_disk(
    repo: FakeSessionRepository,
) -> None:
    """If a session is both live and persisted, the live status is the
    source of truth — the in-memory entity reflects state transitions
    that may not yet have been written when the listing is served.
    """
    repo.append_event("sesn_001", "session.created", {"agent": "t"})
    sessions = {"sesn_001": _make_session("sesn_001", "running")}

    uc = ListSessionsUseCase(sessions_index=sessions, repo=repo)
    result = uc.execute().sessions

    assert len(result) == 1
    assert result[0].status == "running"


def test_list_sessions_is_empty_when_no_sources(repo: FakeSessionRepository) -> None:
    uc = ListSessionsUseCase(sessions_index={}, repo=repo)
    assert uc.execute().sessions == []


# ---------------------------------------------------------------------------
# Filters and ordering (issue #17)
# ---------------------------------------------------------------------------


def test_list_sessions_summary_carries_timestamps(repo: FakeSessionRepository) -> None:
    """Each summary must surface created_at and updated_at — clients use
    them for prune / staleness logic and the HTTP response declares them.
    """
    created = _T0
    updated = _T0 + timedelta(minutes=5)
    sessions = {
        "sesn_001": _make_session(
            "sesn_001", "idle", created_at=created, updated_at=updated
        ),
    }
    uc = ListSessionsUseCase(sessions_index=sessions, repo=repo)
    result = uc.execute().sessions
    assert len(result) == 1
    assert result[0].created_at == created
    assert result[0].updated_at == updated


def test_list_sessions_filters_by_created_after_inclusive(
    repo: FakeSessionRepository,
) -> None:
    """``created_after`` is inclusive: sessions created exactly at the
    boundary must remain in the result. (Out-of-range creations are
    excluded.)
    """
    sessions = {
        "sesn_old": _make_session("sesn_old", created_at=_T0 - timedelta(days=1)),
        "sesn_boundary": _make_session("sesn_boundary", created_at=_T0),
        "sesn_new": _make_session("sesn_new", created_at=_T0 + timedelta(days=1)),
    }
    uc = ListSessionsUseCase(sessions_index=sessions, repo=repo)
    result = uc.execute(ListSessionsInput(created_after=_T0)).sessions
    ids = [s.session_id for s in result]
    assert ids == ["sesn_boundary", "sesn_new"]


def test_list_sessions_filters_by_updated_before_inclusive(
    repo: FakeSessionRepository,
) -> None:
    """``updated_before`` is inclusive on the boundary timestamp."""
    sessions = {
        "sesn_a": _make_session(
            "sesn_a", updated_at=_T0 - timedelta(hours=1)
        ),
        "sesn_b": _make_session("sesn_b", updated_at=_T0),
        "sesn_c": _make_session(
            "sesn_c", updated_at=_T0 + timedelta(hours=1)
        ),
    }
    uc = ListSessionsUseCase(sessions_index=sessions, repo=repo)
    result = uc.execute(ListSessionsInput(updated_before=_T0)).sessions
    ids = [s.session_id for s in result]
    assert ids == ["sesn_a", "sesn_b"]


def test_list_sessions_out_of_range_filter_returns_empty(
    repo: FakeSessionRepository,
) -> None:
    """A filter window with no overlap returns an empty list, not an error."""
    sessions = {
        "sesn_001": _make_session("sesn_001", created_at=_T0),
    }
    uc = ListSessionsUseCase(sessions_index=sessions, repo=repo)
    result = uc.execute(
        ListSessionsInput(created_after=_T0 + timedelta(days=365))
    ).sessions
    assert result == []


def test_list_sessions_orders_by_created_at_desc(
    repo: FakeSessionRepository,
) -> None:
    """``order_by=created_at`` + ``order=desc`` returns newest first."""
    sessions = {
        "sesn_a": _make_session("sesn_a", created_at=_T0),
        "sesn_b": _make_session("sesn_b", created_at=_T0 + timedelta(hours=1)),
        "sesn_c": _make_session("sesn_c", created_at=_T0 + timedelta(hours=2)),
    }
    uc = ListSessionsUseCase(sessions_index=sessions, repo=repo)
    result = uc.execute(
        ListSessionsInput(order_by="created_at", order="desc")
    ).sessions
    assert [s.session_id for s in result] == ["sesn_c", "sesn_b", "sesn_a"]


def test_list_sessions_orders_by_updated_at_asc(
    repo: FakeSessionRepository,
) -> None:
    sessions = {
        "sesn_a": _make_session(
            "sesn_a", updated_at=_T0 + timedelta(hours=2)
        ),
        "sesn_b": _make_session("sesn_b", updated_at=_T0),
        "sesn_c": _make_session(
            "sesn_c", updated_at=_T0 + timedelta(hours=1)
        ),
    }
    uc = ListSessionsUseCase(sessions_index=sessions, repo=repo)
    result = uc.execute(
        ListSessionsInput(order_by="updated_at", order="asc")
    ).sessions
    assert [s.session_id for s in result] == ["sesn_b", "sesn_c", "sesn_a"]


def test_list_sessions_default_order_is_session_id(
    repo: FakeSessionRepository,
) -> None:
    """When ``order_by`` is omitted, ordering remains stable on session_id —
    the contract used by clients written before timestamps existed.
    """
    sessions = {
        "sesn_c": _make_session("sesn_c", created_at=_T0),
        "sesn_a": _make_session("sesn_a", created_at=_T0 + timedelta(days=1)),
        "sesn_b": _make_session("sesn_b", created_at=_T0 - timedelta(days=1)),
    }
    uc = ListSessionsUseCase(sessions_index=sessions, repo=repo)
    result = uc.execute().sessions
    assert [s.session_id for s in result] == ["sesn_a", "sesn_b", "sesn_c"]
