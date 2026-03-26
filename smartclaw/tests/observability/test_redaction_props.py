# Feature: smartclaw-p2a-production-services, Property 17: 敏感数据脱敏
# Feature: smartclaw-p2a-production-services, Property 18: 字符串截断
"""Property-based tests for the redaction module.

Property 17: 敏感数据脱敏
    For any string matching sensitive patterns (sk-*, key-*, token-*, email with @),
    redact_value returns "[REDACTED]".
    For any string NOT matching patterns, redact_value returns original.

Property 18: 字符串截断
    For any string longer than max_length, truncate_string returns string of length <= max_length.
    For any string <= max_length, truncate_string returns original unchanged.

**Validates: Requirements 17.1, 17.2, 17.3**
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from smartclaw.observability.redaction import REDACTED, redact_value, truncate_string

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strings that start with sk-, key-, token-
_sk_prefix_st = st.text(min_size=0, max_size=50).map(lambda s: "sk-" + s)
_key_prefix_st = st.text(min_size=0, max_size=50).map(lambda s: "key-" + s)
_token_prefix_st = st.text(min_size=0, max_size=50).map(lambda s: "token-" + s)

# Email-like strings: local@domain.tld (no spaces, no @-in-local)
_email_st = st.builds(
    lambda local, domain, tld: f"{local}@{domain}.{tld}",
    local=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="._-")),
    domain=st.text(min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="-")),
    tld=st.text(min_size=2, max_size=6, alphabet=st.characters(whitelist_categories=("Ll", "Lu"))),
)

# Sensitive strings: any of the above
_sensitive_st = st.one_of(_sk_prefix_st, _key_prefix_st, _token_prefix_st, _email_st)

# Safe strings: no sk-/key-/token- prefix, no @ character
_safe_alphabet = st.characters(
    whitelist_categories=("Ll", "Lu", "Nd"),
    whitelist_characters=" _-.",
    blacklist_characters="@",
)
_safe_st = st.text(min_size=0, max_size=100, alphabet=_safe_alphabet).filter(
    lambda s: not s.startswith("sk-")
    and not s.startswith("key-")
    and not s.startswith("token-")
    and "@" not in s
)


# ---------------------------------------------------------------------------
# Property 17: 敏感数据脱敏
# ---------------------------------------------------------------------------


# Feature: smartclaw-p2a-production-services, Property 17: 敏感数据脱敏
@given(value=_sensitive_st)
@settings(max_examples=100, deadline=None)
def test_sensitive_strings_are_redacted(value: str) -> None:
    """For any string matching sensitive patterns, redact_value returns REDACTED.

    **Validates: Requirements 17.1, 17.2**
    """
    assert redact_value(value) == REDACTED


# Feature: smartclaw-p2a-production-services, Property 17: 敏感数据脱敏
@given(value=_safe_st)
@settings(max_examples=100, deadline=None)
def test_safe_strings_are_not_redacted(value: str) -> None:
    """For any string NOT matching sensitive patterns, redact_value returns original.

    **Validates: Requirements 17.1, 17.2**
    """
    assert redact_value(value) == value


# ---------------------------------------------------------------------------
# Property 18: 字符串截断
# ---------------------------------------------------------------------------


# Feature: smartclaw-p2a-production-services, Property 18: 字符串截断
@given(
    value=st.text(min_size=0, max_size=2000),
    max_length=st.integers(min_value=1, max_value=1024),
)
@settings(max_examples=100, deadline=None)
def test_truncate_long_string_within_max_length(value: str, max_length: int) -> None:
    """For any string longer than max_length, truncate_string returns length <= max_length.

    **Validates: Requirements 17.3**
    """
    result = truncate_string(value, max_length)
    assert len(result) <= max_length


# Feature: smartclaw-p2a-production-services, Property 18: 字符串截断
@given(
    max_length=st.integers(min_value=1, max_value=1024),
)
@settings(max_examples=100, deadline=None)
def test_truncate_short_string_unchanged(max_length: int) -> None:
    """For any string <= max_length, truncate_string returns original unchanged.

    **Validates: Requirements 17.3**
    """
    # Generate a string that is exactly at or below max_length
    value = "x" * max_length
    result = truncate_string(value, max_length)
    assert result == value

    # Also test shorter string
    if max_length > 1:
        short = "x" * (max_length - 1)
        assert truncate_string(short, max_length) == short
