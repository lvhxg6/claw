"""Property-based tests for Gateway ↔ AgentRuntime integration.

# Feature: smartclaw-gateway-full-agent, Property 10: Health endpoint tools_count consistency
# **Validates: Requirements 2.5**
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

from smartclaw.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_tool(name: str) -> MagicMock:
    """Create a minimal mock tool with a name."""
    tool = MagicMock()
    tool.name = name
    tool.description = f"Mock tool {name}"
    return tool


def _build_health_test_app(registry: ToolRegistry) -> FastAPI:
    """Build a minimal FastAPI app with health router and mock runtime."""
    from smartclaw.gateway.routers.health import router as health_router

    @asynccontextmanager
    async def test_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        mock_runtime = MagicMock()
        mock_runtime.registry = registry
        mock_runtime.close = AsyncMock()

        app.state.runtime = mock_runtime
        app.state.registry = registry
        app.state.ready = True
        yield

    app = FastAPI(lifespan=test_lifespan)
    app.include_router(health_router)
    return app


# ---------------------------------------------------------------------------
# Property 10: Health 端点工具数量一致性
# Feature: smartclaw-gateway-full-agent, Property 10: Health endpoint tools_count consistency
# **Validates: Requirements 2.5**
# ---------------------------------------------------------------------------


class TestProperty10HealthToolsCount:
    """Health endpoint tools_count always matches runtime.registry.count."""

    @settings(max_examples=100, deadline=None)
    @given(tool_count=st.integers(min_value=0, max_value=50))
    def test_health_tools_count_matches_registry(self, tool_count: int):
        registry = ToolRegistry()
        for i in range(tool_count):
            registry.register(_make_mock_tool(f"tool_{i}"))

        app = _build_health_test_app(registry)
        with TestClient(app) as client:
            resp = client.get("/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["tools_count"] == registry.count
        assert data["tools_count"] == tool_count
