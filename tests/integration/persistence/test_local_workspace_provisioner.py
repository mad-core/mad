"""Integration tests for LocalWorkspaceProvisioner.materialize_github_repo
covering the issue #8 base_branch checkout behavior.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mad.adapters.outbound.persistence.local_workspace_provisioner import (
    LocalWorkspaceProvisioner,
)


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
