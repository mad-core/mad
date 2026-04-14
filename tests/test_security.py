"""Security tests for the hard rules in CLAUDE.md.

- Path traversal: a mount_path that would escape the session workspace must be rejected.
- Token hygiene: after clone, `git remote -v` inside the mounted repo must NOT contain the token.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient


def test_path_traversal_absolute_escape_is_rejected(
    client: TestClient, bare_repo: Path
) -> None:
    payload = {
        "agent": {"name": "a", "system": "", "provider": "fake_scripted"},
        "resources": [
            {
                "type": "github_repository",
                "url": f"file://{bare_repo}",
                "mount_path": "/etc/passwd",
                "authorization_token": "ghp_x",
            }
        ],
    }
    r = client.post("/v1/sessions", json=payload)
    assert r.status_code == 400


def test_path_traversal_dotdot_is_rejected(
    client: TestClient, bare_repo: Path
) -> None:
    payload = {
        "agent": {"name": "a", "system": "", "provider": "fake_scripted"},
        "resources": [
            {
                "type": "github_repository",
                "url": f"file://{bare_repo}",
                "mount_path": "/workspace/../../../../tmp/escape",
                "authorization_token": "ghp_x",
            }
        ],
    }
    r = client.post("/v1/sessions", json=payload)
    assert r.status_code == 400


def test_token_stripped_from_remote_after_clone(
    client: TestClient, bare_repo: Path
) -> None:
    token = "ghp_supersecret_TOKEN_12345"
    payload = {
        "agent": {"name": "a", "system": "", "provider": "fake_scripted"},
        "resources": [
            {
                "type": "github_repository",
                "url": f"file://{bare_repo}",
                "mount_path": "/workspace/repo",
                "authorization_token": token,
            }
        ],
    }
    data = client.post("/v1/sessions", json=payload).json()
    local_path = Path(data["resources_mounted"][0]["local_path"])
    remote = subprocess.run(
        ["git", "-C", str(local_path), "remote", "-v"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert token not in remote
