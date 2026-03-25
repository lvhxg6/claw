"""Unit tests for MCPManager."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp import types as mcp_types

from smartclaw.mcp.config import (
    MCPConfig,
    MCPInitializationError,
    MCPServerConfig,
)
from smartclaw.mcp.manager import MCPManager, ServerConnection, _merge_env, detect_transport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_server_connection(name: str, tools: list[mcp_types.Tool] | None = None) -> ServerConnection:
    session = AsyncMock()
    return ServerConnection(
        name=name,
        session=session,
        tools=tools or [],
        _client_cm=AsyncMock(),
        _session_cm=AsyncMock(),
    )


# ---------------------------------------------------------------------------
# Connect/close happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifecycle_happy_path() -> None:
    """Connect to servers, verify connected, close, verify empty."""
    manager = MCPManager()

    config = MCPConfig(
        enabled=True,
        servers={
            "s1": MCPServerConfig(command="test1"),
            "s2": MCPServerConfig(command="test2"),
        },
    )

    async def mock_connect(name: str, cfg: MCPServerConfig) -> ServerConnection:
        return _make_server_connection(name)

    with patch.object(MCPManager, "_connect_server", side_effect=mock_connect):
        await manager.initialize(config)

    assert set(manager.get_connected_servers()) == {"s1", "s2"}

    await manager.close()
    assert manager.get_connected_servers() == []
    assert manager._closed is True


# ---------------------------------------------------------------------------
# All-fail raises MCPInitializationError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_fail_raises_initialization_error() -> None:
    """When all enabled servers fail, MCPInitializationError is raised."""
    manager = MCPManager()

    config = MCPConfig(
        enabled=True,
        servers={
            "s1": MCPServerConfig(command="bad1"),
            "s2": MCPServerConfig(command="bad2"),
        },
    )

    async def mock_connect(name: str, cfg: MCPServerConfig) -> ServerConnection:
        raise ConnectionError(f"Failed: {name}")

    with patch.object(MCPManager, "_connect_server", side_effect=mock_connect):
        with pytest.raises(MCPInitializationError, match="All enabled"):
            await manager.initialize(config)


# ---------------------------------------------------------------------------
# In-flight wait on close
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inflight_wait_on_close() -> None:
    """close() waits for in-flight call_tool to complete before closing."""
    manager = MCPManager()

    content = [mcp_types.TextContent(type="text", text="result")]
    mock_result = mcp_types.CallToolResult(content=content, isError=False)

    mock_session = AsyncMock()

    call_started = asyncio.Event()
    call_proceed = asyncio.Event()

    async def slow_call_tool(tool_name: str, arguments: dict[str, Any]) -> mcp_types.CallToolResult:
        call_started.set()
        await call_proceed.wait()
        return mock_result

    mock_session.call_tool = slow_call_tool

    conn = _make_server_connection("s1")
    conn.session = mock_session
    manager._servers["s1"] = conn

    # Start a tool call
    call_task = asyncio.create_task(manager.call_tool("s1", "tool1", {}))

    await call_started.wait()

    # Start close — should wait
    close_task = asyncio.create_task(manager.close())

    # Let the call finish
    await asyncio.sleep(0.05)
    assert not close_task.done(), "close() should wait for in-flight calls"

    call_proceed.set()
    result = await call_task
    assert result == "result"

    await close_task
    assert manager._closed is True


# ---------------------------------------------------------------------------
# Call to unknown server
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_unknown_server() -> None:
    """call_tool to unknown server returns error string."""
    manager = MCPManager()
    result = await manager.call_tool("nonexistent", "tool", {})
    assert "Error" in result
    assert "not found" in result


# ---------------------------------------------------------------------------
# Call to disconnected server (session raises)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_disconnected_server() -> None:
    """call_tool to a server whose session raises returns error string."""
    manager = MCPManager()

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(side_effect=ConnectionError("disconnected"))

    conn = _make_server_connection("s1")
    conn.session = mock_session
    manager._servers["s1"] = conn

    result = await manager.call_tool("s1", "tool1", {})
    assert "Error" in result
    assert "disconnected" in result


# ---------------------------------------------------------------------------
# Missing env_file raises FileNotFoundError
# ---------------------------------------------------------------------------


def test_missing_env_file_raises() -> None:
    """_merge_env raises FileNotFoundError for missing env_file."""
    config = MCPServerConfig(command="test", env_file="/nonexistent/path/.env")
    with pytest.raises(FileNotFoundError, match="env_file not found"):
        _merge_env(config)


# ---------------------------------------------------------------------------
# Stdio args/env passthrough
# ---------------------------------------------------------------------------


def test_detect_transport_stdio() -> None:
    """Stdio transport detected for command-only config."""
    config = MCPServerConfig(command="npx", args=["-y", "server"])
    assert detect_transport(config) == "stdio"


def test_detect_transport_http() -> None:
    """HTTP transport detected for url-only config."""
    config = MCPServerConfig(url="https://example.com/mcp")
    assert detect_transport(config) == "http"


def test_detect_transport_explicit_overrides() -> None:
    """Explicit type overrides auto-detection."""
    config = MCPServerConfig(type="http", command="npx")
    assert detect_transport(config) == "http"


# ---------------------------------------------------------------------------
# Disabled servers are skipped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_servers_skipped() -> None:
    """Disabled servers are not connected."""
    manager = MCPManager()

    config = MCPConfig(
        enabled=True,
        servers={
            "active": MCPServerConfig(enabled=True, command="test"),
            "inactive": MCPServerConfig(enabled=False, command="test"),
        },
    )

    async def mock_connect(name: str, cfg: MCPServerConfig) -> ServerConnection:
        return _make_server_connection(name)

    with patch.object(MCPManager, "_connect_server", side_effect=mock_connect):
        await manager.initialize(config)

    assert manager.get_connected_servers() == ["active"]


# ---------------------------------------------------------------------------
# MCP disabled skips everything
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_disabled_skips_init() -> None:
    """When MCP is disabled, initialize does nothing."""
    manager = MCPManager()
    config = MCPConfig(enabled=False, servers={"s1": MCPServerConfig(command="test")})
    await manager.initialize(config)
    assert manager.get_connected_servers() == []
