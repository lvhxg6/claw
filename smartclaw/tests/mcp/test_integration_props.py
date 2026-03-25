"""Property-based tests for Agent Graph integration.

Uses hypothesis with @settings(max_examples=100).
Tests Property 13.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st
from langchain_core.tools import BaseTool
from mcp import types as mcp_types
from pydantic import BaseModel

from smartclaw.tools.mcp_tool import MCPToolBridge


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_tool_name = st.from_regex(r"[a-z][a-z0-9_]{0,14}", fullmatch=True)


class _DummyInput(BaseModel):
    pass


class _DummyTool(BaseTool):
    name: str = "dummy"
    description: str = "dummy"
    args_schema: type[BaseModel] = _DummyInput

    def _run(self, **kwargs: Any) -> str:
        return "ok"


def _make_dummy_tool(name: str) -> _DummyTool:
    return _DummyTool(name=name, description=f"Tool {name}")


def _make_mcp_tool(name: str) -> mcp_types.Tool:
    return mcp_types.Tool(
        name=name,
        description=f"MCP tool {name}",
        inputSchema={"type": "object", "properties": {}},
    )


# ---------------------------------------------------------------------------
# Property 13: Registry merge includes all tool sources
# ---------------------------------------------------------------------------


# Feature: smartclaw-mcp-protocol, Property 13: Registry merge includes all tool sources
@given(
    browser_names=st.lists(_tool_name, min_size=1, max_size=4, unique=True),
    mcp_server_tools=st.dictionaries(
        st.from_regex(r"[a-z]{1,6}", fullmatch=True),
        st.lists(_tool_name, min_size=1, max_size=3, unique=True),
        min_size=1,
        max_size=3,
    ),
)
@settings(max_examples=100)
def test_registry_merge_includes_all_sources(
    browser_names: list[str],
    mcp_server_tools: dict[str, list[str]],
) -> None:
    """The resulting tool list contains every tool from browser, system, and MCP sources.

    **Validates: Requirements 8.1, 8.2**
    """
    # Prefix to avoid collisions
    browser_names = [f"browser_{n}" for n in browser_names]
    browser_tools = [_make_dummy_tool(n) for n in browser_names]

    # Build mock MCP manager
    all_mcp_tools: dict[str, list[mcp_types.Tool]] = {}
    for server_name, tool_names in mcp_server_tools.items():
        prefixed = [f"mcp_{server_name}_{tn}" for tn in tool_names]
        all_mcp_tools[server_name] = [_make_mcp_tool(tn) for tn in tool_names]

    manager = MagicMock()
    manager.get_all_tools.return_value = all_mcp_tools

    # Patch create_system_tools to return a known set
    from smartclaw.tools.registry import ToolRegistry

    system_registry = ToolRegistry()
    system_tools = [_make_dummy_tool(f"sys_{i}") for i in range(2)]
    system_registry.register_many(system_tools)

    with patch("smartclaw.tools.registry.create_system_tools", return_value=system_registry):
        from smartclaw.agent.graph import create_all_tools

        result, _skills_summary = create_all_tools(browser_tools, "/tmp/workspace", mcp_manager=manager)

    result_names = {t.name for t in result}

    # All browser tools present
    for name in browser_names:
        assert name in result_names, f"Missing browser tool: {name}"

    # All system tools present
    for t in system_tools:
        assert t.name in result_names, f"Missing system tool: {t.name}"

    # MCP tools present (sanitized names)
    total_mcp = sum(len(tools) for tools in all_mcp_tools.values())
    mcp_result_tools = [t for t in result if isinstance(t, MCPToolBridge)]
    assert len(mcp_result_tools) == total_mcp
