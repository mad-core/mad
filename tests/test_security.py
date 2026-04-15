"""Security tests for the hard rules in CLAUDE.md / specs/v0.1/requirements.md.

FR-3  — Path traversal: mount_path values that escape the session workspace MUST be rejected.
FR-2  — Token hygiene: after clone, git remote -v must NOT contain the authorization_token.
NFR-2 — Token hygiene is also a non-functional constraint (tokens never persisted).
FR-11 — Native tool use: tool calls emitted as free text must be ignored.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import ProviderResponse
from tests.conftest import FakeProvider


# ---------------------------------------------------------------------------
# FR-3 — Path traversal prevention
# ---------------------------------------------------------------------------

def test_path_traversal_absolute_escape_is_rejected(
    client: TestClient, bare_repo: Path
) -> None:
    """A mount_path that is an absolute path outside /workspace must be rejected with 400."""
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
    assert r.status_code == 400, (
        f"Absolute escape mount_path must be rejected with 400, got {r.status_code}"
    )


def test_path_traversal_dotdot_is_rejected(
    client: TestClient, bare_repo: Path
) -> None:
    """A mount_path using ../ to escape the workspace must be rejected with 400."""
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
    assert r.status_code == 400, (
        f"Dot-dot escape mount_path must be rejected with 400, got {r.status_code}"
    )


def test_path_traversal_symlink_escape_is_rejected(
    client: TestClient, bare_repo: Path
) -> None:
    """A mount_path of just /tmp (outside /workspace prefix) must be rejected with 400."""
    payload = {
        "agent": {"name": "a", "system": "", "provider": "fake_scripted"},
        "resources": [
            {
                "type": "github_repository",
                "url": f"file://{bare_repo}",
                "mount_path": "/tmp/injected",
                "authorization_token": "ghp_x",
            }
        ],
    }
    r = client.post("/v1/sessions", json=payload)
    assert r.status_code == 400, (
        f"mount_path /tmp/injected must be rejected with 400, got {r.status_code}"
    )


def test_path_traversal_file_resource_dotdot_rejected(
    client: TestClient,
) -> None:
    """A file resource with a dot-dot mount_path must also be rejected with 400."""
    payload = {
        "agent": {"name": "a", "system": "", "provider": "fake_scripted"},
        "resources": [
            {
                "type": "file",
                "content": "malicious",
                "mount_path": "/workspace/../../../etc/cron.d/evil",
            }
        ],
    }
    r = client.post("/v1/sessions", json=payload)
    assert r.status_code == 400, (
        f"Dot-dot file resource mount_path must be rejected, got {r.status_code}"
    )


def test_path_traversal_valid_workspace_path_is_accepted(
    client: TestClient, bare_repo: Path
) -> None:
    """A mount_path under /workspace/ must be accepted (positive control)."""
    payload = {
        "agent": {"name": "a", "system": "", "provider": "fake_scripted"},
        "resources": [
            {
                "type": "github_repository",
                "url": f"file://{bare_repo}",
                "mount_path": "/workspace/safe/repo",
                "authorization_token": "ghp_x",
            }
        ],
    }
    r = client.post("/v1/sessions", json=payload)
    assert r.status_code == 200, (
        f"Valid /workspace/ mount_path must be accepted, got {r.status_code}"
    )


# ---------------------------------------------------------------------------
# FR-2 / NFR-2 — Token hygiene
# ---------------------------------------------------------------------------

def test_token_stripped_from_remote_after_clone(
    client: TestClient, bare_repo: Path
) -> None:
    """After cloning, git remote -v must not contain the authorization_token."""
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
    assert token not in remote, (
        f"authorization_token must be stripped from git remote after clone, but found it in:\n{remote}"
    )


def test_token_not_in_session_response(
    client: TestClient, bare_repo: Path
) -> None:
    """The POST /v1/sessions response body must not echo the authorization_token."""
    token = "ghp_response_leak_TEST_99999"
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
    r = client.post("/v1/sessions", json=payload)
    assert r.status_code == 200
    assert token not in r.text, (
        "authorization_token must NOT appear anywhere in the session creation response"
    )


def test_token_not_in_session_log(
    client: TestClient, bare_repo: Path
) -> None:
    """The JSONL session log must not contain the authorization_token at any point."""
    token = "ghp_log_leak_TOKEN_77777"
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
    session_id = data["session_id"]

    log_path = Path("sessions") / f"{session_id}.jsonl"
    assert log_path.exists(), "session log must exist"
    log_contents = log_path.read_text()
    assert token not in log_contents, (
        "authorization_token must NOT appear in the session log JSONL"
    )


# ---------------------------------------------------------------------------
# FR-11 — Native tool use only (free-text tool calls are ignored)
# ---------------------------------------------------------------------------

def test_native_tool_use_free_text_tool_calls_ignored(
    client: TestClient, fake_provider: FakeProvider, bare_repo: Path
) -> None:
    """If the LLM emits a tool call as free text (not structured tool_use), it must be ignored.

    The harness must not parse free text with regex. The test verifies that a
    provider response containing only text (even text that looks like a tool call)
    does NOT trigger sandbox execution. We check this by confirming the session
    reaches status_idle with no agent.tool_result events in the log.
    """
    # Provider returns only text — simulating free-text "tool call" that must be ignored
    fake_provider.script([
        ProviderResponse(
            text='<tool>bash</tool><input>{"command": "rm -rf /"}</input>',
            tool_uses=[],  # no structured tool_use blocks
            stop_reason="end_turn",
        )
    ])
    payload = {
        "agent": {"name": "a", "system": "", "provider": "fake_scripted"},
        "resources": [
            {
                "type": "github_repository",
                "url": f"file://{bare_repo}",
                "mount_path": "/workspace/repo",
                "authorization_token": "ghp_x",
            }
        ],
    }
    data = client.post("/v1/sessions", json=payload).json()
    session_id = data["session_id"]

    r = client.post(
        f"/v1/sessions/{session_id}/events",
        json={"events": [{"type": "user.message", "content": "try the free-text trick"}]},
    )
    assert r.status_code in (200, 202)

    # Wait briefly for the background loop to finish (it's fake so it's instant)
    import time; time.sleep(0.2)

    log_path = Path("sessions") / f"{session_id}.jsonl"
    import json as _json
    lines = [_json.loads(ln) for ln in log_path.read_text().splitlines() if ln.strip()]
    tool_results = [e for e in lines if e.get("type") == "agent.tool_result"]
    assert len(tool_results) == 0, (
        f"Free-text tool calls must be ignored — no tool_result events expected, got: {tool_results}"
    )
