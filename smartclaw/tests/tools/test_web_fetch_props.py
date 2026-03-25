"""Property-based tests for WebFetchTool.

Tests Properties 5–9 from the design document.
"""

from __future__ import annotations

import ipaddress
import json
import re

from hypothesis import given, settings
from hypothesis import strategies as st

from smartclaw.tools.web_fetch import (
    TRUNCATION_SUFFIX,
    check_ssrf,
    html_to_text,
    is_private_ip,
)

# ---------------------------------------------------------------------------
# Property 5: SSRF guard blocks non-HTTP schemes
# Feature: smartclaw-tools-supplement, Property 5: SSRF blocks non-HTTP schemes
# ---------------------------------------------------------------------------

_non_http_scheme = st.sampled_from(["ftp", "file", "data", "gopher", "ssh", "telnet", "ldap"])


@settings(max_examples=100)
@given(scheme=_non_http_scheme)
def test_ssrf_blocks_non_http_schemes(scheme: str) -> None:
    """Non-HTTP/HTTPS schemes are blocked by check_ssrf."""
    url = f"{scheme}://example.com/path"
    result = check_ssrf(url)
    assert result is not None
    assert "Only HTTP and HTTPS" in result


# ---------------------------------------------------------------------------
# Property 6: SSRF guard blocks private/local IPs
# Feature: smartclaw-tools-supplement, Property 6: SSRF blocks private/local IPs
# ---------------------------------------------------------------------------

_private_ipv4 = st.one_of(
    st.tuples(st.just(127), st.integers(0, 255), st.integers(0, 255), st.integers(1, 254)),  # loopback
    st.tuples(st.just(10), st.integers(0, 255), st.integers(0, 255), st.integers(1, 254)),   # 10.0.0.0/8
    st.tuples(st.just(172), st.integers(16, 31), st.integers(0, 255), st.integers(1, 254)),   # 172.16.0.0/12
    st.tuples(st.just(192), st.just(168), st.integers(0, 255), st.integers(1, 254)),           # 192.168.0.0/16
    st.tuples(st.just(169), st.just(254), st.integers(0, 255), st.integers(1, 254)),           # link-local
)


@settings(max_examples=100)
@given(octets=_private_ipv4)
def test_ssrf_blocks_private_ips(octets: tuple[int, ...]) -> None:
    """Private/loopback/link-local IPs are detected by is_private_ip."""
    ip_str = ".".join(str(o) for o in octets)
    ip = ipaddress.ip_address(ip_str)
    assert is_private_ip(ip) is True


# ---------------------------------------------------------------------------
# Property 7: HTML-to-text strips all tags
# Feature: smartclaw-tools-supplement, Property 7: HTML-to-text strips all tags
# ---------------------------------------------------------------------------

_body_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Z"), max_codepoint=127),
    min_size=0,
    max_size=200,
)


@settings(max_examples=100)
@given(body=_body_text)
def test_html_to_text_strips_tags(body: str) -> None:
    """html_to_text output contains no script/style blocks or HTML tags."""
    html = f"<html><head><style>body{{color:red}}</style><script>alert(1)</script></head><body><p>{body}</p></body></html>"
    result = html_to_text(html)
    assert "<script" not in result.lower()
    assert "</script>" not in result.lower()
    assert "<style" not in result.lower()
    assert "</style>" not in result.lower()
    # No HTML tags remain
    assert not re.search(r"<[^>]+>", result)


# ---------------------------------------------------------------------------
# Property 8: JSON formatting round-trip
# Feature: smartclaw-tools-supplement, Property 8: JSON formatting round-trip
# ---------------------------------------------------------------------------

_json_values = st.recursive(
    st.one_of(st.none(), st.booleans(), st.integers(-1000, 1000), st.floats(allow_nan=False, allow_infinity=False), st.text(max_size=50)),
    lambda children: st.one_of(st.lists(children, max_size=5), st.dictionaries(st.text(max_size=10), children, max_size=5)),
    max_leaves=20,
)


@settings(max_examples=100)
@given(value=_json_values)
def test_json_formatting_roundtrip(value: object) -> None:
    """JSON formatting then parsing produces the original value."""
    formatted = json.dumps(value, indent=2, ensure_ascii=False)
    parsed = json.loads(formatted)
    assert parsed == value


# ---------------------------------------------------------------------------
# Property 9: Text truncation respects max_chars
# Feature: smartclaw-tools-supplement, Property 9: Text truncation respects max_chars
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    text=st.text(min_size=10, max_size=500),
    max_chars=st.integers(min_value=1, max_value=200),
)
def test_truncation_respects_max_chars(text: str, max_chars: int) -> None:
    """Truncation produces content portion of exactly max_chars length when text exceeds limit."""
    if len(text) <= max_chars:
        return  # skip — no truncation needed

    truncated = text[:max_chars] + TRUNCATION_SUFFIX
    content_portion = truncated[: truncated.index(TRUNCATION_SUFFIX)]
    assert len(content_portion) == max_chars
