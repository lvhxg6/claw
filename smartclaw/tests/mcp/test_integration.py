"""Unit tests for Agent Graph MCP integration."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.tools import BaseTool
from mcp import types as mcp_types
from pydantic import BaseModel

from smartclaw.tools.mcp_tool import MCPToolBridge


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _DummyInput(BaseModel):
    pass


class _DummyTool(BaseTool):
    name: str = "dummy"
    description: str = "dummy"
    args_schema: type[BaseModel] = _DummyInput

    def _run(self, **kwargs: Any) -> str:
        return "ok"


def _make_mcp_tool(name: str) -> mcp_types.Tool:
    return mcp_types.Tool(
        name=name,
        description=f"MCP tool {name}",
        inputSchema={"type": "object", "properties": {}},
    )


# ---------------------------------------------------------------------------
# MCP disabled skips registration
# ---------------------------------------------------------------------------


def test_mcp_disabled_skips_registration() -> None:
    """When mcp_manager is None, no MCP tools are registered."""
    from smartclaw.tools.registry import ToolRegistry

    system_registry = ToolRegistry()
    system_registry.register(_DummyTool(name="sys_tool"))

    with patch("smartclaw.tools.registry.create_system_tools", return_value=system_registry):
        from smartclaw.agent.graph import create_all_tools

        result, _ = create_all_tools(
            [_DummyTool(name="browser_tool")],
            "/tmp/workspace",
            mcp_manager=None,
        )

    names = {t.name for t in result}
    assert "sys_tool" in names
    assert "browser_tool" in names
    # No MCP tools
    mcp_tools = [t for t in result if isinstance(t, MCPToolBridge)]
    assert len(mcp_tools) == 0


# ---------------------------------------------------------------------------
# Duplicate tool name replacement
# ---------------------------------------------------------------------------


def test_duplicate_tool_name_replacement() -> None:
    """When MCP tool has same name as existing tool, it replaces it."""
    from smartclaw.tools.registry import ToolRegistry

    system_registry = ToolRegistry()
    # Register a system tool with a name that will collide
    system_registry.register(_DummyTool(name="mcp_server_tool1"))

    manager = MagicMock()
    # This will produce a tool named mcp_server_tool1 after sanitization
    manager.get_all_tools.return_value = {"server": [_make_mcp_tool("tool1")]}

    with patch("smartclaw.tools.registry.create_system_tools", return_value=system_registry):
        from smartclaw.agent.graph import create_all_tools

        result, _ = create_all_tools(
            [],
            "/tmp/workspace",
            mcp_manager=manager,
        )

    # The MCP tool should have replaced the system tool
    matching = [t for t in result if t.name == "mcp_server_tool1"]
    assert len(matching) == 1
    assert isinstance(matching[0], MCPToolBridge)


# ---------------------------------------------------------------------------
# Combined tools produce valid list
# ---------------------------------------------------------------------------


def test_combined_tools_valid_list() -> None:
    """Browser + system + MCP tools produce a valid list[BaseTool]."""
    from smartclaw.tools.registry import ToolRegistry

    system_registry = ToolRegistry()
    system_registry.register(_DummyTool(name="sys_read"))
    system_registry.register(_DummyTool(name="sys_write"))

    browser_tools = [_DummyTool(name="browser_click"), _DummyTool(name="browser_type")]

    manager = MagicMock()
    manager.get_all_tools.return_value = {
        "server1": [_make_mcp_tool("search")],
        "server2": [_make_mcp_tool("fetch"), _make_mcp_tool("parse")],
    }

    with patch("smartclaw.tools.registry.create_system_tools", return_value=system_registry):
        from smartclaw.agent.graph import create_all_tools

        result, _ = create_all_tools(
            browser_tools,
            "/tmp/workspace",
            mcp_manager=manager,
        )

    assert isinstance(result, list)
    assert all(isinstance(t, BaseTool) for t in result)
    # 2 system + 2 browser + 3 MCP = 7
    assert len(result) == 7
