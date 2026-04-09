"""Backward compatibility integration tests for P2A modules.

Verifies that:
- All P2A disabled → invoke() behavior identical to P1 (Req 20.1)
- SmartClawSettings P0/P1 fields unchanged (Req 20.2)
- P2A new fields default to disabled, compatible with existing YAML (Req 20.3)
- Hook system available in CLI mode (no gateway needed) (Req 20.4)
- Diagnostic event system available without OTEL configured (Req 20.5)

Requirements: 20.1, 20.2, 20.3, 20.4, 20.5
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clear_smartclaw_env() -> dict[str, str]:
    saved: dict[str, str] = {}
    for k in list(os.environ):
        if k.startswith("SMARTCLAW_"):
            saved[k] = os.environ.pop(k)
    return saved


def _restore_env(saved: dict[str, str]) -> None:
    for k in list(os.environ):
        if k.startswith("SMARTCLAW_"):
            del os.environ[k]
    for k, v in saved.items():
        os.environ[k] = v


# ---------------------------------------------------------------------------
# Test 1: All P2A disabled → invoke() behavior identical to P1 (Req 20.1)
# ---------------------------------------------------------------------------


class TestAllP2ADisabledInvokeIdentical:
    """When gateway.enabled=False and tracing_enabled=False, invoke() works normally."""

    def setup_method(self) -> None:
        self._saved = _clear_smartclaw_env()

    def teardown_method(self) -> None:
        _restore_env(self._saved)

    @pytest.mark.asyncio
    async def test_invoke_works_with_p2a_disabled(self) -> None:
        """invoke() returns correct AgentState when all P2A settings are disabled."""
        from smartclaw.agent.graph import invoke
        from smartclaw.agent.state import AgentState
        from smartclaw.config.settings import SmartClawSettings

        # Confirm P2A is disabled
        s = SmartClawSettings()
        assert s.gateway.enabled is False
        assert s.observability.tracing_enabled is False

        mock_result: AgentState = {
            "messages": [HumanMessage(content="hello"), AIMessage(content="world")],
            "iteration": 1,
            "max_iterations": 50,
            "final_answer": "world",
            "error": None,
            "session_key": None,
            "summary": None,
            "sub_agent_depth": None,
        }
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(return_value=mock_result)

        result = await invoke(mock_graph, "hello")

        assert result["final_answer"] == "world"
        assert result["error"] is None
        mock_graph.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_invoke_with_session_key_works_p2a_disabled(self) -> None:
        """invoke() with session_key still works when P2A is disabled."""
        from smartclaw.agent.graph import invoke
        from smartclaw.agent.state import AgentState

        mock_result: AgentState = {
            "messages": [HumanMessage(content="hi"), AIMessage(content="there")],
            "iteration": 2,
            "max_iterations": 50,
            "final_answer": "there",
            "error": None,
            "session_key": "test-session",
            "summary": None,
            "sub_agent_depth": None,
        }
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(return_value=mock_result)

        # Minimal memory_store mock
        mock_memory = MagicMock()
        mock_memory.get_history = AsyncMock(return_value=[])
        mock_memory.add_full_message = AsyncMock()

        result = await invoke(mock_graph, "hi", session_key="test-session", memory_store=mock_memory)

        assert result["final_answer"] == "there"
        assert result["session_key"] == "test-session"

    @pytest.mark.asyncio
    async def test_invoke_hook_exceptions_do_not_break_execution(self) -> None:
        """Even if hook triggers raise, invoke() completes normally (P2A non-blocking)."""
        import smartclaw.hooks.registry as hook_registry
        from smartclaw.agent.graph import invoke
        from smartclaw.agent.state import AgentState

        # Register a hook that raises
        async def bad_hook(event: Any) -> None:
            raise RuntimeError("hook failure")

        hook_registry.register("agent:start", bad_hook)
        hook_registry.register("agent:end", bad_hook)

        try:
            mock_result: AgentState = {
                "messages": [AIMessage(content="ok")],
                "iteration": 1,
                "max_iterations": 50,
                "final_answer": "ok",
                "error": None,
                "session_key": None,
                "summary": None,
                "sub_agent_depth": None,
            }
            mock_graph = MagicMock()
            mock_graph.ainvoke = AsyncMock(return_value=mock_result)

            result = await invoke(mock_graph, "test")
            assert result["final_answer"] == "ok"
        finally:
            hook_registry.clear()


# ---------------------------------------------------------------------------
# Test 2: SmartClawSettings P0/P1 fields unchanged (Req 20.2)
# ---------------------------------------------------------------------------


class TestSmartClawSettingsP0P1FieldsUnchanged:
    """P0 and P1 fields on SmartClawSettings are not modified by P2A additions."""

    def setup_method(self) -> None:
        self._saved = _clear_smartclaw_env()

    def teardown_method(self) -> None:
        _restore_env(self._saved)

    def test_p0_fields_present_and_correct(self) -> None:
        """All P0 fields have correct defaults after P2A additions."""
        from smartclaw.config.settings import SmartClawSettings

        s = SmartClawSettings()
        # P0 agent_defaults
        assert s.agent_defaults.max_tokens == 32768
        assert s.agent_defaults.max_tool_iterations == 50
        assert s.agent_defaults.workspace == "~/.smartclaw/workspace"
        # P0 logging
        assert s.logging.level == "INFO"
        assert s.logging.format == "console"
        assert s.logging.file is None
        # P0 credentials
        assert s.credentials.keyring_service == "smartclaw"

    def test_p1_fields_present_and_correct(self) -> None:
        """All P1 fields have correct defaults after P2A additions."""
        from smartclaw.config.settings import SmartClawSettings

        s = SmartClawSettings()
        # P1 memory
        assert s.memory.enabled is True
        assert s.memory.db_path == "~/.smartclaw/memory.db"
        # P1 skills
        assert s.skills.enabled is True
        # P1 sub_agent
        assert s.sub_agent.enabled is True
        assert s.sub_agent.max_depth == 3
        assert s.sub_agent.max_concurrent == 5

    def test_p0_field_types_unchanged(self) -> None:
        """P0 field types are exactly the same as before P2A."""
        from smartclaw.config.settings import (
            AgentDefaultsSettings,
            CredentialSettings,
            LoggingSettings,
            SmartClawSettings,
        )

        s = SmartClawSettings()
        assert isinstance(s.agent_defaults, AgentDefaultsSettings)
        assert isinstance(s.logging, LoggingSettings)
        assert isinstance(s.credentials, CredentialSettings)

    def test_p1_field_types_unchanged(self) -> None:
        """P1 field types are exactly the same as before P2A."""
        from smartclaw.config.settings import (
            MemorySettings,
            SkillsSettings,
            SmartClawSettings,
            SubAgentSettings,
        )

        s = SmartClawSettings()
        assert isinstance(s.memory, MemorySettings)
        assert isinstance(s.skills, SkillsSettings)
        assert isinstance(s.sub_agent, SubAgentSettings)

    def test_agent_state_p0_p1_fields_unchanged(self) -> None:
        """AgentState still has all P0 and P1 fields."""
        from smartclaw.agent.state import AgentState

        annotations = AgentState.__annotations__
        # P0 fields
        assert "messages" in annotations
        assert "iteration" in annotations
        assert "max_iterations" in annotations
        assert "final_answer" in annotations
        assert "error" in annotations
        # P1 fields
        assert "session_key" in annotations
        assert "summary" in annotations
        assert "sub_agent_depth" in annotations


# ---------------------------------------------------------------------------
# Test 3: P2A new fields default to disabled, compatible with existing YAML (Req 20.3)
# ---------------------------------------------------------------------------


class TestP2ANewFieldsDefaultDisabled:
    """P2A new fields default to disabled and are compatible with existing YAML configs."""

    def setup_method(self) -> None:
        self._saved = _clear_smartclaw_env()

    def teardown_method(self) -> None:
        _restore_env(self._saved)

    def test_gateway_enabled_defaults_false(self) -> None:
        """gateway.enabled defaults to False."""
        from smartclaw.config.settings import SmartClawSettings

        s = SmartClawSettings()
        assert s.gateway.enabled is False

    def test_observability_tracing_enabled_defaults_false(self) -> None:
        """observability.tracing_enabled defaults to False."""
        from smartclaw.config.settings import SmartClawSettings

        s = SmartClawSettings()
        assert s.observability.tracing_enabled is False

    def test_gateway_settings_all_defaults(self) -> None:
        """GatewaySettings has correct defaults."""
        from smartclaw.config.settings import GatewaySettings

        g = GatewaySettings()
        assert g.enabled is False
        # Security: Default to localhost only to prevent accidental public exposure
        assert g.host == "127.0.0.1"
        assert g.port == 8000
        # Security: Default to localhost only, not wildcard
        assert g.cors_origins == ["http://localhost:8000", "http://127.0.0.1:8000"]
        assert g.shutdown_timeout == 30
        assert g.reload_interval == 5

    def test_observability_settings_all_defaults(self) -> None:
        """ObservabilitySettings has correct defaults."""
        from smartclaw.config.settings import ObservabilitySettings

        o = ObservabilitySettings()
        assert o.tracing_enabled is False
        assert o.otlp_endpoint == "http://localhost:4318"
        assert o.otlp_protocol == "http/protobuf"
        assert o.service_name == "smartclaw"
        assert o.sample_rate == 1.0
        assert o.redact_sensitive is True

    def test_p2a_fields_present_on_smartclaw_settings(self) -> None:
        """SmartClawSettings has gateway and observability fields."""
        from smartclaw.config.settings import (
            GatewaySettings,
            ObservabilitySettings,
            SmartClawSettings,
        )

        s = SmartClawSettings()
        assert hasattr(s, "gateway")
        assert hasattr(s, "observability")
        assert isinstance(s.gateway, GatewaySettings)
        assert isinstance(s.observability, ObservabilitySettings)

    def test_settings_without_p2a_yaml_keys_still_works(self) -> None:
        """SmartClawSettings loads fine even when no P2A keys are in environment (simulates old YAML)."""
        # No SMARTCLAW_GATEWAY__ or SMARTCLAW_OBSERVABILITY__ env vars set
        from smartclaw.config.settings import SmartClawSettings

        s = SmartClawSettings()
        # P2A fields get their defaults
        assert s.gateway.enabled is False
        assert s.observability.tracing_enabled is False
        # P0/P1 fields still work
        assert s.agent_defaults.max_tokens == 32768
        assert s.memory.enabled is True


# ---------------------------------------------------------------------------
# Test 4: Hook system available in CLI mode (Req 20.4)
# ---------------------------------------------------------------------------


class TestHookSystemAvailableInCLIMode:
    """Hook system works without gateway running."""

    def setup_method(self) -> None:
        import smartclaw.hooks.registry as hook_registry
        hook_registry.clear()

    def teardown_method(self) -> None:
        import smartclaw.hooks.registry as hook_registry
        hook_registry.clear()

    def test_hook_registry_importable_without_gateway(self) -> None:
        """Hook registry can be imported without fastapi/gateway installed."""
        import smartclaw.hooks.registry as hook_registry
        assert hook_registry is not None
        assert callable(hook_registry.register)
        assert callable(hook_registry.trigger)

    def test_hook_events_importable_without_gateway(self) -> None:
        """Hook events can be imported without gateway."""
        from smartclaw.hooks.events import (
            AgentEndEvent,
            AgentStartEvent,
            HookEvent,
            LLMAfterEvent,
            LLMBeforeEvent,
            SessionEndEvent,
            SessionStartEvent,
            ToolAfterEvent,
            ToolBeforeEvent,
        )
        assert HookEvent is not None
        assert ToolBeforeEvent is not None
        assert AgentStartEvent is not None

    @pytest.mark.asyncio
    async def test_register_and_trigger_hook_in_cli_mode(self) -> None:
        """Can register and trigger hooks without gateway running."""
        import smartclaw.hooks.registry as hook_registry
        from smartclaw.hooks.events import AgentStartEvent

        received: list[Any] = []

        async def my_handler(event: Any) -> None:
            received.append(event)

        hook_registry.register("agent:start", my_handler)

        event = AgentStartEvent(session_key=None, user_message="test", tools_count=0)
        await hook_registry.trigger("agent:start", event)

        assert len(received) == 1
        assert received[0].user_message == "test"

    @pytest.mark.asyncio
    async def test_unregister_hook_in_cli_mode(self) -> None:
        """Can unregister hooks in CLI mode."""
        import smartclaw.hooks.registry as hook_registry
        from smartclaw.hooks.events import AgentEndEvent

        received: list[Any] = []

        async def my_handler(event: Any) -> None:
            received.append(event)

        hook_registry.register("agent:end", my_handler)
        hook_registry.unregister("agent:end", my_handler)

        event = AgentEndEvent(session_key=None, final_answer="done", iterations=1, error=None)
        await hook_registry.trigger("agent:end", event)

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_multiple_hook_points_in_cli_mode(self) -> None:
        """Multiple hook points work independently in CLI mode."""
        import smartclaw.hooks.registry as hook_registry
        from smartclaw.hooks.events import LLMAfterEvent, LLMBeforeEvent

        before_calls: list[Any] = []
        after_calls: list[Any] = []

        async def before_handler(event: Any) -> None:
            before_calls.append(event)

        async def after_handler(event: Any) -> None:
            after_calls.append(event)

        hook_registry.register("llm:before", before_handler)
        hook_registry.register("llm:after", after_handler)

        await hook_registry.trigger("llm:before", LLMBeforeEvent(model="gpt-4", message_count=3, has_tools=True))
        await hook_registry.trigger("llm:after", LLMAfterEvent(model="gpt-4", has_tool_calls=False, duration_ms=100.0, error=None))

        assert len(before_calls) == 1
        assert len(after_calls) == 1


# ---------------------------------------------------------------------------
# Test 5: Diagnostic event system available without OTEL (Req 20.5)
# ---------------------------------------------------------------------------


class TestDiagnosticEventSystemWithoutOTEL:
    """Diagnostic event system works without tracing_enabled=True."""

    def setup_method(self) -> None:
        from smartclaw.observability import diagnostic_bus
        diagnostic_bus.clear()

    def teardown_method(self) -> None:
        from smartclaw.observability import diagnostic_bus
        diagnostic_bus.clear()

    def test_diagnostic_bus_importable_without_otel(self) -> None:
        """Diagnostic bus can be imported without opentelemetry configured."""
        from smartclaw.observability import diagnostic_bus
        assert diagnostic_bus is not None
        assert callable(diagnostic_bus.emit)
        assert callable(diagnostic_bus.on)
        assert callable(diagnostic_bus.off)

    @pytest.mark.asyncio
    async def test_emit_without_otel_subscriber(self) -> None:
        """emit() works normally when no OTEL subscriber is registered."""
        from smartclaw.observability import diagnostic_bus

        # No subscribers at all — should not raise
        await diagnostic_bus.emit("agent.run", {"phase": "start", "session_key": None})
        await diagnostic_bus.emit("tool.executed", {"tool_name": "search", "duration_ms": 10.0})
        await diagnostic_bus.emit("llm.called", {"model": "gpt-4", "duration_ms": 200.0})

    @pytest.mark.asyncio
    async def test_non_otel_subscriber_receives_events_without_otel(self) -> None:
        """Non-OTEL subscribers receive events even when tracing is disabled."""
        from smartclaw.observability import diagnostic_bus

        received: list[tuple[str, dict]] = []

        async def my_subscriber(event_type: str, payload: dict) -> None:
            received.append((event_type, payload))

        diagnostic_bus.on("tool.executed", my_subscriber)

        await diagnostic_bus.emit("tool.executed", {"tool_name": "read_file", "duration_ms": 5.0})

        assert len(received) == 1
        assert received[0][0] == "tool.executed"
        assert received[0][1]["tool_name"] == "read_file"

    @pytest.mark.asyncio
    async def test_on_off_without_otel(self) -> None:
        """on/off registration works without OTEL configured."""
        from smartclaw.observability import diagnostic_bus

        received: list[Any] = []

        async def subscriber(event_type: str, payload: dict) -> None:
            received.append(payload)

        diagnostic_bus.on("session.started", subscriber)
        await diagnostic_bus.emit("session.started", {"session_key": "abc"})
        assert len(received) == 1

        diagnostic_bus.off("session.started", subscriber)
        await diagnostic_bus.emit("session.started", {"session_key": "xyz"})
        assert len(received) == 1  # no new events after off

    @pytest.mark.asyncio
    async def test_emit_all_supported_event_types_without_otel(self) -> None:
        """All supported event types can be emitted without OTEL."""
        from smartclaw.observability import diagnostic_bus

        event_types = [
            "tool.executed",
            "llm.called",
            "agent.run",
            "session.started",
            "session.ended",
            "config.reloaded",
        ]
        for et in event_types:
            # Should not raise even with no subscribers
            await diagnostic_bus.emit(et, {"test": True})

    @pytest.mark.asyncio
    async def test_tracing_disabled_otel_service_uses_noop(self) -> None:
        """When tracing_enabled=False, OTELTracingService uses NoOp provider."""
        from smartclaw.config.settings import ObservabilitySettings
        from smartclaw.observability.tracing import OTELTracingService

        settings = ObservabilitySettings(tracing_enabled=False)
        service = OTELTracingService(settings)
        service.initialize()

        # With NoOp provider, get_tracer should return a no-op tracer
        from opentelemetry import trace
        tracer = trace.get_tracer("test")
        with tracer.start_as_current_span("test-span") as span:
            # NoOp span — should not raise
            assert span is not None

        service.shutdown()
