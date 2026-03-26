"""Unit tests for smartclaw.agent.runtime — AgentRuntime + setup_agent_runtime."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from smartclaw.agent.runtime import AgentRuntime, setup_agent_runtime
from smartclaw.config.settings import SmartClawSettings
from smartclaw.providers.config import ModelConfig
from smartclaw.tools.registry import ToolRegistry


def _make_settings(**overrides) -> SmartClawSettings:
    """Create a SmartClawSettings with sensible test defaults."""
    s = SmartClawSettings()
    s.mcp.enabled = False
    s.skills.enabled = False
    s.sub_agent.enabled = False
    s.memory.enabled = False
    for k, v in overrides.items():
        parts = k.split(".")
        obj = s
        for p in parts[:-1]:
            obj = getattr(obj, p)
        setattr(obj, parts[-1], v)
    return s


@pytest.fixture
def mock_build_graph():
    """Patch build_graph at module level in runtime."""
    with patch("smartclaw.agent.runtime.build_graph") as m:
        m.return_value = MagicMock(name="compiled_graph")
        yield m


# -----------------------------------------------------------------------
# Task 1.3: setup_agent_runtime returns correct structure
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_returns_correct_structure(mock_build_graph):
    """setup_agent_runtime returns AgentRuntime with required fields."""
    settings = _make_settings()
    rt = await setup_agent_runtime(settings)

    assert isinstance(rt, AgentRuntime)
    assert rt.graph is not None
    assert rt.registry is not None
    assert isinstance(rt.registry, ToolRegistry)
    assert rt.system_prompt is not None
    assert isinstance(rt.system_prompt, str)
    assert rt.model_config is not None
    assert rt.registry.count >= 8


@pytest.mark.asyncio
async def test_setup_all_disabled(mock_build_graph):
    """When all optional features disabled, optional components are None."""
    settings = _make_settings()
    rt = await setup_agent_runtime(settings)

    assert rt.memory_store is None
    assert rt.summarizer is None
    assert rt.mcp_manager is None
    assert rt.registry.get("spawn_sub_agent") is None


@pytest.mark.asyncio
async def test_setup_sub_agent_enabled(mock_build_graph):
    """sub_agent.enabled=True registers spawn_sub_agent tool."""
    settings = _make_settings(**{"sub_agent.enabled": True})
    rt = await setup_agent_runtime(settings)

    assert rt.registry.get("spawn_sub_agent") is not None
    assert "spawn_sub_agent" in rt.tool_names


@pytest.mark.asyncio
async def test_setup_memory_enabled(mock_build_graph):
    """memory.enabled=True initializes memory_store and summarizer."""
    settings = _make_settings(**{"memory.enabled": True})

    with patch("smartclaw.memory.store.MemoryStore", autospec=True) as ms_cls:
        ms_instance = AsyncMock()
        ms_instance.close = AsyncMock()
        ms_cls.return_value = ms_instance

        rt = await setup_agent_runtime(settings)

    assert rt.memory_store is not None
    assert rt.summarizer is not None


# -----------------------------------------------------------------------
# Task 1.3: Component failure tolerance
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sub_agent_failure_tolerance(mock_build_graph):
    """If SpawnSubAgentTool creation fails, runtime still works."""
    settings = _make_settings(**{"sub_agent.enabled": True})

    with patch(
        "smartclaw.agent.sub_agent.SpawnSubAgentTool",
        side_effect=RuntimeError("boom"),
    ):
        rt = await setup_agent_runtime(settings)

    assert rt.graph is not None
    assert rt.registry.get("spawn_sub_agent") is None


@pytest.mark.asyncio
async def test_memory_failure_tolerance(mock_build_graph):
    """If MemoryStore.initialize() fails, memory_store and summarizer are None."""
    settings = _make_settings(**{"memory.enabled": True})

    with patch("smartclaw.memory.store.MemoryStore", autospec=True) as ms_cls:
        ms_instance = AsyncMock()
        ms_instance.initialize = AsyncMock(side_effect=RuntimeError("db error"))
        ms_cls.return_value = ms_instance

        rt = await setup_agent_runtime(settings)

    assert rt.memory_store is None
    assert rt.summarizer is None


# -----------------------------------------------------------------------
# Task 1.3: close() tests
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_calls_resources():
    """close() calls close on memory_store and mcp_manager."""
    mock_mem = AsyncMock()
    mock_mcp = AsyncMock()

    rt = AgentRuntime(
        graph=MagicMock(),
        registry=ToolRegistry(),
        memory_store=mock_mem,
        summarizer=None,
        system_prompt="test",
        mcp_manager=mock_mcp,
        model_config=ModelConfig(),
    )

    await rt.close()

    mock_mem.close.assert_awaited_once()
    mock_mcp.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_with_none_resources():
    """close() works fine when memory_store and mcp_manager are None."""
    rt = AgentRuntime(
        graph=MagicMock(),
        registry=ToolRegistry(),
        memory_store=None,
        summarizer=None,
        system_prompt="test",
        mcp_manager=None,
        model_config=ModelConfig(),
    )

    await rt.close()


@pytest.mark.asyncio
async def test_close_exception_tolerance():
    """close() does not propagate exceptions from resources."""
    mock_mem = AsyncMock()
    mock_mem.close = AsyncMock(side_effect=RuntimeError("close failed"))
    mock_mcp = AsyncMock()
    mock_mcp.close = AsyncMock(side_effect=OSError("connection lost"))

    rt = AgentRuntime(
        graph=MagicMock(),
        registry=ToolRegistry(),
        memory_store=mock_mem,
        summarizer=None,
        system_prompt="test",
        mcp_manager=mock_mcp,
        model_config=ModelConfig(),
    )

    await rt.close()

    mock_mem.close.assert_awaited_once()
    mock_mcp.close.assert_awaited_once()


# -----------------------------------------------------------------------
# Task 1.3: tools / tool_names properties
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tools_property(mock_build_graph):
    """tools property returns registry.get_all()."""
    settings = _make_settings()
    rt = await setup_agent_runtime(settings)

    assert rt.tools == rt.registry.get_all()
    assert len(rt.tools) >= 8


@pytest.mark.asyncio
async def test_tool_names_sorted(mock_build_graph):
    """tool_names returns sorted list."""
    settings = _make_settings()
    rt = await setup_agent_runtime(settings)

    names = rt.tool_names
    assert names == sorted(names)
