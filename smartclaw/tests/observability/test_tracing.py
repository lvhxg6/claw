"""Unit tests for OTELTracingService.

Tests:
- tracing_enabled=False → NoOp TracerProvider (no spans exported)
- initialize() with tracing_enabled=True creates real TracerProvider
- subscribe_to_diagnostic_bus() registers subscribers
- shutdown() can be called without error
"""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

import smartclaw.observability.diagnostic_bus as bus
from smartclaw.config.settings import ObservabilitySettings
from smartclaw.observability.tracing import OTELTracingService, setup_tracing


@pytest.fixture(autouse=True)
def reset_bus():
    """Clear diagnostic bus subscribers before/after each test."""
    bus.clear()
    yield
    bus.clear()


@pytest.fixture(autouse=True)
def reset_otel():
    """Reset the global OTEL tracer provider after each test."""
    yield
    # Reset to no-op after test
    from opentelemetry.sdk.trace import TracerProvider as _TP
    trace.set_tracer_provider(_TP())


class TestOTELTracingServiceInit:
    def test_tracing_disabled_uses_noop(self) -> None:
        """tracing_enabled=False → service initialises without a real provider."""
        settings = ObservabilitySettings(tracing_enabled=False)
        svc = OTELTracingService(settings)
        svc.initialize()
        # _provider should be None (no real provider set up)
        assert svc._provider is None

    def test_tracing_enabled_creates_real_provider(self) -> None:
        """tracing_enabled=True → a real TracerProvider is created."""
        settings = ObservabilitySettings(
            tracing_enabled=True,
            otlp_endpoint="http://localhost:4318",
            otlp_protocol="http/protobuf",
        )
        svc = OTELTracingService(settings)
        svc.initialize()
        assert svc._provider is not None
        assert isinstance(svc._provider, TracerProvider)
        svc.shutdown()

    def test_tracer_is_set_after_initialize(self) -> None:
        settings = ObservabilitySettings(tracing_enabled=False)
        svc = OTELTracingService(settings)
        svc.initialize()
        assert svc._tracer is not None


class TestSubscribeToDiagnosticBus:
    def test_subscribe_registers_three_event_types(self) -> None:
        """subscribe_to_diagnostic_bus() registers handlers for 3 event types."""
        settings = ObservabilitySettings(tracing_enabled=False)
        svc = OTELTracingService(settings)
        svc.initialize()
        svc.subscribe_to_diagnostic_bus()

        assert len(bus.get_subscribers("agent.run")) == 1
        assert len(bus.get_subscribers("llm.called")) == 1
        assert len(bus.get_subscribers("tool.executed")) == 1

    def test_subscribe_registers_correct_handlers(self) -> None:
        settings = ObservabilitySettings(tracing_enabled=False)
        svc = OTELTracingService(settings)
        svc.initialize()
        svc.subscribe_to_diagnostic_bus()

        assert bus.get_subscribers("agent.run")[0] == svc._on_agent_run
        assert bus.get_subscribers("llm.called")[0] == svc._on_llm_called
        assert bus.get_subscribers("tool.executed")[0] == svc._on_tool_executed


class TestShutdown:
    def test_shutdown_noop_provider_no_error(self) -> None:
        """shutdown() with no real provider should not raise."""
        settings = ObservabilitySettings(tracing_enabled=False)
        svc = OTELTracingService(settings)
        svc.initialize()
        svc.shutdown()  # must not raise

    def test_shutdown_real_provider_no_error(self) -> None:
        """shutdown() with a real provider should flush and not raise."""
        settings = ObservabilitySettings(
            tracing_enabled=True,
            otlp_endpoint="http://localhost:4318",
        )
        svc = OTELTracingService(settings)
        svc.initialize()
        svc.shutdown()  # must not raise

    def test_shutdown_idempotent(self) -> None:
        """Calling shutdown() twice should not raise."""
        settings = ObservabilitySettings(tracing_enabled=False)
        svc = OTELTracingService(settings)
        svc.initialize()
        svc.shutdown()
        svc.shutdown()  # second call must not raise


class TestSetupTracingConvenienceFunction:
    def test_setup_tracing_returns_service(self) -> None:
        settings = ObservabilitySettings(tracing_enabled=False)
        svc = setup_tracing(settings)
        assert isinstance(svc, OTELTracingService)
        # Subscribers should be registered
        assert len(bus.get_subscribers("agent.run")) >= 1

    def test_setup_tracing_disabled_no_provider(self) -> None:
        settings = ObservabilitySettings(tracing_enabled=False)
        svc = setup_tracing(settings)
        assert svc._provider is None
