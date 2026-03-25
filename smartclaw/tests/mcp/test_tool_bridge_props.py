"""Property-based tests for MCP Tool Bridge.

Uses hypothesis with @settings(max_examples=100).
Tests Properties 5, 6, 7, 8, 9, 14.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from hypothesis import given, settings, assume
from hypothesis import strategies as st
from mcp import types as mcp_types
from pydantic import BaseModel

from smartclaw.tools.mcp_tool import (
    MCPToolBridge,
    create_mcp_tools,
    json_schema_to_model,
    sanitize_tool_name,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_server_name = st.from_regex(r"[a-z][a-z0-9]{0,9}", fullmatch=True)
_tool_name = st.from_regex(r"[a-z][a-z0-9_]{0,14}", fullmatch=True)
_any_string = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S")),
    min_size=1,
    max_size=30,
)
_description = st.text(min_size=1, max_size=50)

_json_type = st.sampled_from(["string", "integer", "number", "boolean", "array", "object"])
_json_schema = st.fixed_dictionaries(
    {"type": st.just("object")},
    optional={
        "properties": st.dictionaries(
            st.from_regex(r"[a-z]{1,8}", fullmatch=True),
            st.fixed_dictionaries({"type": _json_type}),
            min_size=0,
            max_size=5,
        ),
    },
)


def _make_mock_tool(name: str, description: str = "A tool", input_schema: dict[str, Any] | None = None) -> mcp_types.Tool:
    """Create a mock MCP Tool."""
    schema = input_schema or {"type": "object", "properties": {}}
    return mcp_types.Tool(name=name, description=description, inputSchema=schema)


# ---------------------------------------------------------------------------
# Property 5: Tool name sanitization invariants
# ---------------------------------------------------------------------------


# Feature: smartclaw-mcp-protocol, Property 5: Tool name sanitization invariants
@given(server=_any_string, tool=_any_string)
@settings(max_examples=100)
def test_sanitized_name_format(server: str, tool: str) -> None:
    """Sanitized name matches ^[a-z0-9_-]+$, is at most 64 chars, starts with mcp_.

    **Validates: Requirements 6.2, 6.3**
    """
    name = sanitize_tool_name(server, tool)
    assert re.fullmatch(r"[a-z0-9_\-]+", name), f"Invalid chars in: {name!r}"
    assert len(name) <= 64, f"Name too long ({len(name)}): {name!r}"
    assert name.startswith("mcp_"), f"Missing mcp_ prefix: {name!r}"


# Feature: smartclaw-mcp-protocol, Property 5: Tool name sanitization invariants
@given(
    server1=_server_name,
    tool1=_tool_name,
    server2=_server_name,
    tool2=_tool_name,
)
@settings(max_examples=100)
def test_distinct_inputs_produce_distinct_names(
    server1: str, tool1: str, server2: str, tool2: str
) -> None:
    """Two distinct (server, tool) pairs produce distinct sanitized names.

    **Validates: Requirements 6.2, 6.3**
    """
    assume((server1, tool1) != (server2, tool2))
    name1 = sanitize_tool_name(server1, tool1)
    name2 = sanitize_tool_name(server2, tool2)
    assert name1 != name2, f"Collision: ({server1}, {tool1}) and ({server2}, {tool2}) both → {name1!r}"


# ---------------------------------------------------------------------------
# Property 6: Tool description format
# ---------------------------------------------------------------------------


# Feature: smartclaw-mcp-protocol, Property 6: Tool description format
@given(server=_server_name, desc=_description)
@settings(max_examples=100)
def test_description_with_content(server: str, desc: str) -> None:
    """For non-empty description, bridge description is '[MCP:{server}] {desc}'.

    **Validates: Requirements 6.4, 6.5**
    """
    tool = _make_mock_tool("test_tool", description=desc)
    manager = MagicMock()
    manager.get_all_tools.return_value = {server: [tool]}

    bridges = create_mcp_tools(manager)
    assert len(bridges) == 1
    assert bridges[0].description == f"[MCP:{server}] {desc}"


# Feature: smartclaw-mcp-protocol, Property 6: Tool description format
@given(server=_server_name)
@settings(max_examples=100)
def test_description_fallback_when_empty(server: str) -> None:
    """For empty description, bridge description is '[MCP:{server}] MCP tool from {server} server'.

    **Validates: Requirements 6.4, 6.5**
    """
    tool = _make_mock_tool("test_tool", description="")
    manager = MagicMock()
    manager.get_all_tools.return_value = {server: [tool]}

    bridges = create_mcp_tools(manager)
    assert len(bridges) == 1
    assert bridges[0].description == f"[MCP:{server}] MCP tool from {server} server"


# ---------------------------------------------------------------------------
# Property 7: Tool bridge creation count
# ---------------------------------------------------------------------------


# Feature: smartclaw-mcp-protocol, Property 7: Tool bridge creation count
@given(
    server_tools=st.dictionaries(
        _server_name,
        st.lists(_tool_name, min_size=0, max_size=5, unique=True),
        min_size=1,
        max_size=4,
    ),
)
@settings(max_examples=100)
def test_bridge_creation_count(server_tools: dict[str, list[str]]) -> None:
    """create_mcp_tools() returns exactly one BaseTool per discovered MCP tool.

    **Validates: Requirements 6.1**
    """
    all_tools: dict[str, list[mcp_types.Tool]] = {}
    total_count = 0
    for server_name, tool_names in server_tools.items():
        tools = [_make_mock_tool(tn) for tn in tool_names]
        all_tools[server_name] = tools
        total_count += len(tools)

    manager = MagicMock()
    manager.get_all_tools.return_value = all_tools

    bridges = create_mcp_tools(manager)
    assert len(bridges) == total_count


# ---------------------------------------------------------------------------
# Property 8: Tool call delegation correctness
# ---------------------------------------------------------------------------


# Feature: smartclaw-mcp-protocol, Property 8: Tool call delegation correctness
@given(
    server=_server_name,
    tool=_tool_name,
    args=st.dictionaries(
        st.from_regex(r"[a-z]{1,5}", fullmatch=True),
        st.text(min_size=0, max_size=10),
        min_size=0,
        max_size=3,
    ),
)
@settings(max_examples=100)
def test_tool_call_delegation(server: str, tool: str, args: dict[str, str]) -> None:
    """_arun() invokes MCPManager.call_tool() with original server name,
    original tool name, and exact arguments.

    **Validates: Requirements 6.7**
    """
    manager = MagicMock()
    manager.call_tool = AsyncMock(return_value="ok")

    bridge = MCPToolBridge(
        name=sanitize_tool_name(server, tool),
        description=f"[MCP:{server}] test",
        args_schema=type("Input", (BaseModel,), {}),
        server_name=server,
        original_tool_name=tool,
    )
    bridge._mcp_manager = manager

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(bridge._arun(**args))
    finally:
        loop.close()

    manager.call_tool.assert_called_once_with(server, tool, args)
    assert result == "ok"


# ---------------------------------------------------------------------------
# Property 9: Text content extraction
# ---------------------------------------------------------------------------


# Feature: smartclaw-mcp-protocol, Property 9: Text content extraction
@given(texts=st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=5))
@settings(max_examples=100)
def test_text_content_extraction(texts: list[str]) -> None:
    """For any list of text content parts, the result is texts joined by newlines.

    **Validates: Requirements 6.9**
    """
    from smartclaw.mcp.manager import MCPManager

    manager = MCPManager()

    # Create a mock server connection
    content_parts = [mcp_types.TextContent(type="text", text=t) for t in texts]
    mock_result = mcp_types.CallToolResult(content=content_parts, isError=False)

    mock_session = AsyncMock()
    mock_session.call_tool = AsyncMock(return_value=mock_result)

    from smartclaw.mcp.manager import ServerConnection

    conn = ServerConnection(
        name="test_server",
        session=mock_session,
        tools=[],
        _client_cm=AsyncMock(),
        _session_cm=AsyncMock(),
    )
    manager._servers["test_server"] = conn

    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(
            manager.call_tool("test_server", "test_tool", {})
        )
    finally:
        loop.close()

    expected = "\n".join(texts)
    assert result == expected


# ---------------------------------------------------------------------------
# Property 14: Schema conversion produces BaseModel
# ---------------------------------------------------------------------------


# Feature: smartclaw-mcp-protocol, Property 14: Schema conversion produces BaseModel
@given(schema=_json_schema)
@settings(max_examples=100)
def test_schema_conversion_produces_basemodel(schema: dict[str, Any]) -> None:
    """For any valid JSON Schema dict, json_schema_to_model produces a BaseModel subclass.

    **Validates: Requirements 6.6**
    """
    model = json_schema_to_model(schema)
    assert isinstance(model, type)
    assert issubclass(model, BaseModel)
