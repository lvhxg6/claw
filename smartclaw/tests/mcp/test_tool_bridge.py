"""Unit tests for MCPToolBridge."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp import types as mcp_types
from pydantic import BaseModel

from smartclaw.tools.mcp_tool import (
    MCPToolBridge,
    create_mcp_tools,
    json_schema_to_model,
    sanitize_tool_name,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bridge(
    server: str = "test_server",
    tool: str = "test_tool",
    manager: Any = None,
) -> MCPToolBridge:
    bridge = MCPToolBridge(
        name=sanitize_tool_name(server, tool),
        description=f"[MCP:{server}] A test tool",
        args_schema=type("Input", (BaseModel,), {}),
        server_name=server,
        original_tool_name=tool,
    )
    bridge._mcp_manager = manager
    return bridge


# ---------------------------------------------------------------------------
# Error result handling (is_error flag)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_error_result_returns_error_text() -> None:
    """When MCP server returns is_error=True, bridge returns the error text."""
    manager = AsyncMock()
    manager.call_tool = AsyncMock(return_value="Error: something went wrong")

    bridge = _make_bridge(manager=manager)
    result = await bridge._arun(arg1="value")
    assert "Error" in result


# ---------------------------------------------------------------------------
# Exception catching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exception_returns_error_string() -> None:
    """When call_tool raises, bridge catches and returns error string."""
    manager = MagicMock()
    manager.call_tool = AsyncMock(side_effect=RuntimeError("connection lost"))

    bridge = _make_bridge(manager=manager)
    result = await bridge._arun(arg1="value")
    assert "Error" in result
    assert "connection lost" in result


# ---------------------------------------------------------------------------
# No-description fallback
# ---------------------------------------------------------------------------


def test_no_description_fallback() -> None:
    """When MCP tool has no description, fallback text is used."""
    tool = mcp_types.Tool(
        name="my_tool",
        description="",
        inputSchema={"type": "object", "properties": {}},
    )
    manager = MagicMock()
    manager.get_all_tools.return_value = {"myserver": [tool]}

    bridges = create_mcp_tools(manager)
    assert len(bridges) == 1
    assert bridges[0].description == "[MCP:myserver] MCP tool from myserver server"


# ---------------------------------------------------------------------------
# Disconnected server returns error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disconnected_server_error() -> None:
    """call_tool to disconnected server returns error string."""
    manager = MagicMock()
    manager.call_tool = AsyncMock(return_value="Error: MCP server 'test_server' is disconnected")

    bridge = _make_bridge(manager=manager)
    result = await bridge._arun()
    assert "Error" in result


# ---------------------------------------------------------------------------
# Unknown server returns error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_server_error() -> None:
    """call_tool to unknown server returns error string."""
    manager = MagicMock()
    manager.call_tool = AsyncMock(return_value="Error: MCP server 'unknown' not found")

    bridge = _make_bridge(server="unknown", manager=manager)
    result = await bridge._arun()
    assert "Error" in result
    assert "not found" in result


# ---------------------------------------------------------------------------
# _run raises NotImplementedError
# ---------------------------------------------------------------------------


def test_run_raises() -> None:
    """_run() raises NotImplementedError."""
    bridge = _make_bridge()
    with pytest.raises(NotImplementedError):
        bridge._run()


# ---------------------------------------------------------------------------
# Schema conversion
# ---------------------------------------------------------------------------


def test_schema_conversion_basic() -> None:
    """Basic JSON Schema converts to BaseModel with correct fields."""
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "count": {"type": "integer"},
        },
        "required": ["name"],
    }
    model = json_schema_to_model(schema)
    assert issubclass(model, BaseModel)
    fields = model.model_fields
    assert "name" in fields
    assert "count" in fields


def test_schema_conversion_empty_fallback() -> None:
    """Empty schema falls back to dict[str, Any] model."""
    schema: dict[str, Any] = {"type": "object"}
    model = json_schema_to_model(schema)
    assert issubclass(model, BaseModel)
    assert "arguments" in model.model_fields


# ---------------------------------------------------------------------------
# Name sanitization edge cases
# ---------------------------------------------------------------------------


def test_sanitize_name_basic() -> None:
    """Basic sanitization produces expected format."""
    name = sanitize_tool_name("server1", "my_tool")
    assert name.startswith("mcp_")
    assert len(name) <= 64


def test_sanitize_name_special_chars() -> None:
    """Special characters are replaced and collapsed."""
    name = sanitize_tool_name("my server!", "tool@v2")
    assert name.startswith("mcp_")
    assert all(c in "abcdefghijklmnopqrstuvwxyz0123456789_-" for c in name)


def test_sanitize_name_long_input() -> None:
    """Very long names are truncated with hash suffix."""
    name = sanitize_tool_name("a" * 50, "b" * 50)
    assert len(name) <= 64
    assert name.startswith("mcp_")
