"""Property-based tests for structured logging.

Tests cover:
- Property 4: Log output contains required structured fields
- Property 5: Log format matches configuration
- Property 6: Log level filtering
"""

from __future__ import annotations

import json
import logging
import re
import sys
from io import StringIO

from hypothesis import given, settings
from hypothesis import strategies as st

from smartclaw.config.settings import LoggingSettings
from smartclaw.observability.logging import get_logger, setup_logging

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

LEVEL_SEVERITY: dict[str, int] = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}

# Safe component names: ASCII letters/digits, non-empty
component_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=30,
)

# Safe log messages: printable, non-empty, no newlines
log_messages = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        blacklist_characters="\n\r\x00",
    ),
    min_size=1,
    max_size=80,
)


def _capture_log_output(
    log_settings: LoggingSettings,
    component: str,
    message: str,
    level: str = "INFO",
) -> str:
    """Set up logging, emit one message, and return the captured stderr text."""
    import smartclaw.observability.logging as log_mod

    # Reset module state so setup_logging re-configures from scratch.
    log_mod._setup_done = False

    # Redirect stderr to capture structlog output.
    capture = StringIO()
    old_stderr = sys.stderr
    sys.stderr = capture

    try:
        setup_logging(log_settings)
        logger = get_logger(component)

        emit = getattr(logger, level.lower())
        emit(message)

        # Flush all handlers attached to the root logger.
        for handler in logging.getLogger().handlers:
            handler.flush()
    finally:
        sys.stderr = old_stderr

    return capture.getvalue()


# ---------------------------------------------------------------------------
# Property 4: Log output contains required structured fields
# **Validates: Requirements 3.4, 3.5**
# ---------------------------------------------------------------------------


@given(
    component=component_names,
    message=log_messages,
    fmt=st.sampled_from(["console", "json"]),
)
@settings(max_examples=100)
def test_log_structured_fields(component: str, message: str, fmt: str) -> None:
    """Property 4: Log output contains required structured fields.

    For any component name and log message, the structured log output
    should contain a timestamp, log level, caller information (file + line),
    and the bound component name.

    **Validates: Requirements 3.4, 3.5**
    """
    log_settings = LoggingSettings(level="DEBUG", format=fmt, file=None)
    output = _capture_log_output(log_settings, component, message, level="INFO")

    if not output.strip():
        return

    if fmt == "json":
        parsed = json.loads(output.strip())
        # Timestamp (ISO format)
        assert "timestamp" in parsed, f"Missing 'timestamp' in JSON output: {parsed}"
        # Log level — structlog stdlib integration uses "level" key
        has_level = "level" in parsed or "log_level" in parsed
        assert has_level, f"Missing level field in JSON output: {parsed}"
        # Caller info
        assert "filename" in parsed, f"Missing 'filename' in JSON output: {parsed}"
        assert "lineno" in parsed, f"Missing 'lineno' in JSON output: {parsed}"
        # Component
        assert "component" in parsed, f"Missing 'component' in JSON output: {parsed}"
        assert parsed["component"] == component
    else:
        # Console format: verify key fields are present as text
        # Timestamp: ISO-like pattern  YYYY-MM-DDTHH:MM:SS
        assert re.search(r"\d{4}-\d{2}-\d{2}", output), f"No timestamp in console output: {output!r}"
        # Log level
        assert "info" in output.lower(), f"No log level in console output: {output!r}"
        # Component
        assert component in output, f"Component {component!r} not in console output: {output!r}"


# ---------------------------------------------------------------------------
# Property 5: Log format matches configuration
# **Validates: Requirements 3.2**
# ---------------------------------------------------------------------------


@given(
    component=component_names,
    message=log_messages,
)
@settings(max_examples=100)
def test_log_format_matches_config(component: str, message: str) -> None:
    """Property 5: Log format matches configuration.

    When format is "json" the output should be valid JSON.
    When format is "console" the output should be non-JSON text.

    **Validates: Requirements 3.2**
    """
    # --- JSON format ---
    json_settings = LoggingSettings(level="DEBUG", format="json", file=None)
    json_output = _capture_log_output(json_settings, component, message, level="INFO")

    if json_output.strip():
        parsed = json.loads(json_output.strip())
        assert isinstance(parsed, dict), "JSON output should be a dict"

    # --- Console format ---
    console_settings = LoggingSettings(level="DEBUG", format="console", file=None)
    console_output = _capture_log_output(console_settings, component, message, level="INFO")

    if console_output.strip():
        try:
            json.loads(console_output.strip())
            # If it parses as JSON, that's wrong for console mode
            raise AssertionError(f"Console output should NOT be valid JSON: {console_output!r}")
        except json.JSONDecodeError:
            pass  # Expected — console output is not JSON


# ---------------------------------------------------------------------------
# Property 6: Log level filtering
# **Validates: Requirements 3.6**
# ---------------------------------------------------------------------------


@given(
    configured_level=st.sampled_from(LOG_LEVELS),
    emit_level=st.sampled_from(LOG_LEVELS),
    component=component_names,
    message=log_messages,
)
@settings(max_examples=100)
def test_log_level_filtering(
    configured_level: str,
    emit_level: str,
    component: str,
    message: str,
) -> None:
    """Property 6: Log level filtering.

    A message emitted at level M should appear in the output if and only
    if M >= the configured level L.

    **Validates: Requirements 3.6**
    """
    log_settings = LoggingSettings(level=configured_level, format="json", file=None)
    output = _capture_log_output(log_settings, component, message, level=emit_level)

    should_appear = LEVEL_SEVERITY[emit_level] >= LEVEL_SEVERITY[configured_level]
    text = output.strip()

    if should_appear:
        assert text, f"Expected output for {emit_level} with configured level {configured_level}, got nothing"
    else:
        assert not text, f"Expected NO output for {emit_level} with configured level {configured_level}, got: {text!r}"
