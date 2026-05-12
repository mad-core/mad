"""Unit tests for CleanupSessionsUseCase.

The use case is the engine behind POST /v1/sessions/cleanup. These tests
exercise it directly without going through the HTTP adapter — they
verify the selection rule, the dry_run branch, the tombstone exclusion,
and the emission contract the route relies on.
"""

from __future__ import annotations

from datetime import UTC, datetime

from mad.core.events.emitter import EventEmitter
from mad.core.sessions.domain.entities.session import Session
from mad.core.sessions.use_cases.cleanup_sessions import (
    CleanupSessionsInput,
    CleanupSessionsUseCase,
)
from support.events import PersistedEventStore as FakeStore
from support.events import RecordingEventBus as FakeBus
from support.sessions import FakeProvisioner


def _make_session(
    session_id: str,
    status: str = "idle",
    updated_at: datetime | None = None,
) -> Session:
    when = updated_at or datetime.now(UTC)
    s = Session(
        session_id=session_id,
        agent={"name": "t", "provider": "fake"},
        workspace=f"/tmp/mad_{session_id}",
        created_at=when,
        updated_at=when,
    )
    s.status = status
    return s


def _make_uc(
    sessions: dict[str, Session], provisioner: FakeProvisioner
) -> tuple[CleanupSessionsUseCase, FakeStore, FakeBus]:
    store = FakeStore()
    bus = FakeBus()
    emitter = EventEmitter(store=store, bus=bus)
    uc = CleanupSessionsUseCase(
        provisioner=provisioner,
        sessions_index=sessions,
        emitter=emitter,
    )
    return uc, store, bus


# ---------------------------------------------------------------------------
# Happy path: dry_run=false destroys candidates and emits session.deleted
# ---------------------------------------------------------------------------


async def test_cleanup_destroys_sessions_older_than_cutoff() -> None:
    """A session with updated_at < older_than is destroyed: provisioner
    receives destroy(session_id), the entity is marked deleted, the id
    is returned in deleted_session_ids."""
    sid = "sesn_old"
    sessions = {sid: _make_session(sid, "idle", datetime(2025, 1, 1, tzinfo=UTC))}
    provisioner = FakeProvisioner()
    uc, _, _ = _make_uc(sessions, provisioner)

    out = await uc.execute(
        CleanupSessionsInput(older_than=datetime(2025, 6, 1, tzinfo=UTC), dry_run=False)
    )

    assert out.deleted_session_ids == [sid]
    assert out.would_delete == []
    assert out.examined == 1
    assert sessions[sid].status == "deleted"
    assert provisioner.destroyed == [sid]


async def test_cleanup_emits_session_deleted_with_prior_status() -> None:
    """Per matching session the emitter appends session.deleted carrying
    final_status = the status the entity had BEFORE mark_deleted ran.
    Proves the bulk path reuses the destroy_session primitive verbatim."""
    sid = "sesn_old"
    sessions = {sid: _make_session(sid, "idle", datetime(2025, 1, 1, tzinfo=UTC))}
    provisioner = FakeProvisioner()
    uc, store, bus = _make_uc(sessions, provisioner)

    await uc.execute(
        CleanupSessionsInput(older_than=datetime(2025, 6, 1, tzinfo=UTC), dry_run=False)
    )

    assert store.appended == [(sid, "session.deleted", {"final_status": "idle"})]
    assert len(bus.published) == 1
    assert bus.published[0].type == "session.deleted"
    assert bus.published[0].data == {"final_status": "idle"}


async def test_cleanup_running_session_with_stale_updated_at_is_deleted() -> None:
    """No special skip for status=running. A stale running session is
    destroyed; session.deleted carries final_status=running so consumers
    can distinguish it from an idle tombstone."""
    sid = "sesn_running"
    sessions = {sid: _make_session(sid, "running", datetime(2025, 1, 1, tzinfo=UTC))}
    provisioner = FakeProvisioner()
    uc, store, _ = _make_uc(sessions, provisioner)

    out = await uc.execute(
        CleanupSessionsInput(older_than=datetime(2025, 6, 1, tzinfo=UTC), dry_run=False)
    )

    assert out.deleted_session_ids == [sid]
    assert provisioner.destroyed == [sid]
    assert store.appended == [(sid, "session.deleted", {"final_status": "running"})]


# ---------------------------------------------------------------------------
# Negative twin: sessions newer than cutoff survive untouched
# ---------------------------------------------------------------------------


async def test_cleanup_does_not_destroy_sessions_newer_than_cutoff() -> None:
    """A session whose updated_at is >= older_than survives: no destroy
    call, no emission, no status mutation. Counted in examined."""
    sid = "sesn_young"
    sessions = {sid: _make_session(sid, "idle", datetime(2026, 5, 1, tzinfo=UTC))}
    provisioner = FakeProvisioner()
    uc, store, _ = _make_uc(sessions, provisioner)

    out = await uc.execute(
        CleanupSessionsInput(older_than=datetime(2025, 1, 1, tzinfo=UTC), dry_run=False)
    )

    assert out.deleted_session_ids == []
    assert out.examined == 1
    assert provisioner.destroyed == []
    assert store.appended == []
    assert sessions[sid].status == "idle"


# ---------------------------------------------------------------------------
# dry_run=true: reports candidates without acting
# ---------------------------------------------------------------------------


async def test_cleanup_dry_run_reports_without_destroying() -> None:
    """dry_run=true populates would_delete with the candidate ids;
    provisioner.destroy is never called; emitter records nothing;
    session entities remain in their prior status."""
    sid = "sesn_old"
    sessions = {sid: _make_session(sid, "idle", datetime(2025, 1, 1, tzinfo=UTC))}
    provisioner = FakeProvisioner()
    uc, store, bus = _make_uc(sessions, provisioner)

    out = await uc.execute(
        CleanupSessionsInput(older_than=datetime(2025, 6, 1, tzinfo=UTC), dry_run=True)
    )

    assert out.would_delete == [sid]
    assert out.deleted_session_ids == []
    assert out.examined == 1
    assert provisioner.destroyed == []
    assert store.appended == []
    assert bus.published == []
    assert sessions[sid].status == "idle"


# ---------------------------------------------------------------------------
# Tombstones: status=deleted excluded from examined and from selection
# ---------------------------------------------------------------------------


async def test_cleanup_excludes_already_deleted_from_examined() -> None:
    """An entity with status=deleted is invisible to cleanup: never
    counted in examined, never re-destroyed, never echoed in the
    response."""
    tombstone = "sesn_dead"
    sessions = {
        tombstone: _make_session(tombstone, "deleted", datetime(2025, 1, 1, tzinfo=UTC)),
    }
    provisioner = FakeProvisioner()
    uc, store, _ = _make_uc(sessions, provisioner)

    out = await uc.execute(
        CleanupSessionsInput(older_than=datetime(2025, 6, 1, tzinfo=UTC), dry_run=False)
    )

    assert out.deleted_session_ids == []
    assert out.examined == 0
    assert provisioner.destroyed == []
    assert store.appended == []


async def test_cleanup_mixes_live_and_tombstone_correctly() -> None:
    """Mixed index: a live old session is destroyed, a tombstone is
    skipped, a young live session survives. Single examined count
    matches the number of NON-tombstone entries the use case
    considered against the filter."""
    live_old = _make_session("sesn_old", "idle", datetime(2025, 1, 1, tzinfo=UTC))
    tombstone = _make_session("sesn_dead", "deleted", datetime(2025, 1, 1, tzinfo=UTC))
    live_young = _make_session("sesn_young", "idle", datetime(2026, 5, 1, tzinfo=UTC))
    sessions = {s.session_id: s for s in (live_old, tombstone, live_young)}
    provisioner = FakeProvisioner()
    uc, _, _ = _make_uc(sessions, provisioner)

    out = await uc.execute(
        CleanupSessionsInput(older_than=datetime(2025, 6, 1, tzinfo=UTC), dry_run=False)
    )

    assert out.deleted_session_ids == ["sesn_old"]
    assert out.examined == 2  # live_old + live_young; tombstone excluded
    assert provisioner.destroyed == ["sesn_old"]
    assert live_young.status == "idle"
    assert tombstone.status == "deleted"


async def test_cleanup_empty_index_returns_empty_result() -> None:
    """An empty sessions index returns an empty response: no candidates,
    nothing examined, nothing destroyed. Negative twin to the populated-
    index happy path."""
    sessions: dict[str, Session] = {}
    provisioner = FakeProvisioner()
    uc, store, _ = _make_uc(sessions, provisioner)

    out = await uc.execute(
        CleanupSessionsInput(older_than=datetime(2025, 6, 1, tzinfo=UTC), dry_run=False)
    )

    assert out.deleted_session_ids == []
    assert out.would_delete == []
    assert out.examined == 0
    assert provisioner.destroyed == []
    assert store.appended == []
