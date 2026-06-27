"""Unit tests for the ``GitResult`` value object (issue #88).

Covers the ``to_event_data`` serializer that the dispatcher uses to write the
``task.git_result`` event payload — including the negative twin (a result
with no commits) and the detached-HEAD shape (``head_branch is None``).
"""

from __future__ import annotations

from mad.core.orchestration.domain.git_result import Commit, GitResult


def _result(**overrides: object) -> GitResult:
    base = {
        "base_sha": "aaa111",
        "head_branch": "feat/x",
        "head_sha": "bbb222",
        "commits": (Commit(sha="bbb222", subject="do the thing"),),
        "dirty": False,
        "pushed": True,
    }
    base.update(overrides)
    return GitResult(**base)  # type: ignore[arg-type]


def test_to_event_data_serializes_full_shape() -> None:
    data = _result().to_event_data("task-1")

    assert data == {
        "task_id": "task-1",
        "base_sha": "aaa111",
        "head_branch": "feat/x",
        "head_sha": "bbb222",
        "commits": [{"sha": "bbb222", "subject": "do the thing"}],
        "dirty": False,
        "pushed": True,
    }


def test_to_event_data_with_no_commits_emits_empty_list() -> None:
    # Negative twin: a task that created nothing still serializes a result —
    # ``commits`` is an empty list, never a missing key (issue #88 AC).
    data = _result(commits=()).to_event_data("task-2")

    assert data["commits"] == []
    assert data["task_id"] == "task-2"


def test_to_event_data_reports_detached_head_as_null_branch() -> None:
    # Detached HEAD is reported as ``head_branch = None`` (issue #88 AC),
    # not omitted and not a crash.
    data = _result(head_branch=None).to_event_data("task-3")

    assert data["head_branch"] is None


def test_to_event_data_preserves_commit_order_and_subjects() -> None:
    commits = (
        Commit(sha="c3", subject="third"),
        Commit(sha="c2", subject="second"),
        Commit(sha="c1", subject="first"),
    )
    data = _result(commits=commits).to_event_data("task-4")

    assert data["commits"] == [
        {"sha": "c3", "subject": "third"},
        {"sha": "c2", "subject": "second"},
        {"sha": "c1", "subject": "first"},
    ]


def test_to_event_data_carries_dirty_flag_when_worktree_unclean() -> None:
    # Negative twin to the clean-tree assertion above.
    data = _result(dirty=True, pushed=False).to_event_data("task-5")

    assert data["dirty"] is True
    assert data["pushed"] is False
