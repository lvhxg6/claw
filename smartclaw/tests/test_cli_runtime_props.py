"""Property-based tests for CLI runtime integration.

# Feature: smartclaw-gateway-full-agent, Property 3: CLI parameter override
# **Validates: Requirements 3.2**
"""

from __future__ import annotations

import argparse
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from smartclaw.config.settings import SmartClawSettings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings() -> SmartClawSettings:
    s = SmartClawSettings()
    s.memory.enabled = True
    s.skills.enabled = True
    s.sub_agent.enabled = True
    return s


def _make_args(no_memory: bool, no_skills: bool, no_sub_agent: bool) -> argparse.Namespace:
    return argparse.Namespace(
        session=None,
        no_memory=no_memory,
        no_skills=no_skills,
        no_sub_agent=no_sub_agent,
        browser=False,
    )


# ---------------------------------------------------------------------------
# Property 3: CLI 命令行参数覆盖
# Feature: smartclaw-gateway-full-agent, Property 3: CLI parameter override
# **Validates: Requirements 3.2**
# ---------------------------------------------------------------------------


class TestProperty3CliParameterOverride:
    """--no-* flags disable corresponding settings before setup_agent_runtime."""

    @pytest.mark.asyncio
    @settings(max_examples=100, deadline=None)
    @given(
        no_memory=st.booleans(),
        no_skills=st.booleans(),
        no_sub_agent=st.booleans(),
    )
    async def test_cli_flags_override_settings(
        self, no_memory: bool, no_skills: bool, no_sub_agent: bool
    ):
        settings_obj = _make_settings()
        args = _make_args(no_memory=no_memory, no_skills=no_skills, no_sub_agent=no_sub_agent)
        captured = {}

        async def fake_setup(s, **kwargs):
            captured["memory_enabled"] = s.memory.enabled
            captured["skills_enabled"] = s.skills.enabled
            captured["sub_agent_enabled"] = s.sub_agent.enabled
            rt = MagicMock()
            rt.graph = MagicMock()
            rt.memory_store = None
            rt.summarizer = None
            rt.system_prompt = "test"
            rt.tools = []
            rt.tool_names = []
            rt.close = AsyncMock()
            return rt

        with patch("smartclaw.agent.runtime.setup_agent_runtime", side_effect=fake_setup), \
             patch("builtins.input", side_effect=EOFError):
            from smartclaw.cli import _run_agent_loop
            await _run_agent_loop(settings_obj, args)

        # When --no-X is True, the corresponding enabled must be False
        if no_memory:
            assert captured["memory_enabled"] is False
        else:
            assert captured["memory_enabled"] is True

        if no_skills:
            assert captured["skills_enabled"] is False
        else:
            assert captured["skills_enabled"] is True

        if no_sub_agent:
            assert captured["sub_agent_enabled"] is False
        else:
            assert captured["sub_agent_enabled"] is True
