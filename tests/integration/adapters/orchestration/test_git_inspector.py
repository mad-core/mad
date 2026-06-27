"""Integration tests for ``SubprocessGitInspector`` (issue #88).

Exercises the real adapter against real on-disk git repositories created in
``tmp_path``. No network: ``pushed`` is verified via a local ``--bare`` remote
and a local-tracking fetch, never a live origin.

Each behavioural assertion has its negative twin:

- commits since base  ↔  no commits since base (empty list)
- attached branch     ↔  detached HEAD (``head_branch == "HEAD"``)
- clean worktree      ↔  dirty worktree
- pushed branch       ↔  unpushed branch
- a git repo          ↔  a non-git directory (graceful ``None``)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from mad.adapters.outbound.orchestration.git_inspector import SubprocessGitInspector


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    (path / "README.md").write_text("seed\n")
    _git(path, "add", "README.md")
    _git(path, "commit", "-q", "-m", "init")
    return path


# -- read_head_sha -------------------------------------------------------------


async def test_read_head_sha_returns_current_head(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    expected = _git(repo, "rev-parse", "HEAD")

    sha = await SubprocessGitInspector().read_head_sha(repo)

    assert sha == expected


async def test_read_head_sha_on_non_git_dir_returns_none(tmp_path: Path) -> None:
    # Negative twin: not a git repo degrades to None, never raises.
    plain = tmp_path / "plain"
    plain.mkdir()

    sha = await SubprocessGitInspector().read_head_sha(plain)

    assert sha is None


# -- inspect: commits ----------------------------------------------------------


async def test_inspect_lists_commits_created_since_base(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    inspector = SubprocessGitInspector()
    base = await inspector.read_head_sha(repo)

    (repo / "a.txt").write_text("a\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "add a")
    head = _git(repo, "rev-parse", "HEAD")

    result = await inspector.inspect(repo, base)

    assert result is not None
    assert result.base_sha == base
    assert result.head_sha == head
    assert result.head_branch == "main"
    assert [c.subject for c in result.commits] == ["add a"]
    assert result.commits[0].sha == head


async def test_inspect_with_no_new_commits_returns_empty_commit_list(
    tmp_path: Path,
) -> None:
    # Negative twin: agent created no commits — a result is still produced
    # with an empty commit list, not a missing event (issue #88 AC).
    repo = _init_repo(tmp_path / "repo")
    inspector = SubprocessGitInspector()
    base = await inspector.read_head_sha(repo)

    result = await inspector.inspect(repo, base)

    assert result is not None
    assert result.commits == ()
    assert result.head_sha == base


# -- inspect: detached HEAD ----------------------------------------------------


async def test_inspect_reports_detached_head(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    inspector = SubprocessGitInspector()
    base = await inspector.read_head_sha(repo)
    # Detach HEAD onto the current commit.
    _git(repo, "checkout", "-q", "--detach", "HEAD")

    result = await inspector.inspect(repo, base)

    assert result is not None
    assert result.head_branch == "HEAD"
    assert result.pushed is False


# -- inspect: dirty ------------------------------------------------------------


async def test_inspect_reports_clean_worktree(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    inspector = SubprocessGitInspector()
    base = await inspector.read_head_sha(repo)

    result = await inspector.inspect(repo, base)

    assert result is not None
    assert result.dirty is False


async def test_inspect_reports_dirty_worktree(tmp_path: Path) -> None:
    # Negative twin to the clean-worktree case.
    repo = _init_repo(tmp_path / "repo")
    inspector = SubprocessGitInspector()
    base = await inspector.read_head_sha(repo)
    (repo / "README.md").write_text("seed\nuncommitted change\n")

    result = await inspector.inspect(repo, base)

    assert result is not None
    assert result.dirty is True


# -- inspect: pushed -----------------------------------------------------------


async def test_inspect_reports_pushed_branch(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    bare = tmp_path / "origin.git"
    _git(repo, "clone", "-q", "--bare", str(repo), str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "fetch", "-q", "origin")
    inspector = SubprocessGitInspector()
    base = await inspector.read_head_sha(repo)

    result = await inspector.inspect(repo, base)

    assert result is not None
    assert result.head_branch == "main"
    assert result.pushed is True


async def test_inspect_reports_unpushed_branch(tmp_path: Path) -> None:
    # Negative twin: a branch with no remote-tracking ref is not pushed.
    repo = _init_repo(tmp_path / "repo")
    bare = tmp_path / "origin.git"
    _git(repo, "clone", "-q", "--bare", str(repo), str(bare))
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "fetch", "-q", "origin")
    _git(repo, "checkout", "-q", "-b", "feat/local-only")
    inspector = SubprocessGitInspector()
    base = await inspector.read_head_sha(repo)

    result = await inspector.inspect(repo, base)

    assert result is not None
    assert result.head_branch == "feat/local-only"
    assert result.pushed is False


# -- inspect: graceful degradation ---------------------------------------------


async def test_inspect_on_non_git_dir_returns_none(tmp_path: Path) -> None:
    # Negative twin to every successful inspect above: a non-git workspace
    # yields None so the dispatcher omits the event instead of failing.
    plain = tmp_path / "plain"
    plain.mkdir()

    result = await SubprocessGitInspector().inspect(plain, "deadbeef")

    assert result is None


async def test_inspect_with_no_base_sha_returns_none(tmp_path: Path) -> None:
    # No baseline was captured at dispatch — nothing to diff against.
    repo = _init_repo(tmp_path / "repo")

    result = await SubprocessGitInspector().inspect(repo, None)

    assert result is None
