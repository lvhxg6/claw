"""Property-based tests for transport detection.

Uses hypothesis with @settings(max_examples=100).
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from smartclaw.mcp.config import MCPServerConfig
from smartclaw.mcp.manager import detect_transport


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_url = st.from_regex(r"https?://[a-z]{1,10}\.[a-z]{2,4}", fullmatch=True)
_command = st.from_regex(r"[a-z]{1,10}", fullmatch=True)


# ---------------------------------------------------------------------------
# Property 1: Transport detection correctness
# ---------------------------------------------------------------------------


# Feature: smartclaw-mcp-protocol, Property 1: Transport detection correctness
@given(url=_url)
@settings(max_examples=100)
def test_explicit_http_type_returns_http(url: str) -> None:
    """When type is explicitly 'http', detect_transport returns 'http'.

    **Validates: Requirements 2.1, 3.1, 3.2, 4.1, 4.2, 4.3**
    """
    config = MCPServerConfig(type="http", url=url)
    assert detect_transport(config) == "http"


# Feature: smartclaw-mcp-protocol, Property 1: Transport detection correctness
@given(url=_url)
@settings(max_examples=100)
def test_explicit_sse_type_maps_to_http(url: str) -> None:
    """When type is explicitly 'sse', detect_transport returns 'http'.

    **Validates: Requirements 2.1, 3.1, 3.2, 4.1, 4.2, 4.3**
    """
    config = MCPServerConfig(type="sse", url=url)
    assert detect_transport(config) == "http"


# Feature: smartclaw-mcp-protocol, Property 1: Transport detection correctness
@given(command=_command)
@settings(max_examples=100)
def test_explicit_stdio_type_returns_stdio(command: str) -> None:
    """When type is explicitly 'stdio', detect_transport returns 'stdio'.

    **Validates: Requirements 2.1, 3.1, 3.2, 4.1, 4.2, 4.3**
    """
    config = MCPServerConfig(type="stdio", command=command)
    assert detect_transport(config) == "stdio"


# Feature: smartclaw-mcp-protocol, Property 1: Transport detection correctness
@given(url=_url)
@settings(max_examples=100)
def test_url_without_type_autodetects_http(url: str) -> None:
    """When url is present and type is None, detect_transport returns 'http'.

    **Validates: Requirements 2.1, 3.1, 3.2, 4.1, 4.2, 4.3**
    """
    config = MCPServerConfig(url=url)
    assert detect_transport(config) == "http"


# Feature: smartclaw-mcp-protocol, Property 1: Transport detection correctness
@given(command=_command)
@settings(max_examples=100)
def test_command_without_type_or_url_autodetects_stdio(command: str) -> None:
    """When command is present, no url, no type, detect_transport returns 'stdio'.

    **Validates: Requirements 2.1, 3.1, 3.2, 4.1, 4.2, 4.3**
    """
    config = MCPServerConfig(command=command)
    assert detect_transport(config) == "stdio"


# Feature: smartclaw-mcp-protocol, Property 1: Transport detection correctness
@given(data=st.data())
@settings(max_examples=100)
def test_neither_url_nor_command_raises(data: st.DataObject) -> None:
    """When neither url nor command is present, detect_transport raises ValueError.

    **Validates: Requirements 2.1, 3.1, 3.2, 4.1, 4.2, 4.3**
    """
    config = MCPServerConfig()
    with pytest.raises(ValueError, match="neither"):
        detect_transport(config)
