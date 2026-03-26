"""OpenTelemetry tracing service.

Provides ``OTELTracingService`` which:
- Initialises a real TracerProvider (with BatchSpanProcessor + OTLP exporter)
  when ``tracing_enabled=True``, or a NoOp TracerProvider otherwise.
- Subscribes to the diagnostic bus (tool.executed / llm.called / agent.run)
  and creates OTEL spans for each event.
- Redacts all span attributes through ``redact_attributes()`` before setting them.

Usage::

    from smartclaw.observability.tracing import setup_tracing
    from smartclaw.config.settings import ObservabilitySettings

    svc = setup_tracing(ObservabilitySettings(tracing_enabled=True))
    # ... run agent ...
    svc.shutdown()
"""

from __future__ import annotations

import contextvars
import logging
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import NonRecordingSpan, Span, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

import smartclaw.observability.diagnostic_bus as bus
from smartclaw.config.settings import ObservabilitySettings
from smartclaw.observability.redaction import redact_attributes, truncate_string

_log = logging.getLogger(__name__)

# Context variable to track the current root span across async calls
_root_span_var: contextvars.ContextVar[Span | None] = contextvars.ContextVar(
    "_root_span_var", default=None
)
_root_ctx_var: contextvars.ContextVar[Any] = contextvars.ContextVar(
    "_root_ctx_var", default=None
)


class OTELTracingService:
    """OpenTelemetry tracing service backed by the diagnostic event bus."""

    def __init__(self, settings: ObservabilitySettings) -> None:
        self._settings = settings
        self._provider: TracerProvider | None = None
        self._tracer: trace.Tracer | None = None

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Set up the TracerProvider.

        When ``tracing_enabled=False`` a NoOp provider is used so that
        all tracing calls are no-ops and nothing is exported.
        """
        if not self._settings.tracing_enabled:
            # Use the global no-op tracer — nothing is exported
            self._provider = None
            self._tracer = trace.get_tracer(__name__)
            return

        resource = Resource.create({"service.name": self._settings.service_name})
        provider = TracerProvider(resource=resource)

        exporter = self._build_exporter()
        if exporter is not None:
            provider.add_span_processor(BatchSpanProcessor(exporter))

        # Register as the global provider
        trace.set_tracer_provider(provider)
        self._provider = provider
        self._tracer = provider.get_tracer(__name__)

    def _build_exporter(self) -> Any:
        """Build the OTLP exporter based on configured protocol."""
        try:
            if self._settings.otlp_protocol == "grpc":
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                    OTLPSpanExporter,
                )
                return OTLPSpanExporter(endpoint=self._settings.otlp_endpoint)
            else:
                # Default: http/protobuf
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )
                return OTLPSpanExporter(endpoint=self._settings.otlp_endpoint)
        except Exception as exc:
            _log.warning("Failed to build OTLP exporter, tracing will be no-op: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Diagnostic bus subscription
    # ------------------------------------------------------------------

    def subscribe_to_diagnostic_bus(self) -> None:
        """Subscribe to tool.executed, llm.called, and agent.run events."""
        bus.on("agent.run", self._on_agent_run)
        bus.on("llm.called", self._on_llm_called)
        bus.on("tool.executed", self._on_tool_executed)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    async def _on_agent_run(self, event_type: str, payload: dict) -> None:
        """Handle agent.run events.

        phase=start → create root span "agent.invoke"
        phase=end   → end root span, set ERROR status if error present
        """
        tracer = self._get_tracer()
        phase = payload.get("phase", "")

        if phase == "start":
            raw_attrs: dict[str, str] = {
                "session_key": str(payload.get("session_key", "")),
                "user_message": truncate_string(str(payload.get("user_message", "")), 256),
                "max_iterations": str(payload.get("max_iterations", "")),
            }
            attrs = redact_attributes(raw_attrs)
            span = tracer.start_span("agent.invoke", attributes=attrs)
            ctx = trace.use_span(span, end_on_exit=False)
            ctx.__enter__()
            _root_span_var.set(span)
            _root_ctx_var.set(ctx)

        elif phase == "end":
            span = _root_span_var.get(None)
            if span is not None and span.is_recording():
                error = payload.get("error")
                if error:
                    span.set_status(StatusCode.ERROR, str(error))
                    span.record_exception(Exception(str(error)))
                else:
                    span.set_status(StatusCode.OK)
                span.end()
            ctx = _root_ctx_var.get(None)
            if ctx is not None:
                try:
                    ctx.__exit__(None, None, None)
                except Exception:
                    pass
            _root_span_var.set(None)
            _root_ctx_var.set(None)

    async def _on_llm_called(self, event_type: str, payload: dict) -> None:
        """Handle llm.called events — create child span "llm.call"."""
        tracer = self._get_tracer()
        root_span = _root_span_var.get(None)

        raw_attrs: dict[str, str] = {
            "model": str(payload.get("model", "")),
            "message_count": str(payload.get("message_count", "")),
            "has_tool_calls": str(payload.get("has_tool_calls", False)),
        }
        attrs = redact_attributes(raw_attrs)

        ctx = trace.set_span_in_context(root_span) if root_span else None
        with tracer.start_as_current_span("llm.call", context=ctx, attributes=attrs) as span:
            error = payload.get("error")
            if error:
                span.set_status(StatusCode.ERROR, str(error))
                span.record_exception(Exception(str(error)))

    async def _on_tool_executed(self, event_type: str, payload: dict) -> None:
        """Handle tool.executed events — create child span "tool.execute.{tool_name}"."""
        tracer = self._get_tracer()
        root_span = _root_span_var.get(None)
        tool_name = str(payload.get("tool_name", "unknown"))

        raw_attrs: dict[str, str] = {
            "tool_name": tool_name,
            "success": str(payload.get("success", True)),
        }
        attrs = redact_attributes(raw_attrs)

        ctx = trace.set_span_in_context(root_span) if root_span else None
        with tracer.start_as_current_span(
            f"tool.execute.{tool_name}", context=ctx, attributes=attrs
        ) as span:
            error = payload.get("error")
            if error:
                span.set_status(StatusCode.ERROR, str(error))
                span.record_exception(Exception(str(error)))

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Flush and shut down the TracerProvider."""
        if self._provider is not None:
            try:
                self._provider.force_flush()
                self._provider.shutdown()
            except Exception as exc:
                _log.warning("Error during TracerProvider shutdown: %s", exc)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_tracer(self) -> trace.Tracer:
        if self._tracer is None:
            return trace.get_tracer(__name__)
        return self._tracer


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def setup_tracing(settings: ObservabilitySettings) -> OTELTracingService:
    """Create, initialise, and subscribe an OTELTracingService.

    Returns the ready-to-use service instance.
    """
    svc = OTELTracingService(settings)
    svc.initialize()
    svc.subscribe_to_diagnostic_bus()
    return svc
