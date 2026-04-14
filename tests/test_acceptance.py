"""Acceptance tests mapped 1:1 to specs/v0.1/requirements.md → MVP acceptance criteria.

These tests are EXPECTED to fail until the implementer runs. They encode the
red state of the TDD loop.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import ProviderResponse, ToolUse
from tests.conftest import FakeProvider


def test_mvp_01_create_session_clones_repo(client: TestClient, session_payload: dict) -> None:
    r = client.post("/v1/sessions", json=session_payload)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "created"
    mounted = data["resources_mounted"][0]
    assert mounted["status"] == "cloned"
    assert Path(mounted["local_path"]).exists()


def test_mvp_02_send_user_message_starts_agent(
    client: TestClient, fake_provider: FakeProvider, session_payload: dict
) -> None:
    fake_provider.script([ProviderResponse(text="done", stop_reason="end_turn")])
    r = client.post("/v1/sessions", json=session_payload)
    session_id = r.json()["session_id"]

    r = client.post(
        f"/v1/sessions/{session_id}/events",
        json={"events": [{"type": "user.message", "content": "hello"}]},
    )
    assert r.status_code in (200, 202)


def test_mvp_03_stream_emits_agent_events(
    client: TestClient, fake_provider: FakeProvider, session_payload: dict
) -> None:
    fake_provider.script([
        ProviderResponse(
            tool_uses=[ToolUse(id="t1", name="bash", input={"command": "ls /workspace/repo"})],
            stop_reason="tool_use",
        ),
        ProviderResponse(text="all good", stop_reason="end_turn"),
    ])
    session_id = client.post("/v1/sessions", json=session_payload).json()["session_id"]
    client.post(
        f"/v1/sessions/{session_id}/events",
        json={"events": [{"type": "user.message", "content": "explore"}]},
    )
    with client.stream("GET", f"/v1/sessions/{session_id}/stream") as r:
        assert r.status_code == 200
        seen_types = set()
        for line in r.iter_lines():
            if line.startswith("data:"):
                seen_types.add(line)
            if "session.status_idle" in line:
                break
        assert any("agent.tool_use" in s for s in seen_types)


def test_mvp_04_get_session_returns_final_state(
    client: TestClient, fake_provider: FakeProvider, session_payload: dict
) -> None:
    fake_provider.script([ProviderResponse(text="done", stop_reason="end_turn")])
    session_id = client.post("/v1/sessions", json=session_payload).json()["session_id"]
    client.post(
        f"/v1/sessions/{session_id}/events",
        json={"events": [{"type": "user.message", "content": "go"}]},
    )
    r = client.get(f"/v1/sessions/{session_id}")
    assert r.status_code == 200
    assert "events" in r.json() or "status" in r.json()


def test_mvp_05_list_sessions(
    client: TestClient, fake_provider: FakeProvider, session_payload: dict
) -> None:
    client.post("/v1/sessions", json=session_payload)
    r = client.get("/v1/sessions")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list) or "sessions" in body


def test_mvp_06_resume_session_with_new_message(
    client: TestClient, fake_provider: FakeProvider, session_payload: dict
) -> None:
    fake_provider.script([
        ProviderResponse(text="first", stop_reason="end_turn"),
        ProviderResponse(text="second", stop_reason="end_turn"),
    ])
    session_id = client.post("/v1/sessions", json=session_payload).json()["session_id"]
    r1 = client.post(
        f"/v1/sessions/{session_id}/events",
        json={"events": [{"type": "user.message", "content": "first"}]},
    )
    r2 = client.post(
        f"/v1/sessions/{session_id}/events",
        json={"events": [{"type": "user.message", "content": "second"}]},
    )
    assert r1.status_code in (200, 202)
    assert r2.status_code in (200, 202)


def test_mvp_07_delete_cleans_workspace_preserves_log(
    client: TestClient, session_payload: dict
) -> None:
    r = client.post("/v1/sessions", json=session_payload)
    data = r.json()
    session_id = data["session_id"]
    workspace = Path(data["workspace"])
    assert workspace.exists()

    r = client.delete(f"/v1/sessions/{session_id}")
    assert r.status_code in (200, 204)
    assert not workspace.exists()

    log = Path("sessions") / f"{session_id}.jsonl"
    assert log.exists(), "session log must be preserved after DELETE"


def test_mvp_08_idempotency_key_returns_same_session(
    client: TestClient, session_payload: dict
) -> None:
    headers = {"Idempotency-Key": "11111111-2222-3333-4444-555555555555"}
    r1 = client.post("/v1/sessions", json=session_payload, headers=headers)
    r2 = client.post("/v1/sessions", json=session_payload, headers=headers)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["session_id"] == r2.json()["session_id"]
