"""Property-based tests for MCPManager.

Uses hypothesis with @settings(max_examples=100).
Tests Properties 2, 3, 4, 11.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from mcp import types as mcp_types

from smartclaw.mcp.config import MCPConfig, MCPServerConfig
from smartclaw.mcp.manager import MCPManager, ServerConnection


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_server_name = st.from_regex(r"[a-z][a-z0-9]{0,9}", fullmatch=True)
_tool_name = st.from_regex(r"[a-z][a-z0-9_]{0,14}", fullmatch=True)


def _make_mock_tool(name: str) -> mcp_types.Tool:
    """Create a mock MCP Tool."""
    return mcp_types.Tool(
        name=name,
        description=f"Tool {name}",
        inputSchema={"type": "object", "properties": {}},
    )


def _make_server_connection(name: str, tools: list[mcp_types.Tool] | None = None) -> ServerConnection:
    """Create a mock ServerConnection."""
    session = AsyncMock()
    client_cm = AsyncMock()
    session_cm = AsyncMock()
    return ServerConnection(
        name=name,
        session=session,
        tools=tools or [],
        _client_cm=client_cm,
        _session_cm=session_cm,
    )


def _run_async(coro: Any) -> Any:
    """Run an async coroutine in a new event loop (safe for hypothesis)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Property 2: Initialization connects exactly enabled and successful servers
# ---------------------------------------------------------------------------


# Feature: smartclaw-mcp-protocol, Property 2: Initialization connects exactly the enabled and successful servers
@given(
    enabled_names=st.lists(_server_name, min_size=1, max_size=5, unique=True),
    disabled_names=st.lists(_server_name, min_size=0, max_size=3, unique=True),
    fail_indices=st.data(),
)
@settings(max_examples=100)
def test_initialization_connects_enabled_successful(
    enabled_names: list[str],
    disabled_names: list[str],
    fail_indices: st.DataObject,
) -> None:
    """After initialize(), get_connected_servers() returns exactly the set of
    server names that were both enabled and successfully connected.

    **Validates: Requirements 1.1, 1.2, 1.4, 1.7**
    """
    # Make names disjoint
    disabled_names = [f"dis_{n}" for n in disabled_names]

    # Decide which enabled servers fail
    num_fail = fail_indices.draw(st.integers(min_value=0, max_value=len(enabled_names) - 1))
    fail_set = set(enabled_names[:num_fail])
    success_set = set(enabled_names) - fail_set

    # Build config
    servers: dict[str, MCPServerConfig] = {}
    for name in enabled_names:
        servers[name] = MCPServerConfig(enabled=True, command="test")
    for name in disabled_names:
        servers[name] = MCPServerConfig(enabled=False, command="test")

    config = MCPConfig(enabled=True, servers=servers)

    manager = MCPManager()

    async def mock_connect(self_name: str, cfg: MCPServerConfig) -> ServerConnection:
        if self_name in fail_set:
            raise ConnectionError(f"Failed: {self_name}")
        return _make_server_connection(self_name)

    with patch.object(MCPManager, "_connect_server", side_effect=mock_connect):
        _run_async(manager.initialize(config))

    connected = set(manager.get_connected_servers())
    assert connected == success_set


# ---------------------------------------------------------------------------
# Property 3: Close releases all sessions
# ---------------------------------------------------------------------------


# Feature: smartclaw-mcp-protocol, Property 3: Close releases all sessions
@given(names=st.lists(_server_name, min_size=1, max_size=5, unique=True))
@settings(max_examples=100)
def test_close_releases_all_sessions(names: list[str]) -> None:
    """After close(), all sessions are closed and _servers is empty.

    **Validates: Requirements 1.5**
    """
    manager = MCPManager()
    for name in names:
        manager._servers[name] = _make_server_connection(name)

    _run_async(manager.close())

    assert len(manager._servers) == 0
    assert manager._closed is True


# ---------------------------------------------------------------------------
# Property 4: Close prevents new tool calls
# ---------------------------------------------------------------------------


# Feature: smartclaw-mcp-protocol, Property 4: Close prevents new tool calls
@given(
    server_name=_server_name,
    tool_name=_tool_name,
)
@settings(max_examples=100)
def test_close_prevents_new_tool_calls(server_name: str, tool_name: str) -> None:
    """After close(), every call_tool() returns an error string.

    **Validates: Requirements 9.4**
    """
    manager = MCPManager()
    _run_async(manager.close())

    result = _run_async(manager.call_tool(server_name, tool_name, {}))
    assert isinstance(result, str)
    assert "Error" in result
    assert "closed" in result.lower()


# ---------------------------------------------------------------------------
# Property 11: Tool discovery grouping
# ---------------------------------------------------------------------------


# Feature: smartclaw-mcp-protocol, Property 11: Tool discovery grouping
@given(
    server_tools=st.dictionaries(
        _server_name,
        st.lists(_tool_name, min_size=0, max_size=5, unique=True),
        min_size=1,
        max_size=5,
    ),
)
@settings(max_examples=100)
def test_tool_discovery_grouping(server_tools: dict[str, list[str]]) -> None:
    """get_all_tools() returns a mapping where each key is a connected server
    name and each value is the complete list of tools for that server.

    **Validates: Requirements 5.1, 5.2, 5.3, 5.4**
    """
    manager = MCPManager()

    for server_name, tool_names in server_tools.items():
        tools = [_make_mock_tool(tn) for tn in tool_names]
        manager._servers[server_name] = _make_server_connection(server_name, tools)

    result = manager.get_all_tools()

    assert set(result.keys()) == set(server_tools.keys())
    for server_name, tool_names in server_tools.items():
        result_tool_names = [t.name for t in result[server_name]]
        assert result_tool_names == tool_names
