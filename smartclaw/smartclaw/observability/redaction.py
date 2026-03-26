"""Sensitive data redaction utilities for OTEL span attributes.

Provides:
    redact_value(value)              — redact a single string if it matches sensitive patterns
    redact_attributes(attrs, ...)    — redact + truncate all string values in a dict
    truncate_string(value, ...)      — truncate a string to max_length
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Sensitive patterns
# ---------------------------------------------------------------------------

_SENSITIVE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^sk-"),                              # OpenAI-style API key
    re.compile(r"^key-"),                             # Generic API key
    re.compile(r"^token-"),                           # Token prefix
    re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+"),         # Email-like (contains @)
]

_SECRET_ENV_NAMES: frozenset[str] = frozenset({
    "API_KEY",
    "SECRET",
    "PASSWORD",
    "TOKEN",
    "PRIVATE_KEY",
})

REDACTED = "[REDACTED]"

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def redact_value(value: str) -> str:
    """Return REDACTED if *value* matches any sensitive pattern, else return *value* unchanged."""
    for pattern in _SENSITIVE_PATTERNS:
        if pattern.search(value):
            return REDACTED
    return value


def truncate_string(value: str, max_length: int = 1024) -> str:
    """Return *value* truncated to *max_length* characters.

    If ``len(value) <= max_length`` the original string is returned unchanged.
    """
    if len(value) > max_length:
        return value[:max_length]
    return value


def redact_attributes(attrs: dict[str, str], max_length: int = 1024) -> dict[str, str]:
    """Apply redact_value + truncate_string to every string value in *attrs*.

    Non-string values are passed through unchanged.
    """
    result: dict[str, str] = {}
    for key, value in attrs.items():
        if isinstance(value, str):
            result[key] = truncate_string(redact_value(value), max_length)
        else:
            result[key] = value  # type: ignore[assignment]
    return result
