"""Shared fixtures for gateway tests.

Provides a TestClient with mocked Agent Graph invoke() to avoid real LLM calls.
Uses app.state injection to bypass real LLM/DB initialization.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from smartclaw.agent.mode_router import ModeDecision
from smartclaw.tools.registry import ToolRegistry


def _make_mock_result(iterations: int = 1) -> dict:  # type: ignore[type-arg]
    return {
        "final_answer": "Mock response",
        "iteration": iterations,
        "error": None,
        "session_key": None,
        "messages": [],
        "summary": None,
        "sub_agent_depth": None,
        "token_stats": None,
    }


def _build_test_app(
    registry: ToolRegistry,
    mock_memory: Any,
    mock_graph: Any,
    ready: bool = True,
) -> FastAPI:
    """Build a FastAPI app with pre-injected test state (no real lifespan)."""
    from smartclaw.gateway.routers.capability_packs import router as capability_packs_router
    from smartclaw.gateway.routers.chat import router as chat_router
    from smartclaw.gateway.routers.health import router as health_router
    from smartclaw.gateway.routers.sessions import router as sessions_router
    from smartclaw.gateway.routers.tools import router as tools_router

    @asynccontextmanager
    async def test_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        # Build a mock runtime that wraps the individual mocks
        mock_runtime = MagicMock()
        mock_runtime.graph = mock_graph
        mock_runtime.registry = registry
        mock_runtime.memory_store = mock_memory
        mock_runtime.system_prompt = "You are SmartClaw, a helpful AI assistant."
        mock_runtime.summarizer = None
        mock_runtime.close = AsyncMock()
        mock_runtime.tools = registry.get_all()
        mock_runtime.create_graph = MagicMock(return_value=mock_graph)
        mock_runtime.create_request_graph = MagicMock(return_value=mock_graph)
        mock_runtime.resolve_mode = MagicMock(
            return_value=ModeDecision(
                requested_mode=None,
                resolved_mode="classic",
                reason="test_default",
                confidence=1.0,
            )
        )
        mock_runtime.resolve_capability_pack = MagicMock(
            return_value=MagicMock(
                requested_name=None,
                resolved_name=None,
                reason="test_default",
                pack=None,
            )
        )
        mock_runtime.capability_registry = MagicMock()
        mock_runtime.capability_registry.list_names = MagicMock(return_value=[])
        mock_runtime.capability_registry.get = MagicMock(return_value=None)
        mock_runtime.compose_system_prompt = MagicMock(return_value=mock_runtime.system_prompt)
        mock_runtime.build_capability_policy = MagicMock(return_value=None)

        from smartclaw.providers.config import ModelConfig
        mock_runtime.model_config = ModelConfig()

        app.state.runtime = mock_runtime
        # Backward compatibility aliases
        app.state.registry = registry
        app.state.memory_store = mock_memory
        app.state.graph = mock_graph
        app.state.ready = ready
        yield

    app = FastAPI(title="SmartClaw API", version="0.1.0", lifespan=test_lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(chat_router)
    app.include_router(capability_packs_router)
    app.include_router(sessions_router)
    app.include_router(tools_router)
    app.include_router(health_router)
    return app


def make_test_client(
    mock_invoke_result: dict | None = None,  # type: ignore[type-arg]
    invoke_side_effect: Exception | None = None,
    tools: list | None = None,
    ready: bool = True,
) -> tuple[TestClient, AsyncMock, AsyncMock, ToolRegistry]:
    """Create a TestClient with mocked dependencies."""
    import smartclaw.agent.graph as graph_module

    # Mock memory store
    mock_memory = AsyncMock()
    mock_memory.get_history = AsyncMock(return_value=[])
    mock_memory.get_summary = AsyncMock(return_value="")
    mock_memory.set_history = AsyncMock()
    mock_memory.set_summary = AsyncMock()
    mock_memory.get_session_config = AsyncMock(return_value=None)
    mock_memory.set_session_config = AsyncMock()
    mock_memory.list_sessions = AsyncMock(return_value=[])

    # Mock graph
    mock_graph = MagicMock()

    # Registry
    registry = ToolRegistry()
    if tools:
        for t in tools:
            registry.register(t)

    # Patch invoke
    result = mock_invoke_result or _make_mock_result()
    if invoke_side_effect is not None:
        mock_invoke = AsyncMock(side_effect=invoke_side_effect)
    else:
        mock_invoke = AsyncMock(return_value=result)

    graph_module.invoke = mock_invoke  # type: ignore[assignment]

    app = _build_test_app(registry, mock_memory, mock_graph, ready=ready)
    client = TestClient(app, raise_server_exceptions=False)

    # Restore after building (TestClient uses context manager on enter)
    # Keep patch active — restore is caller's responsibility or done in fixture teardown

    return client, mock_invoke, mock_memory, registry


@pytest.fixture
def test_client():
    """Default test client with successful mock invoke."""
    import smartclaw.agent.graph as graph_module
    original_invoke = graph_module.invoke

    client, mock_invoke, mock_memory, registry = make_test_client()
    yield client, mock_invoke, mock_memory, registry

    graph_module.invoke = original_invoke  # type: ignore[assignment]


@pytest.fixture
def test_client_error():
    """Test client where invoke raises RuntimeError."""
    import smartclaw.agent.graph as graph_module
    original_invoke = graph_module.invoke

    client, mock_invoke, mock_memory, registry = make_test_client(
        invoke_side_effect=RuntimeError("LLM failure")
    )
    yield client, mock_invoke, mock_memory, registry

    graph_module.invoke = original_invoke  # type: ignore[assignment]


@pytest.fixture
def test_client_not_ready():
    """Test client where app is not ready."""
    import smartclaw.agent.graph as graph_module
    original_invoke = graph_module.invoke

    client, mock_invoke, mock_memory, registry = make_test_client(ready=False)
    yield client, mock_invoke, mock_memory, registry

    graph_module.invoke = original_invoke  # type: ignore[assignment]
