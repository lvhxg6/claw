"""Unit tests for P2A configuration settings.

Tests cover:
- GatewaySettings all field defaults (Req 8.1)
- ObservabilitySettings all field defaults (Req 18.1)
- SmartClawSettings has gateway and observability fields with correct defaults
- Existing P0/P1 fields are not modified (Req 20.2, 20.3)
- Environment variable overrides (Req 8.2, 18.2)
- gateway.enabled=False means CLI-only mode (Req 8.3)
- observability.tracing_enabled=False means NoOp TracerProvider (Req 18.4)

Requirements: 8.1, 8.2, 8.3, 18.1, 18.2, 18.4, 20.2, 20.3
"""

from __future__ import annotations

import os

import pytest

from smartclaw.config.settings import (
    GatewaySettings,
    ObservabilitySettings,
    SmartClawSettings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clear_smartclaw_env() -> dict[str, str]:
    """Remove all SMARTCLAW_ env vars, return saved values for restore."""
    saved: dict[str, str] = {}
    for k in list(os.environ):
        if k.startswith("SMARTCLAW_"):
            saved[k] = os.environ.pop(k)
    return saved


def _restore_env(saved: dict[str, str]) -> None:
    """Restore previously saved env vars."""
    for k in list(os.environ):
        if k.startswith("SMARTCLAW_"):
            del os.environ[k]
    for k, v in saved.items():
        os.environ[k] = v


# ---------------------------------------------------------------------------
# Test: GatewaySettings defaults (Req 8.1)
# ---------------------------------------------------------------------------


class TestGatewaySettingsDefaults:
    """Verify GatewaySettings default values."""

    def test_enabled_default_false(self) -> None:
        s = GatewaySettings()
        assert s.enabled is False

    def test_host_default(self) -> None:
        s = GatewaySettings()
        assert s.host == "0.0.0.0"

    def test_port_default(self) -> None:
        s = GatewaySettings()
        assert s.port == 8000

    def test_cors_origins_default(self) -> None:
        s = GatewaySettings()
        assert s.cors_origins == ["*"]

    def test_shutdown_timeout_default(self) -> None:
        s = GatewaySettings()
        assert s.shutdown_timeout == 30

    def test_reload_interval_default(self) -> None:
        s = GatewaySettings()
        assert s.reload_interval == 5


# ---------------------------------------------------------------------------
# Test: ObservabilitySettings defaults (Req 18.1)
# ---------------------------------------------------------------------------


class TestObservabilitySettingsDefaults:
    """Verify ObservabilitySettings default values."""

    def test_tracing_enabled_default_false(self) -> None:
        s = ObservabilitySettings()
        assert s.tracing_enabled is False

    def test_otlp_endpoint_default(self) -> None:
        s = ObservabilitySettings()
        assert s.otlp_endpoint == "http://localhost:4318"

    def test_otlp_protocol_default(self) -> None:
        s = ObservabilitySettings()
        assert s.otlp_protocol == "http/protobuf"

    def test_service_name_default(self) -> None:
        s = ObservabilitySettings()
        assert s.service_name == "smartclaw"

    def test_sample_rate_default(self) -> None:
        s = ObservabilitySettings()
        assert s.sample_rate == 1.0

    def test_redact_sensitive_default_true(self) -> None:
        s = ObservabilitySettings()
        assert s.redact_sensitive is True


# ---------------------------------------------------------------------------
# Test: SmartClawSettings includes P2A fields with correct defaults
# ---------------------------------------------------------------------------


class TestSmartClawSettingsP2AFields:
    """Verify P2A fields are present on SmartClawSettings with correct defaults."""

    def setup_method(self) -> None:
        self._saved = _clear_smartclaw_env()

    def teardown_method(self) -> None:
        _restore_env(self._saved)

    def test_gateway_field_present(self) -> None:
        s = SmartClawSettings()
        assert isinstance(s.gateway, GatewaySettings)

    def test_gateway_defaults_disabled(self) -> None:
        s = SmartClawSettings()
        assert s.gateway.enabled is False
        assert s.gateway.host == "0.0.0.0"
        assert s.gateway.port == 8000

    def test_observability_field_present(self) -> None:
        s = SmartClawSettings()
        assert isinstance(s.observability, ObservabilitySettings)

    def test_observability_defaults_disabled(self) -> None:
        s = SmartClawSettings()
        assert s.observability.tracing_enabled is False
        assert s.observability.otlp_endpoint == "http://localhost:4318"
        assert s.observability.service_name == "smartclaw"


# ---------------------------------------------------------------------------
# Test: Existing P0/P1 fields are not modified (Req 20.2, 20.3)
# ---------------------------------------------------------------------------


class TestP0P1FieldsUnmodified:
    """Verify P0/P1 fields retain their defaults when P2A fields are added."""

    def setup_method(self) -> None:
        self._saved = _clear_smartclaw_env()

    def teardown_method(self) -> None:
        _restore_env(self._saved)

    def test_agent_defaults_max_tokens(self) -> None:
        s = SmartClawSettings()
        assert s.agent_defaults.max_tokens == 32768

    def test_agent_defaults_workspace(self) -> None:
        s = SmartClawSettings()
        assert s.agent_defaults.workspace == "~/.smartclaw/workspace"

    def test_logging_level(self) -> None:
        s = SmartClawSettings()
        assert s.logging.level == "INFO"

    def test_logging_format(self) -> None:
        s = SmartClawSettings()
        assert s.logging.format == "console"

    def test_credentials_keyring_service(self) -> None:
        s = SmartClawSettings()
        assert s.credentials.keyring_service == "smartclaw"

    def test_memory_enabled(self) -> None:
        s = SmartClawSettings()
        assert s.memory.enabled is True

    def test_memory_db_path(self) -> None:
        s = SmartClawSettings()
        assert s.memory.db_path == "~/.smartclaw/memory.db"

    def test_skills_enabled(self) -> None:
        s = SmartClawSettings()
        assert s.skills.enabled is True

    def test_sub_agent_enabled(self) -> None:
        s = SmartClawSettings()
        assert s.sub_agent.enabled is True

    def test_multi_agent_enabled_false(self) -> None:
        s = SmartClawSettings()
        assert s.multi_agent.enabled is False


# ---------------------------------------------------------------------------
# Test: gateway.enabled=False → CLI-only mode (Req 8.3)
# ---------------------------------------------------------------------------


class TestGatewayDisabledCLIOnly:
    """Verify gateway.enabled=False means system operates in CLI-only mode."""

    def setup_method(self) -> None:
        self._saved = _clear_smartclaw_env()

    def teardown_method(self) -> None:
        _restore_env(self._saved)

    def test_gateway_disabled_by_default(self) -> None:
        s = SmartClawSettings()
        assert s.gateway.enabled is False

    def test_gateway_can_be_enabled(self) -> None:
        os.environ["SMARTCLAW_GATEWAY__ENABLED"] = "true"
        s = SmartClawSettings()
        assert s.gateway.enabled is True


# ---------------------------------------------------------------------------
# Test: observability.tracing_enabled=False → NoOp TracerProvider (Req 18.4)
# ---------------------------------------------------------------------------


class TestObservabilityDisabledNoOp:
    """Verify tracing_enabled=False means NoOp tracing (config level)."""

    def setup_method(self) -> None:
        self._saved = _clear_smartclaw_env()

    def teardown_method(self) -> None:
        _restore_env(self._saved)

    def test_tracing_disabled_by_default(self) -> None:
        s = SmartClawSettings()
        assert s.observability.tracing_enabled is False

    def test_tracing_can_be_enabled(self) -> None:
        os.environ["SMARTCLAW_OBSERVABILITY__TRACING_ENABLED"] = "true"
        s = SmartClawSettings()
        assert s.observability.tracing_enabled is True


# ---------------------------------------------------------------------------
# Test: Environment variable overrides (Req 8.2, 18.2)
# ---------------------------------------------------------------------------


class TestP2AEnvOverrides:
    """Verify environment variable overrides for P2A settings."""

    def setup_method(self) -> None:
        self._saved = _clear_smartclaw_env()

    def teardown_method(self) -> None:
        _restore_env(self._saved)

    def test_gateway_port_override(self) -> None:
        os.environ["SMARTCLAW_GATEWAY__PORT"] = "9999"
        s = SmartClawSettings()
        assert s.gateway.port == 9999

    def test_gateway_host_override(self) -> None:
        os.environ["SMARTCLAW_GATEWAY__HOST"] = "127.0.0.1"
        s = SmartClawSettings()
        assert s.gateway.host == "127.0.0.1"

    def test_gateway_shutdown_timeout_override(self) -> None:
        os.environ["SMARTCLAW_GATEWAY__SHUTDOWN_TIMEOUT"] = "60"
        s = SmartClawSettings()
        assert s.gateway.shutdown_timeout == 60

    def test_gateway_reload_interval_override(self) -> None:
        os.environ["SMARTCLAW_GATEWAY__RELOAD_INTERVAL"] = "10"
        s = SmartClawSettings()
        assert s.gateway.reload_interval == 10

    def test_observability_otlp_endpoint_override(self) -> None:
        os.environ["SMARTCLAW_OBSERVABILITY__OTLP_ENDPOINT"] = "http://jaeger:4318"
        s = SmartClawSettings()
        assert s.observability.otlp_endpoint == "http://jaeger:4318"

    def test_observability_service_name_override(self) -> None:
        os.environ["SMARTCLAW_OBSERVABILITY__SERVICE_NAME"] = "my-agent"
        s = SmartClawSettings()
        assert s.observability.service_name == "my-agent"

    def test_observability_sample_rate_override(self) -> None:
        os.environ["SMARTCLAW_OBSERVABILITY__SAMPLE_RATE"] = "0.5"
        s = SmartClawSettings()
        assert s.observability.sample_rate == 0.5

    def test_observability_otlp_protocol_override(self) -> None:
        os.environ["SMARTCLAW_OBSERVABILITY__OTLP_PROTOCOL"] = "grpc"
        s = SmartClawSettings()
        assert s.observability.otlp_protocol == "grpc"

    def test_observability_redact_sensitive_override(self) -> None:
        os.environ["SMARTCLAW_OBSERVABILITY__REDACT_SENSITIVE"] = "false"
        s = SmartClawSettings()
        assert s.observability.redact_sensitive is False

    def test_p0_p1_fields_unchanged_with_p2a_overrides(self) -> None:
        """P0/P1 fields retain defaults when P2A env vars are set."""
        os.environ["SMARTCLAW_GATEWAY__PORT"] = "9999"
        os.environ["SMARTCLAW_OBSERVABILITY__TRACING_ENABLED"] = "true"
        s = SmartClawSettings()
        # P0/P1 defaults intact
        assert s.agent_defaults.max_tokens == 32768
        assert s.logging.level == "INFO"
        assert s.memory.enabled is True
        assert s.skills.enabled is True
        assert s.sub_agent.enabled is True
