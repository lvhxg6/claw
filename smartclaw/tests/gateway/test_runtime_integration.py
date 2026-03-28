"""Integration tests for Gateway ↔ AgentRuntime integration.

Tests that lifespan sets up runtime, chat passes system_prompt/summarizer,
and shutdown calls runtime.close().
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage

from smartclaw.agent.mode_router import ModeDecision
from smartclaw.agent.runtime import AgentRuntime
from smartclaw.capabilities.models import CapabilityResolution
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

    def test_chat_passes_approved_flag_to_invoke(self):
        import smartclaw.agent.graph as graph_module
        original_invoke = graph_module.invoke

        try:
            client, mock_invoke, _, _ = make_test_client()

            with client:
                resp = client.post("/api/chat", json={"message": "hello", "approved": True})
            assert resp.status_code == 200

            mock_invoke.assert_awaited_once()
            assert mock_invoke.call_args.kwargs["approved"] is True
        finally:
            graph_module.invoke = original_invoke

    def test_chat_passes_approval_action_to_invoke(self):
        import smartclaw.agent.graph as graph_module
        original_invoke = graph_module.invoke

        try:
            client, mock_invoke, _, _ = make_test_client()

            with client:
                resp = client.post("/api/chat", json={"message": "hello", "approval_action": "report_only"})
            assert resp.status_code == 200

            mock_invoke.assert_awaited_once()
            assert mock_invoke.call_args.kwargs["approval_action"] == "report_only"
        finally:
            graph_module.invoke = original_invoke


class TestCapabilityPackEndpoints:
    """Verify gateway endpoints expose capability pack metadata for the UI."""

    def test_list_capability_packs_returns_metadata(self):
        client, _, _, _ = make_test_client()

        with client:
            runtime = client.app.state.runtime
            pack = MagicMock()
            pack.name = "security-governance"
            pack.description = "Security governance workflow"
            pack.scenario_types = ["inspection", "hardening"]
            pack.preferred_mode = "orchestrator"
            pack.task_profile = "multi_stage"
            pack.approval_required = True
            pack.schema_enforced = True
            runtime.capability_registry.list_names.return_value = ["security-governance"]
            runtime.capability_registry.get.return_value = pack

            resp = client.get("/api/capability-packs")

        assert resp.status_code == 200
        assert resp.json() == [
            {
                "name": "security-governance",
                "description": "Security governance workflow",
                "scenario_types": ["inspection", "hardening"],
                "preferred_mode": "orchestrator",
                "task_profile": "multi_stage",
                "approval_required": True,
                "schema_enforced": True,
            }
        ]

    def test_models_endpoint_returns_image_analysis_mode_and_capabilities(self):
        client, _, _, _ = make_test_client()

        with client:
            runtime = client.app.state.runtime
            runtime.get_available_models = MagicMock(
                return_value=["glm/glm-5", "kimi/kimi-k2.5"]
            )
            runtime.resolve_model_capabilities = MagicMock(
                side_effect=lambda model_ref=None, **_: {
                    "glm/glm-5": MagicMock(
                        model_dump=lambda: {"supports_vision": False, "source": "builtin_model_registry"}
                    ),
                    "kimi/kimi-k2.5": MagicMock(
                        model_dump=lambda: {"supports_vision": True, "source": "builtin_model_registry"}
                    ),
                }[model_ref or runtime.model_config.primary]
            )
            client.app.state.settings.uploads.image_analysis_mode = "vision_preferred"

            resp = client.get("/api/models")

        assert resp.status_code == 200
        payload = resp.json()
        assert payload["image_analysis_mode"] == "vision_preferred"
        assert payload["capabilities"]["glm/glm-5"]["supports_vision"] is False
        assert payload["capabilities"]["kimi/kimi-k2.5"]["supports_vision"] is True

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

    def test_session_stats_endpoint_returns_context_metrics(self):
        client, _, mock_memory, _ = make_test_client()

        with client:
            mock_memory.get_history = AsyncMock(return_value=[HumanMessage(content="hello world")])
            mock_memory.get_summary = AsyncMock(return_value="summary text")
            mock_memory.list_attachments = AsyncMock(return_value=[{"extract_text": "asset text"}])
            mock_memory.get_session_config = AsyncMock(
                return_value={
                    "config": {
                        "runtime_stats": {
                            "last_token_stats": {
                                "prompt_tokens": 10,
                                "completion_tokens": 5,
                                "total_tokens": 15,
                            }
                        }
                    }
                }
            )
            resp = client.get("/api/sessions/sess-ctx/stats")

        assert resp.status_code == 200
        payload = resp.json()
        assert payload["session_key"] == "sess-ctx"
        assert payload["message_count"] == 1
        assert payload["attachment_count"] == 1
        assert payload["context_tokens_est"] > 0
        assert payload["last_token_stats"]["total_tokens"] == 15
        assert payload["provider_cache_supported"] is False

    def test_chat_applies_capability_pack_prompt_and_graph_scope(self):
        import smartclaw.agent.graph as graph_module
        original_invoke = graph_module.invoke

        try:
            client, mock_invoke, _, _ = make_test_client()

            with client:
                runtime = client.app.state.runtime
                runtime.resolve_capability_pack.return_value = CapabilityResolution(
                    requested_name="security-governance",
                    resolved_name="security-governance",
                    reason="explicit_request",
                    pack=MagicMock(
                        preferred_mode="orchestrator",
                        task_profile="multi_stage",
                        scenario_types=["inspection"],
                    ),
                )
                runtime.resolve_mode.return_value = ModeDecision(
                    requested_mode="orchestrator",
                    resolved_mode="orchestrator",
                    reason="explicit_request",
                    confidence=1.0,
                )
                runtime.compose_system_prompt.return_value = "Prompt with capability pack"

                resp = client.post(
                    "/api/chat",
                    json={
                        "message": "执行巡检",
                        "capability_pack": "security-governance",
                    },
                )
            assert resp.status_code == 200

            runtime.create_request_graph.assert_called_once()
            graph_kwargs = runtime.create_request_graph.call_args.kwargs
            assert graph_kwargs["capability_pack"] == "security-governance"
            call_kwargs = mock_invoke.call_args
            assert call_kwargs.kwargs["system_prompt"] == "Prompt with capability pack"
            assert call_kwargs.kwargs["mode"] == "orchestrator"
        finally:
            graph_module.invoke = original_invoke

    def test_chat_requires_approval_for_governed_capability_pack(self):
        import smartclaw.agent.graph as graph_module
        original_invoke = graph_module.invoke

        try:
            client, mock_invoke, _, _ = make_test_client()

            with client:
                runtime = client.app.state.runtime
                runtime.resolve_capability_pack.return_value = CapabilityResolution(
                    requested_name="security-governance",
                    resolved_name="security-governance",
                    reason="explicit_request",
                    pack=MagicMock(
                        preferred_mode="orchestrator",
                        task_profile="multi_stage",
                        scenario_types=["inspection"],
                    ),
                )
                runtime.build_capability_policy.return_value = {
                    "approval_required": True,
                    "approval_message": "Please approve governance execution",
                }

                resp = client.post(
                    "/api/chat",
                    json={
                        "message": "执行巡检",
                        "capability_pack": "security-governance",
                    },
                )
            assert resp.status_code == 200
            payload = resp.json()
            assert payload["clarification"]["question"] == "Please approve governance execution"
            mock_invoke.assert_not_called()
        finally:
            graph_module.invoke = original_invoke

    def test_chat_stream_approval_clarification_includes_session_key(self):
        import smartclaw.agent.graph as graph_module
        original_invoke = graph_module.invoke

        try:
            client, mock_invoke, _, _ = make_test_client()

            with client:
                runtime = client.app.state.runtime
                runtime.resolve_capability_pack.return_value = CapabilityResolution(
                    requested_name="security-governance",
                    resolved_name="security-governance",
                    reason="explicit_request",
                    pack=MagicMock(
                        preferred_mode="orchestrator",
                        task_profile="multi_stage",
                        scenario_types=["inspection"],
                    ),
                )
                runtime.build_capability_policy.return_value = {
                    "approval_required": True,
                    "approval_message": "Please approve governance execution",
                }

                resp = client.post(
                    "/api/chat/stream",
                    json={
                        "message": "执行巡检",
                        "capability_pack": "security-governance",
                    },
                )
            assert resp.status_code == 200
            body = resp.text
            assert "event: clarification" in body
            assert "\"session_key\"" in body
            mock_invoke.assert_not_called()
        finally:
            graph_module.invoke = original_invoke
