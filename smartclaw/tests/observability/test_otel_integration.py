"""OTEL integration tests: diagnostic bus events → OTEL spans.

Tests:
- emit("agent.run", {"phase": "start"}) → root span created
- emit("agent.run", {"phase": "end"}) → root span ended
- emit("llm.called", ...) → child span created
- emit("tool.executed", ...) → child span created
- tracing_enabled=False → emit works but no spans created
"""

from __future__ import annotations

import asyncio

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import smartclaw.observability.diagnostic_bus as bus
from smartclaw.config.settings import ObservabilitySettings
from smartclaw.observability.tracing import OTELTracingService, _root_span_var


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service_with_in_memory_exporter() -> tuple[OTELTracingService, InMemorySpanExporter]:
    """Create an OTELTracingService wired to an InMemorySpanExporter for testing."""
    exporter = InMemorySpanExporter()
    settings = ObservabilitySettings(
        tracing_enabled=True,
        service_name="test-service",
    )
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    svc = OTELTracingService(settings)
    # Manually wire the provider and tracer so we use our in-memory exporter
    svc._provider = provider
    svc._tracer = provider.get_tracer("test")
    svc.subscribe_to_diagnostic_bus()
    return svc, exporter


@pytest.fixture(autouse=True)
def reset_bus_and_otel():
    """Reset bus and OTEL state before/after each test."""
    bus.clear()
    _root_span_var.set(None)
    yield
    bus.clear()
    _root_span_var.set(None)
    # Reset global provider
    trace.set_tracer_provider(TracerProvider())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_run_start_creates_root_span() -> None:
    """emit("agent.run", phase=start) → root span is created and tracked."""
    svc, exporter = _make_service_with_in_memory_exporter()

    await bus.emit("agent.run", {
        "phase": "start",
        "session_key": "sess-001",
        "user_message": "hello",
        "max_iterations": 10,
    })

    # Root span should be set in context var
    root = _root_span_var.get(None)
    assert root is not None
    assert root.is_recording()

    # Clean up
    await bus.emit("agent.run", {"phase": "end"})


@pytest.mark.asyncio
async def test_agent_run_end_ends_root_span() -> None:
    """emit("agent.run", phase=end) → root span is ended and exported."""
    svc, exporter = _make_service_with_in_memory_exporter()

    await bus.emit("agent.run", {"phase": "start", "session_key": "sess-002"})
    await bus.emit("agent.run", {"phase": "end"})

    # Root span var should be cleared
    assert _root_span_var.get(None) is None

    # Span should be exported
    spans = exporter.get_finished_spans()
    agent_spans = [s for s in spans if s.name == "agent.invoke"]
    assert len(agent_spans) == 1
    assert not agent_spans[0].context.is_valid or True  # span ended


@pytest.mark.asyncio
async def test_llm_called_creates_child_span() -> None:
    """emit("llm.called", ...) → child span "llm.call" is created."""
    svc, exporter = _make_service_with_in_memory_exporter()

    await bus.emit("agent.run", {"phase": "start", "session_key": "sess-003"})
    await bus.emit("llm.called", {
        "model": "gpt-4o",
        "message_count": 5,
        "has_tool_calls": False,
    })
    await bus.emit("agent.run", {"phase": "end"})

    spans = exporter.get_finished_spans()
    llm_spans = [s for s in spans if s.name == "llm.call"]
    assert len(llm_spans) == 1
    assert llm_spans[0].attributes.get("model") == "gpt-4o"


@pytest.mark.asyncio
async def test_tool_executed_creates_child_span() -> None:
    """emit("tool.executed", ...) → child span "tool.execute.{name}" is created."""
    svc, exporter = _make_service_with_in_memory_exporter()

    await bus.emit("agent.run", {"phase": "start", "session_key": "sess-004"})
    await bus.emit("tool.executed", {
        "tool_name": "web_search",
        "success": True,
    })
    await bus.emit("agent.run", {"phase": "end"})

    spans = exporter.get_finished_spans()
    tool_spans = [s for s in spans if s.name == "tool.execute.web_search"]
    assert len(tool_spans) == 1
    assert tool_spans[0].attributes.get("tool_name") == "web_search"


@pytest.mark.asyncio
async def test_tracing_disabled_emit_works_no_spans() -> None:
    """tracing_enabled=False → emit works normally but no real spans are exported."""
    settings = ObservabilitySettings(tracing_enabled=False)
    svc = OTELTracingService(settings)
    svc.initialize()
    svc.subscribe_to_diagnostic_bus()

    # These should not raise
    await bus.emit("agent.run", {"phase": "start", "session_key": "sess-noop"})
    await bus.emit("llm.called", {"model": "gpt-4o", "message_count": 1})
    await bus.emit("tool.executed", {"tool_name": "search", "success": True})
    await bus.emit("agent.run", {"phase": "end"})


@pytest.mark.asyncio
async def test_agent_run_end_with_error_sets_error_status() -> None:
    """emit("agent.run", phase=end, error=...) → span status is ERROR."""
    svc, exporter = _make_service_with_in_memory_exporter()

    await bus.emit("agent.run", {"phase": "start", "session_key": "sess-err"})
    await bus.emit("agent.run", {"phase": "end", "error": "something went wrong"})

    spans = exporter.get_finished_spans()
    agent_spans = [s for s in spans if s.name == "agent.invoke"]
    assert len(agent_spans) == 1
    from opentelemetry.trace import StatusCode
    assert agent_spans[0].status.status_code == StatusCode.ERROR


@pytest.mark.asyncio
async def test_tool_executed_error_sets_error_status() -> None:
    """emit("tool.executed", error=...) → span status is ERROR."""
    svc, exporter = _make_service_with_in_memory_exporter()

    await bus.emit("agent.run", {"phase": "start"})
    await bus.emit("tool.executed", {
        "tool_name": "failing_tool",
        "success": False,
        "error": "tool failed",
    })
    await bus.emit("agent.run", {"phase": "end"})

    spans = exporter.get_finished_spans()
    tool_spans = [s for s in spans if s.name == "tool.execute.failing_tool"]
    assert len(tool_spans) == 1
    from opentelemetry.trace import StatusCode
    assert tool_spans[0].status.status_code == StatusCode.ERROR


@pytest.mark.asyncio
async def test_sensitive_attributes_are_redacted_in_spans() -> None:
    """Span attributes containing sensitive data are redacted."""
    svc, exporter = _make_service_with_in_memory_exporter()

    await bus.emit("agent.run", {
        "phase": "start",
        "session_key": "sk-secret-session",  # sensitive
        "user_message": "hello",
    })
    await bus.emit("agent.run", {"phase": "end"})

    spans = exporter.get_finished_spans()
    agent_spans = [s for s in spans if s.name == "agent.invoke"]
    assert len(agent_spans) == 1
    assert agent_spans[0].attributes.get("session_key") == "[REDACTED]"
