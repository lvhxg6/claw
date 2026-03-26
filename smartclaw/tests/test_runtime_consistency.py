"""Consistency tests — two calls with same settings produce same tool_names and system_prompt.

Requirements: 6.1, 6.2
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from smartclaw.agent.runtime import setup_agent_runtime
from smartclaw.config.settings import SmartClawSettings


def _make_settings() -> SmartClawSettings:
    s = SmartClawSettings()
    s.mcp.enabled = False
    s.skills.enabled = False
    s.sub_agent.enabled = True
    s.memory.enabled = False
    return s


@pytest.mark.asyncio
async def test_two_calls_same_tool_names():
    """Two calls with same settings produce identical tool_names. (Req 6.1)"""
    with patch("smartclaw.agent.runtime.build_graph", return_value=MagicMock()):
        s1 = _make_settings()
        rt1 = await setup_agent_runtime(s1)

        s2 = _make_settings()
        rt2 = await setup_agent_runtime(s2)

    assert rt1.tool_names == rt2.tool_names


@pytest.mark.asyncio
async def test_two_calls_same_system_prompt():
    """Two calls with same settings produce identical system_prompt. (Req 6.2)"""
    with patch("smartclaw.agent.runtime.build_graph", return_value=MagicMock()):
        s1 = _make_settings()
        rt1 = await setup_agent_runtime(s1)

        s2 = _make_settings()
        rt2 = await setup_agent_runtime(s2)

    assert rt1.system_prompt == rt2.system_prompt


@pytest.mark.asyncio
async def test_consistency_with_memory_enabled():
    """Consistency holds even with memory enabled. (Req 6.1, 6.2)"""
    with patch("smartclaw.agent.runtime.build_graph", return_value=MagicMock()), \
         patch("smartclaw.memory.store.MemoryStore") as ms_cls:
        ms_instance = AsyncMock()
        ms_instance.close = AsyncMock()
        ms_cls.return_value = ms_instance

        s1 = _make_settings()
        s1.memory.enabled = True
        rt1 = await setup_agent_runtime(s1)

        s2 = _make_settings()
        s2.memory.enabled = True
        rt2 = await setup_agent_runtime(s2)

    assert rt1.tool_names == rt2.tool_names
    assert rt1.system_prompt == rt2.system_prompt
