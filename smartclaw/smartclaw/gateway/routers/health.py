"""Health router — GET /health, GET /ready."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from smartclaw.gateway.models import HealthResponse

router = APIRouter(tags=["health"])

_VERSION = "0.1.0"


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Return service health information."""
    registry = request.app.state.registry
    return HealthResponse(
        status="ok",
        version=_VERSION,
        tools_count=registry.count,
    )


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Return 200 if ready, 503 if not."""
    is_ready = getattr(request.app.state, "ready", False)
    if is_ready:
        return JSONResponse({"status": "ready"}, status_code=200)
    return JSONResponse({"status": "not ready"}, status_code=503)
