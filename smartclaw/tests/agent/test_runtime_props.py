"""Property-based tests for smartclaw.agent.runtime — AgentRuntime + setup_agent_runtime.

Uses hypothesis to verify correctness properties across randomized configurations.
"""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from smartclaw.agent.runtime import AgentRuntime, setup_agent_runtime
from smartclaw.config.settings import SmartClawSettings
from smartclaw.providers.config import ModelConfig
from smartclaw.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(
    mcp_enabled: bool = False,
    skills_enabled: bool = False,
    sub_agent_enabled: bool = False,
    memory_enabled: bool = False,
) -> SmartClawSettings:
    """Build SmartClawSettings with the given feature flags."""
    s = SmartClawSettings()
    s.mcp.enabled = mcp_enabled
    s.skills.enabled = skills_enabled
    s.sub_agent.enabled = sub_agent_enabled
    s.memory.enabled = memory_enabled
    return s


@contextlib.asynccontextmanager
async def _patch_heavy_deps():
    """Patch build_graph and MemoryStore to avoid real LLM/DB calls."""
    with (
        patch("smartclaw.agent.runtime.build_graph", return_value=MagicMock(name="graph")),
        patch("smartclaw.memory.store.MemoryStore") as ms_cls,
    ):
        ms_instance = AsyncMock()
        ms_instance.close = AsyncMock()
        ms_cls.return_value = ms_instance
        yield


# ---------------------------------------------------------------------------
# Property 1: AgentRuntime 结构完整性
# Feature: smartclaw-gateway-full-agent, Property 1: AgentRuntime structure completeness
# **Validates: Requirements 1.1**
# ---------------------------------------------------------------------------


class TestProperty1StructureCompleteness:
    """For any SmartClawSettings, setup_agent_runtime returns a structurally complete AgentRuntime."""

    @pytest.mark.asyncio
    @settings(max_examples=100, deadline=None)
    @given(
        mcp_enabled=st.just(False),  # MCP needs real servers, always disable
        skills_enabled=st.booleans(),
        sub_agent_enabled=st.booleans(),
        memory_enabled=st.booleans(),
    )
    async def test_structure_always_complete(
        self, mcp_enabled, skills_enabled, sub_agent_enabled, memory_enabled
    ):
        s = _make_settings(
            mcp_enabled=mcp_enabled,
            skills_enabled=skills_enabled,
            sub_agent_enabled=sub_agent_enabled,
            memory_enabled=memory_enabled,
        )

        async with _patch_heavy_deps():
            rt = await setup_agent_runtime(s)

        # Core fields always non-None
        assert rt.graph is not None
        assert rt.registry is not None
        assert isinstance(rt.registry, ToolRegistry)
        assert rt.system_prompt is not None
        assert isinstance(rt.system_prompt, str)
        assert len(rt.system_prompt) > 0
        assert rt.model_config is not None
        # At least 8 base system tools
        assert rt.registry.count >= 8


# ---------------------------------------------------------------------------
# Property 2: 功能开关一致性
# Feature: smartclaw-gateway-full-agent, Property 2: Feature switch consistency
# **Validates: Requirements 1.3, 1.4, 1.5**
# ---------------------------------------------------------------------------


class TestProperty2FeatureSwitchConsistency:
    """Feature enabled/disabled → component present/absent."""

    @pytest.mark.asyncio
    @settings(max_examples=100, deadline=None)
    @given(
        sub_agent_enabled=st.booleans(),
        memory_enabled=st.booleans(),
    )
    async def test_feature_switches(self, sub_agent_enabled, memory_enabled):
        s = _make_settings(
            sub_agent_enabled=sub_agent_enabled,
            memory_enabled=memory_enabled,
        )

        async with _patch_heavy_deps():
            rt = await setup_agent_runtime(s)

        # Sub-agent
        if sub_agent_enabled:
            assert "spawn_sub_agent" in rt.tool_names
        else:
            assert "spawn_sub_agent" not in rt.tool_names

        # Memory
        if memory_enabled:
            assert rt.memory_store is not None
            assert rt.summarizer is not None
        else:
            assert rt.memory_store is None
            assert rt.summarizer is None


# ---------------------------------------------------------------------------
# Property 7: close() 释放资源
# Feature: smartclaw-gateway-full-agent, Property 7: close() releases resources
# **Validates: Requirements 5.2**
# ---------------------------------------------------------------------------


class TestProperty7CloseReleasesResources:
    """close() calls close on all present resources."""

    @pytest.mark.asyncio
    @settings(max_examples=100, deadline=None)
    @given(
        has_memory=st.booleans(),
        has_mcp=st.booleans(),
    )
    async def test_close_releases(self, has_memory, has_mcp):
        mock_mem = AsyncMock() if has_memory else None
        mock_mcp = AsyncMock() if has_mcp else None

        if mock_mem is not None:
            mock_mem.close = AsyncMock()
        if mock_mcp is not None:
            mock_mcp.close = AsyncMock()

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

        if has_memory:
            mock_mem.close.assert_awaited_once()
        if has_mcp:
            mock_mcp.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# Property 8: close() 异常容错
# Feature: smartclaw-gateway-full-agent, Property 8: close() exception tolerance
# **Validates: Requirements 5.5**
# ---------------------------------------------------------------------------


class TestProperty8CloseExceptionTolerance:
    """close() never propagates exceptions and continues cleaning remaining resources."""

    @pytest.mark.asyncio
    @settings(max_examples=100, deadline=None)
    @given(
        mem_exc_type=st.sampled_from([Exception, RuntimeError, OSError]),
        mcp_exc_type=st.sampled_from([Exception, RuntimeError, OSError]),
    )
    async def test_close_tolerates_exceptions(self, mem_exc_type, mcp_exc_type):
        mock_mem = AsyncMock()
        mock_mem.close = AsyncMock(side_effect=mem_exc_type("mem close fail"))
        mock_mcp = AsyncMock()
        mock_mcp.close = AsyncMock(side_effect=mcp_exc_type("mcp close fail"))

        rt = AgentRuntime(
            graph=MagicMock(),
            registry=ToolRegistry(),
            memory_store=mock_mem,
            summarizer=None,
            system_prompt="test",
            mcp_manager=mock_mcp,
            model_config=ModelConfig(),
        )

        # Must not raise
        await rt.close()

        # Both close methods must have been called
        mock_mem.close.assert_awaited_once()
        mock_mcp.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# Property 9: 初始化确定性
# Feature: smartclaw-gateway-full-agent, Property 9: Initialization determinism
# **Validates: Requirements 6.1, 6.2**
# ---------------------------------------------------------------------------


class TestProperty9InitializationDeterminism:
    """Two calls with same settings produce same tool_names and system_prompt."""

    @pytest.mark.asyncio
    @settings(max_examples=100, deadline=None)
    @given(
        sub_agent_enabled=st.booleans(),
        memory_enabled=st.booleans(),
    )
    async def test_deterministic_init(self, sub_agent_enabled, memory_enabled):
        s1 = _make_settings(
            sub_agent_enabled=sub_agent_enabled,
            memory_enabled=memory_enabled,
        )
        s2 = _make_settings(
            sub_agent_enabled=sub_agent_enabled,
            memory_enabled=memory_enabled,
        )

        async with _patch_heavy_deps():
            rt1 = await setup_agent_runtime(s1)

        async with _patch_heavy_deps():
            rt2 = await setup_agent_runtime(s2)

        assert rt1.tool_names == rt2.tool_names
        assert rt1.system_prompt == rt2.system_prompt
