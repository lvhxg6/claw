"""Integration tests for Gateway ↔ AgentRuntime integration.

Tests that lifespan sets up runtime, chat passes system_prompt/summarizer,
and shutdown calls runtime.close().
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from smartclaw.agent.runtime import AgentRuntime
from smartclaw.providers.config import ModelConfig
from smartclaw.tools.registry import ToolRegistry
from tests.gateway.conftest import make_test_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_runtime() -> AgentRuntime:
    """Create a mock AgentRuntime with all fields populated."""
    registry = ToolRegistry()
    return AgentRuntime(
        graph=MagicMock(name="compiled_graph"),
        registry=registry,
        memory_store=AsyncMock(),
        summarizer=MagicMock(name="summarizer"),
        system_prompt="Test system prompt",
        mcp_manager=None,
        model_config=ModelConfig(),
    )


# ---------------------------------------------------------------------------
# Test: lifespan calls setup_agent_runtime and stores runtime
# ---------------------------------------------------------------------------

class TestLifespanSetsRuntime:
    """Verify lifespan() calls setup_agent_runtime and populates app.state."""

    def test_lifespan_sets_runtime(self):
        mock_runtime = _make_mock_runtime()
        mock_runtime.close = AsyncMock()

        with patch("smartclaw.agent.runtime.setup_agent_runtime", new_callable=AsyncMock) as mock_setup:
            mock_setup.return_value = mock_runtime

            with patch("smartclaw.hooks.registry.register"), \
                 patch("smartclaw.hooks.registry.unregister"), \
                 patch("smartclaw.hooks.registry.VALID_HOOK_POINTS", []):

                from smartclaw.gateway.app import lifespan

                @asynccontextmanager
                async def patched_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
                    async with lifespan(app):
                        yield

                app = FastAPI(lifespan=patched_lifespan)
                with TestClient(app):
                    assert hasattr(app.state, "runtime")
                    assert app.state.runtime is mock_runtime
                    assert app.state.graph is mock_runtime.graph
                    assert app.state.registry is mock_runtime.registry
                    assert app.state.memory_store is mock_runtime.memory_store

    def test_shutdown_calls_runtime_close(self):
        mock_runtime = _make_mock_runtime()
        mock_runtime.close = AsyncMock()

        with patch("smartclaw.agent.runtime.setup_agent_runtime", new_callable=AsyncMock) as mock_setup:
            mock_setup.return_value = mock_runtime

            with patch("smartclaw.hooks.registry.register"), \
                 patch("smartclaw.hooks.registry.unregister"), \
                 patch("smartclaw.hooks.registry.VALID_HOOK_POINTS", []):

                from smartclaw.gateway.app import lifespan

                @asynccontextmanager
                async def patched_lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
                    async with lifespan(app):
                        yield

                app = FastAPI(lifespan=patched_lifespan)
                with TestClient(app):
                    pass

                mock_runtime.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# Test: chat passes system_prompt and summarizer to invoke
# ---------------------------------------------------------------------------

class TestChatPassesRuntimeParams:
    """Verify chat() and chat_stream() pass system_prompt and summarizer."""

    def test_chat_passes_system_prompt_and_summarizer(self):
        import smartclaw.agent.graph as graph_module
        original_invoke = graph_module.invoke

        try:
            client, mock_invoke, _, _ = make_test_client()

            with client:
                resp = client.post("/api/chat", json={"message": "hello"})
            assert resp.status_code == 200

            mock_invoke.assert_awaited_once()
            call_kwargs = mock_invoke.call_args
            assert "system_prompt" in call_kwargs.kwargs
            assert call_kwargs.kwargs["system_prompt"] is not None
            assert "summarizer" in call_kwargs.kwargs
        finally:
            graph_module.invoke = original_invoke

    def test_chat_stream_passes_system_prompt_and_summarizer(self):
        import smartclaw.agent.graph as graph_module
        original_invoke = graph_module.invoke

        try:
            client, mock_invoke, _, _ = make_test_client()

            with client:
                resp = client.post("/api/chat/stream", json={"message": "hello"})
            assert resp.status_code == 200

            mock_invoke.assert_awaited_once()
            call_kwargs = mock_invoke.call_args
            assert "system_prompt" in call_kwargs.kwargs
            assert call_kwargs.kwargs["system_prompt"] is not None
            assert "summarizer" in call_kwargs.kwargs
        finally:
            graph_module.invoke = original_invoke
