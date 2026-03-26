"""Models router — GET/PUT /api/models for model switching."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api/models", tags=["models"])


class ModelInfo(BaseModel):
    """Current model information."""
    primary: str
    fallbacks: list[str]
    available: list[str]
    is_busy: bool


class SwitchModelRequest(BaseModel):
    """Request body for switching model."""
    model: str


class SwitchModelResponse(BaseModel):
    """Response for model switch operation."""
    success: bool
    message: str
    current_model: str


@router.get("", response_model=ModelInfo)
async def get_models(request: Request) -> ModelInfo:
    """Return current model configuration and available models."""
    runtime = request.app.state.runtime
    model_config = runtime.model_config

    # Get all registered providers
    from smartclaw.providers.factory import ProviderFactory
    available = list(runtime.get_available_models())

    return ModelInfo(
        primary=model_config.primary,
        fallbacks=list(model_config.fallbacks),
        available=available,
        is_busy=runtime.is_busy,
    )


@router.put("", response_model=SwitchModelResponse)
async def switch_model(request: Request, body: SwitchModelRequest) -> SwitchModelResponse:
    """Switch the primary model.

    Returns 409 Conflict if there are active requests.
    Returns 400 Bad Request if the model format is invalid.
    """
    runtime = request.app.state.runtime

    if runtime.is_busy:
        raise HTTPException(
            status_code=409,
            detail="Cannot switch model while requests are in progress",
        )

    success = await runtime.switch_model(body.model)

    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to switch to model '{body.model}'. Check if the provider is valid.",
        )

    return SwitchModelResponse(
        success=True,
        message=f"Switched to {body.model}",
        current_model=runtime.model_config.primary,
    )
