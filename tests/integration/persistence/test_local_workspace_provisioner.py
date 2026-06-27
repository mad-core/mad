"""Integration tests for LocalWorkspaceProvisioner.materialize_github_repo
covering the issue #8 base_branch checkout behavior, plus the issue #64
configurable workspace base directory (create/destroy filesystem effects).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mad.adapters.outbound.persistence.local_workspace_provisioner import (
    GitCloneError,
    LocalWorkspaceProvisioner,
    _scrub_token,
)


def test_create_makes_missing_base_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # #64: the resolved base is created on first use even when several levels
    # of it are absent (mkdir parents=True), so an operator can point
    # MAD_WORKSPACE_DIR at a path that does not exist yet.
    base = tmp_path / "nested" / "workspaces"
    monkeypatch.setenv("MAD_WORKSPACE_DIR", str(base))
    assert not base.exists()

    created = LocalWorkspaceProvisioner().create("sesn_xyz")

    assert created == base / "mad_sesn_xyz"
    assert created.is_dir()
    assert base.is_dir()


def test_destroy_removes_only_the_session_subdirectory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # #64: destroy() tears down a single session's mad_<id> subdir and MUST
    # leave both the shared base and any sibling session untouched — otherwise
    # one session's teardown would wipe out concurrent sessions' workspaces.
    base = tmp_path / "workspaces"
    monkeypatch.setenv("MAD_WORKSPACE_DIR", str(base))
    provisioner = LocalWorkspaceProvisioner()
    target = provisioner.create("sesn_target")
    sibling = provisioner.create("sesn_sibling")

    provisioner.destroy("sesn_target")

    assert not target.exists()
    assert sibling.is_dir()
    assert base.is_dir()


def _bare_repo_with_branches(tmp_path: Path, branches: list[str]) -> Path:
    """Build a local bare repo with the given branches (first is the default)."""
    seed = tmp_path / "seed"
    seed.mkdir()
    subprocess.run(["git", "init", "-q", "-b", branches[0], str(seed)], check=True)
    (seed / "README.md").write_text("seed\n")
    subprocess.run(["git", "-C", str(seed), "add", "README.md"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(seed),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-q",
            "-m",
            "init",
        ],
        check=True,
    )
    for branch in branches[1:]:
        subprocess.run(
            ["git", "-C", str(seed), "branch", branch],
            check=True,
            capture_output=True,
        )
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(bare)], check=True)
    return bare


def test_materialize_checks_out_requested_base_branch(tmp_path: Path) -> None:
    bare = _bare_repo_with_branches(tmp_path, ["main", "develop"])
    workspace = tmp_path / "ws"
    workspace.mkdir()

    LocalWorkspaceProvisioner().materialize_github_repo(
        workspace=workspace,
        mount_path="/workspace/repo",
        repo_url=f"file://{bare}",
        token=None,
        base_branch="develop",
    )

    head = subprocess.run(
        ["git", "-C", str(workspace / "repo"), "rev-parse", "--abbrev-ref", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert head.stdout.strip() == "develop"


def test_materialize_unknown_base_branch_raises_value_error(tmp_path: Path) -> None:
    bare = _bare_repo_with_branches(tmp_path, ["main"])
    workspace = tmp_path / "ws"
    workspace.mkdir()

    with pytest.raises(ValueError, match="unknown base_branch"):
        LocalWorkspaceProvisioner().materialize_github_repo(
            workspace=workspace,
            mount_path="/workspace/repo",
            repo_url=f"file://{bare}",
            token=None,
            base_branch="does-not-exist",
        )


def test_materialize_raises_actionable_error_when_clone_fails(tmp_path: Path) -> None:
    """Negative twin (#89): a clone that fails (no credential / unreachable source)
    raises GitCloneError with an actionable GITHUB_TOKEN hint — never a silent
    success or a bare CalledProcessError. Uses a nonexistent local source so no
    network or real GitHub is touched (hard rule 5)."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    missing = tmp_path / "does-not-exist.git"

    with pytest.raises(GitCloneError, match="GITHUB_TOKEN"):
        LocalWorkspaceProvisioner().materialize_github_repo(
            workspace=workspace,
            mount_path="/workspace/repo",
            repo_url=f"file://{missing}",
            token=None,
        )


def test_scrub_token_removes_token_literal() -> None:
    """Hard rule 2: a token echoed in git stderr is scrubbed before it can reach
    the raised error message or any log."""
    leaked = "fatal: could not read from https://ghp_secret@github.com/x/y.git"
    assert _scrub_token(leaked, "ghp_secret") == (
        "fatal: could not read from https://[REDACTED]@github.com/x/y.git"
    )


def test_scrub_token_is_noop_without_token() -> None:
    """Negative twin: anonymous clone failures (token=None) pass stderr through."""
    assert _scrub_token("fatal: repository not found", None) == "fatal: repository not found"


def test_materialize_without_base_branch_keeps_remote_default(tmp_path: Path) -> None:
    bare = _bare_repo_with_branches(tmp_path, ["main"])
    workspace = tmp_path / "ws"
    workspace.mkdir()

    LocalWorkspaceProvisioner().materialize_github_repo(
        workspace=workspace,
        mount_path="/workspace/repo",
        repo_url=f"file://{bare}",
        token=None,
    )

    head = subprocess.run(
        ["git", "-C", str(workspace / "repo"), "rev-parse", "--abbrev-ref", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert head.stdout.strip() == "main"
