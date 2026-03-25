"""Property-based tests for SkillsRegistry.

Uses hypothesis with @settings(max_examples=100, deadline=None).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from smartclaw.skills.loader import SkillsLoader
from smartclaw.skills.registry import SkillsRegistry
from smartclaw.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_segment = st.from_regex(r"[a-zA-Z0-9]{1,10}", fullmatch=True)
_valid_name = st.builds(
    lambda segs: "-".join(segs),
    st.lists(_segment, min_size=1, max_size=3),
).filter(lambda n: 1 <= len(n) <= 64)


class _DummyInput(BaseModel):
    """Minimal input schema for mock tools."""
    pass


def _make_mock_tool(name: str) -> BaseTool:
    """Create a minimal BaseTool instance with the given name."""
    tool = MagicMock(spec=BaseTool)
    tool.name = name
    return tool


# ---------------------------------------------------------------------------
# Property 14: Skill Register/Get Round-Trip
# ---------------------------------------------------------------------------


# Feature: smartclaw-p1-enhanced-capabilities, Property 14: Skill Register/Get Round-Trip
@given(name=_valid_name)
@settings(max_examples=100, deadline=None)
def test_register_then_get_returns_module(name: str) -> None:
    """For any skill name and module, register then get returns the module.
    Calling get with an unregistered name returns None.

    **Validates: Requirements 7.1, 7.3**
    """
    loader = MagicMock(spec=SkillsLoader)
    tool_registry = ToolRegistry()
    registry = SkillsRegistry(loader, tool_registry)

    module = object()
    registry.register(name, module)

    # get returns the registered module
    assert registry.get(name) is module

    # unregistered name returns None
    assert registry.get(name + "-nonexistent") is None


# Feature: smartclaw-p1-enhanced-capabilities, Property 14: Skill Register/Get Round-Trip (multiple)
@given(names=st.lists(_valid_name, min_size=1, max_size=10, unique=True))
@settings(max_examples=100, deadline=None)
def test_register_multiple_then_get_each(names: list[str]) -> None:
    """For any set of distinct skill names, registering each then getting
    each returns the correct module.

    **Validates: Requirements 7.1, 7.3**
    """
    loader = MagicMock(spec=SkillsLoader)
    tool_registry = ToolRegistry()
    registry = SkillsRegistry(loader, tool_registry)

    modules = {}
    for name in names:
        mod = object()
        modules[name] = mod
        registry.register(name, mod)

    for name, mod in modules.items():
        assert registry.get(name) is mod


# ---------------------------------------------------------------------------
# Property 15: Unregister Removes Skill and Tools
# ---------------------------------------------------------------------------


# Feature: smartclaw-p1-enhanced-capabilities, Property 15: Unregister Removes Skill and Tools
@given(name=_valid_name, tool_count=st.integers(min_value=0, max_value=5))
@settings(max_examples=100, deadline=None)
def test_unregister_removes_skill_and_tools(name: str, tool_count: int) -> None:
    """For any registered skill with associated tools, unregister makes
    get return None and removes the skill's tools from ToolRegistry.

    **Validates: Requirements 7.2, 7.6**
    """
    loader = MagicMock(spec=SkillsLoader)
    tool_registry = ToolRegistry()
    registry = SkillsRegistry(loader, tool_registry)

    # Create mock tools
    tools = [_make_mock_tool(f"{name}-tool-{i}") for i in range(tool_count)]

    # Register skill with tools (as a list of BaseTool)
    registry.register(name, tools)

    # Verify tools are registered
    for tool in tools:
        assert tool_registry.get(tool.name) is not None

    # Unregister
    registry.unregister(name)

    # Skill should be gone
    assert registry.get(name) is None

    # Tools should be removed from ToolRegistry
    for tool in tools:
        assert tool_registry.get(tool.name) is None


# Feature: smartclaw-p1-enhanced-capabilities, Property 15: Unregister idempotent
@given(name=_valid_name)
@settings(max_examples=100, deadline=None)
def test_unregister_nonexistent_is_silent(name: str) -> None:
    """Unregistering a skill that doesn't exist is silently ignored.

    **Validates: Requirements 7.2, 7.6**
    """
    loader = MagicMock(spec=SkillsLoader)
    tool_registry = ToolRegistry()
    registry = SkillsRegistry(loader, tool_registry)

    # Should not raise
    registry.unregister(name)
    assert registry.get(name) is None


# ---------------------------------------------------------------------------
# Property 16: Skill List Sorted
# ---------------------------------------------------------------------------


# Feature: smartclaw-p1-enhanced-capabilities, Property 16: Skill List Sorted
@given(names=st.lists(_valid_name, min_size=0, max_size=15, unique=True))
@settings(max_examples=100, deadline=None)
def test_list_skills_returns_sorted_names(names: list[str]) -> None:
    """For any set of registered skills, list_skills returns skill names
    in ascending lexicographic order.

    **Validates: Requirements 7.4**
    """
    loader = MagicMock(spec=SkillsLoader)
    tool_registry = ToolRegistry()
    registry = SkillsRegistry(loader, tool_registry)

    for name in names:
        registry.register(name, object())

    result = registry.list_skills()
    assert result == sorted(names)
    assert len(result) == len(names)
