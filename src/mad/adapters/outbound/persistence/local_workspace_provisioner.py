from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


def workspace_path(session_id: str) -> Path:
    return Path(tempfile.gettempdir()) / f"mad_{session_id}"


def _resolve_mount(workspace: Path, mount_path: str) -> Path:
    """Resolve mount_path relative to workspace, stripping leading /workspace/."""
    relative = mount_path.lstrip("/")
    if relative.startswith("workspace/") or relative == "workspace":
        relative = relative[len("workspace") :]
    relative = relative.lstrip("/")
    if relative:
        return workspace / relative
    return workspace


class LocalWorkspaceProvisioner:
    """Concrete implementation of ``WorkspaceProvisioner`` using the local filesystem."""

    def create(self, session_id: str) -> Path:
        """Return (and create if necessary) the temp workspace for a session."""
        path = workspace_path(session_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def destroy(self, session_id: str) -> None:
        """Remove the workspace directory if it exists."""
        path = workspace_path(session_id)
        if path.exists():
            shutil.rmtree(path)

    def materialize_github_repo(
        self,
        workspace: Path,
        mount_path: str,
        repo_url: str,
        token: str | None,
        base_branch: str | None = None,
    ) -> None:
        """Clone repo_url into workspace at mount_path, stripping the token afterwards."""
        local_path = _resolve_mount(workspace, mount_path)
        local_path.mkdir(parents=True, exist_ok=True)

        clone_url = repo_url
        if token and repo_url.startswith("https://"):
            clone_url = repo_url.replace("https://", f"https://{token}@", 1)

        cmd = ["git", "clone", "-q", clone_url, str(local_path)]
        shutil.rmtree(local_path)
        subprocess.run(cmd, check=True, capture_output=True)

        # Strip token from remote after clone (CLAUDE.md hard rule 2)
        subprocess.run(
            ["git", "-C", str(local_path), "remote", "set-url", "origin", repo_url],
            check=True,
            capture_output=True,
        )

        if base_branch:
            result = subprocess.run(
                ["git", "-C", str(local_path), "checkout", base_branch],
                capture_output=True,
            )
            if result.returncode != 0:
                raise ValueError(f"unknown base_branch {base_branch!r} for repository")

    def materialize_file(
        self,
        workspace: Path,
        mount_path: str,
        content: str,
    ) -> None:
        """Write content to workspace at mount_path."""
        local_path = _resolve_mount(workspace, mount_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_text(content)
