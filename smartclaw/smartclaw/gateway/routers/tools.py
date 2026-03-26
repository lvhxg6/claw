"""Tools router — GET /api/tools."""

from __future__ import annotations

from fastapi import APIRouter, Request

from smartclaw.gateway.models import ToolInfo

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("", response_model=list[ToolInfo])
async def list_tools(request: Request) -> list[ToolInfo]:
    """Return all tools registered in the ToolRegistry."""
    registry = request.app.state.registry
    tools = registry.get_all()
    return [ToolInfo(name=t.name, description=t.description or "") for t in tools]
