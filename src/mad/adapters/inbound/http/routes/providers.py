"""Provider endpoints — model discovery and deployment model config (issue #55)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from mad.core.orchestration.use_cases.deployment_model_config import (
    ClearDeploymentModelUseCase,
    DeploymentModelOutput,
    GetDeploymentModelUseCase,
    SetDeploymentModelInput,
    SetDeploymentModelUseCase,
)
from mad.core.orchestration.use_cases.list_provider_models import ListProviderModelsUseCase

router = APIRouter(tags=["providers"])


class ProviderModelsResponse(BaseModel):
    providers: dict[str, list[str]] = Field(
        ..., description="Provider name -> list of model identifiers available from that provider."
    )


class DeploymentModelResponse(BaseModel):
    """Current deployment-wide model default.

    ``model`` is ``null`` when no deployment model has been set — sessions
    with no override will use the provider's machine-configured default.
    """

    model: str | None = None


class SetDeploymentModelRequest(BaseModel):
    model: str = Field(..., description="Model identifier to set as the deployment-wide default.")


def _catalog(request: Request):
    return request.app.state.model_catalog


def _deployment_model_config(request: Request):
    return request.app.state.deployment_model_config


def _emitter(request: Request):
    return request.app.state.event_emitter


@router.get("/v1/providers/models", response_model=ProviderModelsResponse)
async def list_provider_models(request: Request) -> ProviderModelsResponse:
    use_case = ListProviderModelsUseCase(catalog=_catalog(request))
    output = await use_case.execute()
    return ProviderModelsResponse(providers=output.catalog)


@router.get("/v1/model", response_model=DeploymentModelResponse)
async def get_deployment_model(request: Request) -> DeploymentModelResponse:
    """Read the deployment-wide default model.

    Returns ``null`` for ``model`` when no default has been set — the provider
    uses its own machine-configured default in that case.
    """
    use_case = GetDeploymentModelUseCase(config=_deployment_model_config(request))
    output = use_case.execute()
    return DeploymentModelResponse(model=output.model)


@router.put("/v1/model", response_model=DeploymentModelResponse)
async def set_deployment_model(
    payload: SetDeploymentModelRequest,
    request: Request,
) -> DeploymentModelResponse:
    """Set the deployment-wide default model.

    Every session that has no per-session ``model`` override will use this
    default on the next launcher invocation (live inheritance — no restart
    required). Emits ``model.default.updated`` so the setting survives a
    restart via JSONL replay (hard rule 6).
    """
    use_case = SetDeploymentModelUseCase(
        config=_deployment_model_config(request),
        emitter=_emitter(request),
    )
    output: DeploymentModelOutput = await use_case.execute(
        SetDeploymentModelInput(model=payload.model)
    )
    return DeploymentModelResponse(model=output.model)


@router.delete("/v1/model", response_model=DeploymentModelResponse)
async def clear_deployment_model(request: Request) -> DeploymentModelResponse:
    """Clear the deployment-wide model default.

    After clearing, sessions with no per-session override will use the
    provider's own machine-configured default (i.e. no ``--model`` flag is
    passed). Idempotent: clearing when already unset is a no-op success.
    """
    use_case = ClearDeploymentModelUseCase(
        config=_deployment_model_config(request),
        emitter=_emitter(request),
    )
    output: DeploymentModelOutput = await use_case.execute()
    return DeploymentModelResponse(model=output.model)
