from __future__ import annotations

import subprocess
from collections import deque
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as app_module
from app import LLMProvider, ProviderResponse


class FakeProvider:
    def __init__(self) -> None:
        self._queue: deque[ProviderResponse] = deque()

    def script(self, responses: list[ProviderResponse]) -> None:
        self._queue = deque(responses)

    async def complete(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
    ) -> ProviderResponse:
        if not self._queue:
            return ProviderResponse(text="(fake provider exhausted)", stop_reason="end_turn")
        return self._queue.popleft()


@pytest.fixture
def fake_provider(monkeypatch: pytest.MonkeyPatch) -> FakeProvider:
    provider = FakeProvider()
    monkeypatch.setattr(app_module, "get_provider", lambda name: provider)
    return provider


@pytest.fixture
def client(fake_provider: FakeProvider) -> TestClient:
    return TestClient(app_module.app)


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def bare_repo(tmp_path: Path) -> Path:
    """A local git bare repo with one commit on `main`. Use as a clone source.

    Returns a file:// path the test can pass as `resources[].url` so tests
    never touch real GitHub.
    """
    seed = tmp_path / "seed"
    seed.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], check=True)
    (seed / "README.md").write_text("seed repo\n")
    subprocess.run(["git", "-C", str(seed), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(seed), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "init"],
        check=True,
    )
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(seed), str(bare)], check=True)
    return bare


def _session_payload(bare_repo: Path) -> dict:
    return {
        "agent": {
            "name": "test-agent",
            "system": "You are a test agent.",
            "provider": "fake_scripted",
        },
        "resources": [
            {
                "type": "github_repository",
                "url": f"file://{bare_repo}",
                "mount_path": "/workspace/repo",
                "authorization_token": "ghp_fake_token_xxx",
                "checkout": {"type": "branch", "name": "main"},
            }
        ],
    }


@pytest.fixture
def session_payload(bare_repo: Path) -> dict:
    return _session_payload(bare_repo)
