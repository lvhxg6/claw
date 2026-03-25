"""Property-based tests for ToolRegistry.

Uses hypothesis with @settings(max_examples=100).
"""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import BaseModel

from smartclaw.tools.base import SmartClawTool
from smartclaw.tools.registry import ToolRegistry


class _Input(BaseModel):
    pass


class _FakeTool(SmartClawTool):
    name: str = "fake"
    description: str = "fake"
    args_schema: type[BaseModel] = _Input

    async def _arun(self, **kwargs: Any) -> str:
        return "ok"


# Strategy: unique tool names (alphanumeric, 1-20 chars)
_tool_name = st.from_regex(r"[a-z][a-z0-9_]{0,19}", fullmatch=True)
_unique_names = st.lists(_tool_name, min_size=1, max_size=15, unique=True)


def _make_tool(name: str) -> _FakeTool:
    return _FakeTool(name=name, description=f"Tool {name}")


# ---------------------------------------------------------------------------
# Property 2: Registry register/get round-trip
# ---------------------------------------------------------------------------


# Feature: smartclaw-tool-system, Property 2: Registry register/get round-trip
@given(names=_unique_names)
@settings(max_examples=100)
def test_register_get_roundtrip(names: list[str]) -> None:
    """For any list of tools with unique names, after registering,
    get(name) returns the corresponding tool instance.

    **Validates: Requirements 2.1, 2.2, 2.3**
    """
    reg = ToolRegistry()
    tools = [_make_tool(n) for n in names]
    reg.register_many(tools)

    for tool in tools:
        assert reg.get(tool.name) is tool


# ---------------------------------------------------------------------------
# Property 3: Registry list_tools returns sorted names
# ---------------------------------------------------------------------------


# Feature: smartclaw-tool-system, Property 3: Registry list_tools sorted
@given(names=_unique_names)
@settings(max_examples=100)
def test_list_tools_sorted(names: list[str]) -> None:
    """For any set of registered tools, list_tools() returns sorted ascending
    lexicographic order with exactly all registered names.

    **Validates: Requirements 2.4**
    """
    reg = ToolRegistry()
    for n in names:
        reg.register(_make_tool(n))

    result = reg.list_tools()
    assert result == sorted(names)


# ---------------------------------------------------------------------------
# Property 4: Registry size invariant
# ---------------------------------------------------------------------------


# Feature: smartclaw-tool-system, Property 4: Registry size invariant
@given(names=_unique_names)
@settings(max_examples=100)
def test_registry_size_invariant(names: list[str]) -> None:
    """For any set of tools with unique names, count equals len(get_all())
    and both equal the number of unique names registered.

    **Validates: Requirements 2.5, 2.8**
    """
    reg = ToolRegistry()
    for n in names:
        reg.register(_make_tool(n))

    assert reg.count == len(reg.get_all())
    assert reg.count == len(names)


# ---------------------------------------------------------------------------
# Property 5: Registry duplicate replacement
# ---------------------------------------------------------------------------


# Feature: smartclaw-tool-system, Property 5: Registry duplicate replacement
@given(name=_tool_name)
@settings(max_examples=100)
def test_duplicate_replacement(name: str) -> None:
    """For two tools sharing the same name, registering first then second
    results in get(name) returning the second; count remains 1.

    **Validates: Requirements 2.6**
    """
    reg = ToolRegistry()
    tool1 = _make_tool(name)
    tool2 = _FakeTool(name=name, description="second")

    reg.register(tool1)
    reg.register(tool2)

    assert reg.get(name) is tool2
    assert reg.count == 1


# ---------------------------------------------------------------------------
# Property 6: Registry merge is set union
# ---------------------------------------------------------------------------


# Feature: smartclaw-tool-system, Property 6: Registry merge union
@given(
    names_a=st.lists(_tool_name, min_size=1, max_size=8, unique=True),
    names_b=st.lists(_tool_name, min_size=1, max_size=8, unique=True),
)
@settings(max_examples=100)
def test_merge_union(names_a: list[str], names_b: list[str]) -> None:
    """For two registries with disjoint names, after merge, first registry
    contains all tools from both; count equals sum of original counts.

    **Validates: Requirements 2.7**
    """
    # Make names disjoint by prefixing
    names_a = [f"a_{n}" for n in names_a]
    names_b = [f"b_{n}" for n in names_b]

    reg_a = ToolRegistry()
    reg_b = ToolRegistry()

    for n in names_a:
        reg_a.register(_make_tool(n))
    for n in names_b:
        reg_b.register(_make_tool(n))

    original_a_count = reg_a.count
    original_b_count = reg_b.count

    reg_a.merge(reg_b)

    assert reg_a.count == original_a_count + original_b_count
    for n in names_a + names_b:
        assert reg_a.get(n) is not None
