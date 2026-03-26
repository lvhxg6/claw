"""Unit tests for the redaction module.

Tests:
- sk- prefix → REDACTED
- key- prefix → REDACTED
- token- prefix → REDACTED
- email format → REDACTED
- normal string → unchanged
- truncation at exact boundary, over boundary, under boundary
- user_message truncated to 256 chars
"""

from __future__ import annotations

import pytest

from smartclaw.observability.redaction import (
    REDACTED,
    redact_attributes,
    redact_value,
    truncate_string,
)


# ---------------------------------------------------------------------------
# redact_value — sensitive patterns
# ---------------------------------------------------------------------------


class TestRedactValue:
    def test_sk_prefix_is_redacted(self) -> None:
        assert redact_value("sk-abc123") == REDACTED

    def test_sk_prefix_only_is_redacted(self) -> None:
        assert redact_value("sk-") == REDACTED

    def test_key_prefix_is_redacted(self) -> None:
        assert redact_value("key-my-secret") == REDACTED

    def test_key_prefix_only_is_redacted(self) -> None:
        assert redact_value("key-") == REDACTED

    def test_token_prefix_is_redacted(self) -> None:
        assert redact_value("token-xyz789") == REDACTED

    def test_token_prefix_only_is_redacted(self) -> None:
        assert redact_value("token-") == REDACTED

    def test_email_format_is_redacted(self) -> None:
        assert redact_value("user@example.com") == REDACTED

    def test_email_with_subdomain_is_redacted(self) -> None:
        assert redact_value("admin@mail.company.org") == REDACTED

    def test_normal_string_unchanged(self) -> None:
        assert redact_value("hello world") == "hello world"

    def test_empty_string_unchanged(self) -> None:
        assert redact_value("") == ""

    def test_number_string_unchanged(self) -> None:
        assert redact_value("12345") == "12345"

    def test_url_without_at_unchanged(self) -> None:
        assert redact_value("https://example.com/path") == "https://example.com/path"

    def test_partial_sk_not_at_start_unchanged(self) -> None:
        # "sk-" must be at the start (^sk-)
        assert redact_value("prefix-sk-abc") == "prefix-sk-abc"

    def test_partial_key_not_at_start_unchanged(self) -> None:
        assert redact_value("my-key-value") == "my-key-value"

    def test_partial_token_not_at_start_unchanged(self) -> None:
        assert redact_value("access_token-abc") == "access_token-abc"


# ---------------------------------------------------------------------------
# truncate_string
# ---------------------------------------------------------------------------


class TestTruncateString:
    def test_string_at_exact_boundary_unchanged(self) -> None:
        s = "a" * 1024
        assert truncate_string(s) == s
        assert len(truncate_string(s)) == 1024

    def test_string_over_boundary_truncated(self) -> None:
        s = "a" * 1025
        result = truncate_string(s)
        assert len(result) == 1024
        assert result == "a" * 1024

    def test_string_under_boundary_unchanged(self) -> None:
        s = "hello"
        assert truncate_string(s) == "hello"

    def test_empty_string_unchanged(self) -> None:
        assert truncate_string("") == ""

    def test_custom_max_length(self) -> None:
        s = "abcdefghij"
        assert truncate_string(s, max_length=5) == "abcde"

    def test_custom_max_length_exact(self) -> None:
        s = "abcde"
        assert truncate_string(s, max_length=5) == "abcde"

    def test_custom_max_length_under(self) -> None:
        s = "abc"
        assert truncate_string(s, max_length=5) == "abc"

    def test_user_message_truncated_to_256(self) -> None:
        """user_message should be truncated to 256 chars (Req 17.4)."""
        long_message = "x" * 512
        result = truncate_string(long_message, max_length=256)
        assert len(result) == 256
        assert result == "x" * 256

    def test_user_message_under_256_unchanged(self) -> None:
        message = "short message"
        assert truncate_string(message, max_length=256) == message


# ---------------------------------------------------------------------------
# redact_attributes
# ---------------------------------------------------------------------------


class TestRedactAttributes:
    def test_sensitive_values_redacted(self) -> None:
        attrs = {"api_key": "sk-secret123", "name": "alice"}
        result = redact_attributes(attrs)
        assert result["api_key"] == REDACTED
        assert result["name"] == "alice"

    def test_long_values_truncated(self) -> None:
        attrs = {"msg": "a" * 2000}
        result = redact_attributes(attrs)
        assert len(result["msg"]) == 1024

    def test_sensitive_and_long_value_redacted_not_truncated(self) -> None:
        # A sensitive value that is also long — redaction takes priority
        attrs = {"key": "sk-" + "x" * 2000}
        result = redact_attributes(attrs)
        assert result["key"] == REDACTED

    def test_empty_dict(self) -> None:
        assert redact_attributes({}) == {}

    def test_custom_max_length(self) -> None:
        attrs = {"msg": "hello world"}
        result = redact_attributes(attrs, max_length=5)
        assert result["msg"] == "hello"
