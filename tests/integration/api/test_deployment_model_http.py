"""HTTP integration tests for deployment model config routes (issue #55).

Endpoints under test:
- GET  /v1/model
- PUT  /v1/model
- DELETE /v1/model

Also covers:
- OpenAPI contract test for PUT /v1/model (heuristic rule 5).
- Bootstrap / persistence round-trip for DeploymentModelConfig.
- Session model 422 validation.
- Launcher model threading (ScriptedLauncher records model on each call).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mad.adapters.inbound.http.app import create_app
from mad.core.orchestration.domain.model_config import DeploymentModelConfig
from mad.core.orchestration.use_cases.deployment_model_config import (
    bootstrap_deployment_model_config,
)
from support.launchers import ScriptedLauncher
from support.sessions import FakeSessionRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _app(launcher: ScriptedLauncher | None = None) -> TestClient:
    return TestClient(create_app(launcher_factory=lambda _name: launcher or ScriptedLauncher()))


# ---------------------------------------------------------------------------
# GET /v1/model
# ---------------------------------------------------------------------------


def test_get_deployment_model_unset_returns_null(client: TestClient) -> None:
    """With no deployment model configured, model is null."""
    r = client.get("/v1/model")
    assert r.status_code == 200, r.text
    assert r.json() == {"model": None}


def test_get_deployment_model_reflects_prior_put(client: TestClient) -> None:
    """Negative twin / live state: after a PUT, GET reads the new value."""
    client.put("/v1/model", json={"model": "claude-sonnet-4-5"})
    r = client.get("/v1/model")
    assert r.status_code == 200, r.text
    assert r.json() == {"model": "claude-sonnet-4-5"}


# ---------------------------------------------------------------------------
# PUT /v1/model
# ---------------------------------------------------------------------------


def test_put_deployment_model_returns_200_and_model(client: TestClient) -> None:
    """Setting the deployment model returns 200 with the new model value."""
    r = client.put("/v1/model", json={"model": "claude-haiku-4-5"})
    assert r.status_code == 200, r.text
    assert r.json() == {"model": "claude-haiku-4-5"}


def test_put_deployment_model_missing_model_field_returns_422(client: TestClient) -> None:
    """Negative twin: omitting the required ``model`` field returns 422."""
    r = client.put("/v1/model", json={})
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# DELETE /v1/model
# ---------------------------------------------------------------------------


def test_delete_deployment_model_clears_to_null(client: TestClient) -> None:
    """After PUT then DELETE, GET reports null again."""
    client.put("/v1/model", json={"model": "opus"})
    r = client.delete("/v1/model")
    assert r.status_code == 200, r.text
    assert r.json() == {"model": None}

    r2 = client.get("/v1/model")
    assert r2.json() == {"model": None}


def test_delete_deployment_model_idempotent_when_already_null(client: TestClient) -> None:
    """Negative twin: deleting when already unset is a 200 no-op."""
    r = client.delete("/v1/model")
    assert r.status_code == 200, r.text
    assert r.json() == {"model": None}


# ---------------------------------------------------------------------------
# OpenAPI contract test for PUT /v1/model (heuristic rule 5)
# ---------------------------------------------------------------------------


def test_openapi_put_deployment_model_declares_model_field(client: TestClient) -> None:
    """PUT /v1/model must appear in the OpenAPI spec with a body schema
    that has a required ``model`` field (string)."""
    spec = client.get("/openapi.json").json()
    paths = spec.get("paths", {})
    assert "/v1/model" in paths, "PUT /v1/model route absent from OpenAPI spec"
    put_op = paths["/v1/model"].get("put", {})
    assert put_op, "PUT operation absent from /v1/model spec"
    body = put_op.get("requestBody", {})
    assert body, "PUT /v1/model has no requestBody"
    schema_ref = body["content"]["application/json"]["schema"]
    # Resolve $ref to SetDeploymentModelRequest schema
    ref = schema_ref.get("$ref", "")
    schema_name = ref.rsplit("/", 1)[-1] if ref else ""
    schema = spec["components"]["schemas"][schema_name] if schema_name else schema_ref
    assert "model" in schema.get("required", []), (
        f"'model' must be required in SetDeploymentModelRequest schema, got: {schema}"
    )
    props = schema.get("properties", {})
    assert "model" in props, f"'model' must be a property, got: {props}"


# ---------------------------------------------------------------------------
# Bootstrap / persistence round-trip
# ---------------------------------------------------------------------------


def test_bootstrap_deployment_model_config_last_write_wins() -> None:
    """Two ``model.default.updated`` events → last one wins after replay."""
    repo = FakeSessionRepository()
    from mad.core.orchestration.domain.model_config import DEPLOYMENT_MODEL_SESSION_ID

    repo.append_event(DEPLOYMENT_MODEL_SESSION_ID, "model.default.updated", {"model": "opus-first"})
    repo.append_event(DEPLOYMENT_MODEL_SESSION_ID, "model.default.updated", {"model": "haiku-last"})
    config = DeploymentModelConfig()

    bootstrap_deployment_model_config(config, repo)

    assert config.default_model == "haiku-last"


def test_bootstrap_then_cleared_leaves_none() -> None:
    """After an update followed by a clear, bootstrap results in None."""
    repo = FakeSessionRepository()
    from mad.core.orchestration.domain.model_config import DEPLOYMENT_MODEL_SESSION_ID

    repo.append_event(DEPLOYMENT_MODEL_SESSION_ID, "model.default.updated", {"model": "sonnet-mid"})
    repo.append_event(DEPLOYMENT_MODEL_SESSION_ID, "model.default.cleared", {})
    config = DeploymentModelConfig()

    bootstrap_deployment_model_config(config, repo)

    assert config.default_model is None


def test_bootstrap_missing_log_leaves_default_none() -> None:
    """Negative twin: no reserved log → default_model stays None."""
    repo = FakeSessionRepository()
    config = DeploymentModelConfig()

    bootstrap_deployment_model_config(config, repo)

    assert config.default_model is None


# ---------------------------------------------------------------------------
# Session model 422 validation
# ---------------------------------------------------------------------------


def _base_session_payload() -> dict:
    return {
        "agent": {"name": "a", "provider": "claude_cli"},
        "resources": [],
    }


def test_post_session_with_invalid_model_returns_422(client: TestClient) -> None:
    """POST /v1/sessions with an unknown model id for a known provider → 422."""
    payload = _base_session_payload()
    payload["model"] = "bogus-model-xyz"
    r = client.post("/v1/sessions", json=payload)
    assert r.status_code == 422, r.text
    assert "bogus-model-xyz" in r.text


def test_post_session_with_valid_model_does_not_422(client: TestClient) -> None:
    """Negative twin: a model in the static catalog → not 422 (session created)."""
    payload = _base_session_payload()
    payload["model"] = "opus"
    r = client.post("/v1/sessions", json=payload)
    # The static catalog contains ["opus", "sonnet", "haiku"] for claude_cli; must succeed.
    assert r.status_code == 200, r.text
    assert "session_id" in r.json()


def test_post_session_without_model_field_succeeds(client: TestClient) -> None:
    """Negative twin: no model field → session created (inherits deployment default)."""
    r = client.post("/v1/sessions", json=_base_session_payload())
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# Task-enqueue model 422 validation (FIX 6)
# ---------------------------------------------------------------------------


def test_post_task_with_invalid_model_returns_422(client: TestClient) -> None:
    """POST /v1/sessions/{id}/tasks with an unknown model for claude_cli → 422."""
    # Create the session first.
    r = client.post("/v1/sessions", json=_base_session_payload())
    assert r.status_code == 200, r.text
    session_id = r.json()["session_id"]

    r2 = client.post(
        f"/v1/sessions/{session_id}/tasks",
        json={"content": "x", "model": "bogus-model-zzz"},
    )
    assert r2.status_code == 422, r2.text


def test_post_task_with_valid_model_returns_202(client: TestClient) -> None:
    """Negative twin: ``opus`` is in the static claude_cli catalog → 202 accepted."""
    r = client.post("/v1/sessions", json=_base_session_payload())
    assert r.status_code == 200, r.text
    session_id = r.json()["session_id"]

    r2 = client.post(
        f"/v1/sessions/{session_id}/tasks",
        json={"content": "x", "model": "opus"},
    )
    assert r2.status_code == 202, r2.text


# ---------------------------------------------------------------------------
# Launcher model threading (ScriptedLauncher records model)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_message_threads_session_model_to_launcher(
    tmp_path: Path,
    tmp_sessions_dir: Path,
    tmp_workspaces_dir: Path,
) -> None:
    """Create a session with model='opus', send a message, and assert
    the ScriptedLauncher received that model on both calls (primary + auto-sync)."""
    launcher = ScriptedLauncher()
    launcher.script(
        [
            [{"type": "session.status_idle", "stop_reason": "end_turn"}],
            [{"type": "session.status_idle", "stop_reason": "end_turn"}],
        ]
    )
    c = TestClient(create_app(launcher_factory=lambda _name: launcher))

    # Create session with model override.
    payload = {
        "agent": {"name": "a", "provider": "claude_cli"},
        "resources": [],
        "model": "opus",
    }
    r = c.post("/v1/sessions", json=payload)
    assert r.status_code == 200, r.text
    session_id = r.json()["session_id"]

    # Send a message; this fires off the background launcher task.
    r2 = c.post(f"/v1/sessions/{session_id}/messages", json={"content": "go"})
    assert r2.status_code == 200, r2.text

    # Wait for both launcher calls (primary + auto-sync).
    deadline = asyncio.get_event_loop().time() + 3.0
    while len(launcher.calls) < 2 and asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.05)

    assert len(launcher.calls) >= 1, "Launcher must have been called at least once"
    for call in launcher.calls:
        assert call["model"] == "opus", f"Expected model='opus' on all launcher calls, got: {call}"


@pytest.mark.asyncio
async def test_send_message_passes_none_model_when_no_model_set(
    tmp_path: Path,
    tmp_sessions_dir: Path,
    tmp_workspaces_dir: Path,
) -> None:
    """Negative twin: no model at any level → launcher receives model=None."""
    launcher = ScriptedLauncher()
    launcher.script(
        [
            [{"type": "session.status_idle", "stop_reason": "end_turn"}],
            [{"type": "session.status_idle", "stop_reason": "end_turn"}],
        ]
    )
    c = TestClient(create_app(launcher_factory=lambda _name: launcher))

    # Session without model.
    payload = {
        "agent": {"name": "a", "provider": "claude_cli"},
        "resources": [],
    }
    r = c.post("/v1/sessions", json=payload)
    assert r.status_code == 200, r.text
    session_id = r.json()["session_id"]

    r2 = c.post(f"/v1/sessions/{session_id}/messages", json={"content": "go"})
    assert r2.status_code == 200, r2.text

    deadline = asyncio.get_event_loop().time() + 3.0
    while len(launcher.calls) < 1 and asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.05)

    assert len(launcher.calls) >= 1
    for call in launcher.calls:
        assert call["model"] is None, f"Expected model=None on all launcher calls, got: {call}"
