# Feature: smartclaw-p2a-production-services, Property 5: Tools 端点返回所有已注册工具
"""Property tests for tools endpoint completeness.

**Validates: Requirements 5.1**
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from smartclaw.tools.registry import ToolRegistry
from tests.gateway.conftest import make_test_client


def _make_mock_tool(name: str, description: str) -> MagicMock:
    tool = MagicMock()
    tool.name = name
    tool.description = description
    return tool


# Strategy: generate a list of unique tool name/description pairs
_tool_names_st = st.lists(
    st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_"),
        min_size=1,
        max_size=20,
    ),
    min_size=0,
    max_size=10,
    unique=True,
)


# ---------------------------------------------------------------------------
# Property 5: Tools 端点返回所有已注册工具
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(_tool_names_st)
def test_tools_endpoint_returns_all_registered_tools(tool_names: list[str]) -> None:
    """GET /api/tools returns exactly the tools registered in ToolRegistry."""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke

    try:
        tools = [_make_mock_tool(name, f"desc_{name}") for name in tool_names]
        client, _, _, registry = make_test_client(tools=tools)
        with client:
            resp = client.get("/api/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == len(tool_names)
        returned_names = {item["name"] for item in data}
        assert returned_names == set(tool_names)
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


@settings(max_examples=100, deadline=None)
@given(_tool_names_st)
def test_tools_endpoint_descriptions_match(tool_names: list[str]) -> None:
    """GET /api/tools returns correct descriptions for each tool."""
    import smartclaw.agent.graph as graph_module
    original = graph_module.invoke

    try:
        tools = [_make_mock_tool(name, f"desc_{name}") for name in tool_names]
        client, _, _, registry = make_test_client(tools=tools)
        with client:
            resp = client.get("/api/tools")
        assert resp.status_code == 200
        data = resp.json()
        name_to_desc = {item["name"]: item["description"] for item in data}
        for name in tool_names:
            assert name_to_desc[name] == f"desc_{name}"
    finally:
        graph_module.invoke = original  # type: ignore[assignment]
