# Feature: smartclaw-p2a-production-services, Property 8: P2A 设置环境变量覆盖
"""Property-based tests for P2A settings environment variable overrides.

Uses hypothesis with @settings(max_examples=100, deadline=None).

For any environment variable with prefix SMARTCLAW_GATEWAY__ or
SMARTCLAW_OBSERVABILITY__, the corresponding GatewaySettings or
ObservabilitySettings field value should be overridden by the env var value.

**Validates: Requirements 8.2, 18.2**
"""

from __future__ import annotations

import os

from hypothesis import given, settings
from hypothesis import strategies as st

from smartclaw.config.settings import SmartClawSettings


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
# Strategies
# ---------------------------------------------------------------------------

# Port numbers: valid range for network ports
_port_st = st.integers(min_value=1, max_value=65535)

# Host strings: simple alphanumeric hostnames
_host_st = st.from_regex(r"[a-z][a-z0-9\.\-]{0,30}", fullmatch=True)

# OTLP endpoint: http URLs
_otlp_endpoint_st = st.builds(
    lambda host, port: f"http://{host}:{port}",
    host=_host_st,
    port=_port_st,
)

# Service name: simple identifiers
_service_name_st = st.from_regex(r"[a-z][a-z0-9_\-]{0,20}", fullmatch=True)

# Sample rate: float between 0.0 and 1.0
_sample_rate_st = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)

# Shutdown timeout / reload interval: positive integers
_timeout_st = st.integers(min_value=1, max_value=3600)


# ---------------------------------------------------------------------------
# Property 8: P2A 设置环境变量覆盖 — Gateway fields
# ---------------------------------------------------------------------------


# Feature: smartclaw-p2a-production-services, Property 8: P2A 设置环境变量覆盖
@given(port=_port_st)
@settings(max_examples=100, deadline=None)
def test_gateway_port_env_override(port: int) -> None:
    """SMARTCLAW_GATEWAY__PORT overrides gateway.port.

    **Validates: Requirements 8.2**
    """
    saved = _clear_smartclaw_env()
    try:
        os.environ["SMARTCLAW_GATEWAY__PORT"] = str(port)
        s = SmartClawSettings()
        assert s.gateway.port == port
    finally:
        _restore_env(saved)


# Feature: smartclaw-p2a-production-services, Property 8: P2A 设置环境变量覆盖
@given(host=_host_st)
@settings(max_examples=100, deadline=None)
def test_gateway_host_env_override(host: str) -> None:
    """SMARTCLAW_GATEWAY__HOST overrides gateway.host.

    **Validates: Requirements 8.2**
    """
    saved = _clear_smartclaw_env()
    try:
        os.environ["SMARTCLAW_GATEWAY__HOST"] = host
        s = SmartClawSettings()
        assert s.gateway.host == host
    finally:
        _restore_env(saved)


# Feature: smartclaw-p2a-production-services, Property 8: P2A 设置环境变量覆盖
@given(timeout=_timeout_st)
@settings(max_examples=100, deadline=None)
def test_gateway_shutdown_timeout_env_override(timeout: int) -> None:
    """SMARTCLAW_GATEWAY__SHUTDOWN_TIMEOUT overrides gateway.shutdown_timeout.

    **Validates: Requirements 8.2**
    """
    saved = _clear_smartclaw_env()
    try:
        os.environ["SMARTCLAW_GATEWAY__SHUTDOWN_TIMEOUT"] = str(timeout)
        s = SmartClawSettings()
        assert s.gateway.shutdown_timeout == timeout
    finally:
        _restore_env(saved)


# Feature: smartclaw-p2a-production-services, Property 8: P2A 设置环境变量覆盖
@given(interval=_timeout_st)
@settings(max_examples=100, deadline=None)
def test_gateway_reload_interval_env_override(interval: int) -> None:
    """SMARTCLAW_GATEWAY__RELOAD_INTERVAL overrides gateway.reload_interval.

    **Validates: Requirements 8.2**
    """
    saved = _clear_smartclaw_env()
    try:
        os.environ["SMARTCLAW_GATEWAY__RELOAD_INTERVAL"] = str(interval)
        s = SmartClawSettings()
        assert s.gateway.reload_interval == interval
    finally:
        _restore_env(saved)


# ---------------------------------------------------------------------------
# Property 8: P2A 设置环境变量覆盖 — Observability fields
# ---------------------------------------------------------------------------


# Feature: smartclaw-p2a-production-services, Property 8: P2A 设置环境变量覆盖
@given(endpoint=_otlp_endpoint_st)
@settings(max_examples=100, deadline=None)
def test_observability_otlp_endpoint_env_override(endpoint: str) -> None:
    """SMARTCLAW_OBSERVABILITY__OTLP_ENDPOINT overrides observability.otlp_endpoint.

    **Validates: Requirements 18.2**
    """
    saved = _clear_smartclaw_env()
    try:
        os.environ["SMARTCLAW_OBSERVABILITY__OTLP_ENDPOINT"] = endpoint
        s = SmartClawSettings()
        assert s.observability.otlp_endpoint == endpoint
    finally:
        _restore_env(saved)


# Feature: smartclaw-p2a-production-services, Property 8: P2A 设置环境变量覆盖
@given(service_name=_service_name_st)
@settings(max_examples=100, deadline=None)
def test_observability_service_name_env_override(service_name: str) -> None:
    """SMARTCLAW_OBSERVABILITY__SERVICE_NAME overrides observability.service_name.

    **Validates: Requirements 18.2**
    """
    saved = _clear_smartclaw_env()
    try:
        os.environ["SMARTCLAW_OBSERVABILITY__SERVICE_NAME"] = service_name
        s = SmartClawSettings()
        assert s.observability.service_name == service_name
    finally:
        _restore_env(saved)


# Feature: smartclaw-p2a-production-services, Property 8: P2A 设置环境变量覆盖
@given(sample_rate=_sample_rate_st)
@settings(max_examples=100, deadline=None)
def test_observability_sample_rate_env_override(sample_rate: float) -> None:
    """SMARTCLAW_OBSERVABILITY__SAMPLE_RATE overrides observability.sample_rate.

    **Validates: Requirements 18.2**
    """
    saved = _clear_smartclaw_env()
    try:
        os.environ["SMARTCLAW_OBSERVABILITY__SAMPLE_RATE"] = str(sample_rate)
        s = SmartClawSettings()
        assert abs(s.observability.sample_rate - sample_rate) < 1e-6
    finally:
        _restore_env(saved)


# Feature: smartclaw-p2a-production-services, Property 8: P2A 设置环境变量覆盖
@given(enabled=st.booleans())
@settings(max_examples=100, deadline=None)
def test_observability_tracing_enabled_env_override(enabled: bool) -> None:
    """SMARTCLAW_OBSERVABILITY__TRACING_ENABLED overrides observability.tracing_enabled.

    **Validates: Requirements 18.2**
    """
    saved = _clear_smartclaw_env()
    try:
        os.environ["SMARTCLAW_OBSERVABILITY__TRACING_ENABLED"] = str(enabled).lower()
        s = SmartClawSettings()
        assert s.observability.tracing_enabled is enabled
    finally:
        _restore_env(saved)
