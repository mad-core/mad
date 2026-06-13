"""Integration tests for GET /v1/providers/models.

Coverage:
- Happy path: 200 with a providers object containing claude_cli with the expected static list.
- OpenAPI contract: /openapi.json declares the /v1/providers/models path.
- Negative twin: the response body must not be empty (providers must not be an empty dict).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mad.adapters.inbound.http.app import create_app
from mad.adapters.outbound.agents.model_catalog import _CLAUDE_CLI_FALLBACK
from support.launchers import ScriptedLauncher


@pytest.fixture
def providers_client(
    tmp_sessions_dir,
    tmp_workspaces_dir,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    """TestClient with opencode discovery forced to fallback (no real opencode binary)."""
    # Ensure opencode is not discovered via PATH or env var.
    monkeypatch.delenv("MAD_OPENCODE_BIN", raising=False)
    monkeypatch.setenv("PATH", "")
    return TestClient(create_app(launcher_factory=lambda _n: ScriptedLauncher()))


def test_list_provider_models_returns_200_with_providers(
    providers_client: TestClient,
) -> None:
    """GET /v1/providers/models returns 200 and a providers dict with claude_cli."""
    r = providers_client.get("/v1/providers/models")
    assert r.status_code == 200
    body = r.json()
    assert "providers" in body
    assert "claude_cli" in body["providers"]
    assert body["providers"]["claude_cli"] == list(_CLAUDE_CLI_FALLBACK)


def test_list_provider_models_providers_not_empty(
    providers_client: TestClient,
) -> None:
    """NEGATIVE TWIN: providers dict must not be empty — at least one provider must be present."""
    r = providers_client.get("/v1/providers/models")
    assert r.status_code == 200
    body = r.json()
    assert len(body["providers"]) > 0, "providers must not be empty"
    # Value-level: each provider must have a non-empty list of models.
    for provider_name, models in body["providers"].items():
        assert isinstance(models, list), f"{provider_name}: expected list, got {type(models)}"
        assert len(models) > 0, f"{provider_name}: model list must not be empty"


def test_list_provider_models_openapi_presence(
    providers_client: TestClient,
) -> None:
    """OpenAPI spec must declare the /v1/providers/models path (contract test per rule 5)."""
    spec = providers_client.get("/openapi.json").json()
    assert "/v1/providers/models" in spec["paths"], (
        "/v1/providers/models must appear in OpenAPI paths"
    )
    get_op = spec["paths"]["/v1/providers/models"].get("get")
    assert get_op is not None, "GET operation must be declared for /v1/providers/models"
    # Response 200 must reference a named component (ProviderModelsResponse).
    responses = get_op.get("responses", {})
    assert "200" in responses, "200 response must be declared"
