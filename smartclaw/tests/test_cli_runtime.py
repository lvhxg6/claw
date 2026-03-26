"""Unit tests for CLI runtime integration — --no-* flags modify settings."""

from __future__ import annotations

import argparse
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from smartclaw.config.settings import SmartClawSettings


def _make_settings() -> SmartClawSettings:
    """Create default settings with all features enabled."""
    s = SmartClawSettings()
    s.memory.enabled = True
    s.skills.enabled = True
    s.sub_agent.enabled = True
    return s


def _make_args(**overrides) -> argparse.Namespace:
    """Create CLI args namespace with defaults."""
    defaults = {
        "session": None,
        "no_memory": False,
        "no_skills": False,
        "no_sub_agent": False,
        "browser": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestCliNoFlags:
    """Test that --no-* flags correctly disable settings before setup_agent_runtime."""

    @pytest.mark.asyncio
    async def test_no_memory_disables_memory(self):
        settings = _make_settings()
        args = _make_args(no_memory=True)
        captured_settings = {}

        async def fake_setup(s, **kwargs):
            captured_settings["memory_enabled"] = s.memory.enabled
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
            await _run_agent_loop(settings, args)

        assert captured_settings["memory_enabled"] is False

    @pytest.mark.asyncio
    async def test_no_skills_disables_skills(self):
        settings = _make_settings()
        args = _make_args(no_skills=True)
        captured_settings = {}

        async def fake_setup(s, **kwargs):
            captured_settings["skills_enabled"] = s.skills.enabled
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
            await _run_agent_loop(settings, args)

        assert captured_settings["skills_enabled"] is False

    @pytest.mark.asyncio
    async def test_no_sub_agent_disables_sub_agent(self):
        settings = _make_settings()
        args = _make_args(no_sub_agent=True)
        captured_settings = {}

        async def fake_setup(s, **kwargs):
            captured_settings["sub_agent_enabled"] = s.sub_agent.enabled
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
            await _run_agent_loop(settings, args)

        assert captured_settings["sub_agent_enabled"] is False

    @pytest.mark.asyncio
    async def test_no_flags_keeps_all_enabled(self):
        settings = _make_settings()
        args = _make_args()
        captured_settings = {}

        async def fake_setup(s, **kwargs):
            captured_settings["memory_enabled"] = s.memory.enabled
            captured_settings["skills_enabled"] = s.skills.enabled
            captured_settings["sub_agent_enabled"] = s.sub_agent.enabled
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
            await _run_agent_loop(settings, args)

        assert captured_settings["memory_enabled"] is True
        assert captured_settings["skills_enabled"] is True
        assert captured_settings["sub_agent_enabled"] is True

    @pytest.mark.asyncio
    async def test_cli_calls_runtime_close(self):
        settings = _make_settings()
        args = _make_args()

        mock_close = AsyncMock()

        async def fake_setup(s, **kwargs):
            rt = MagicMock()
            rt.graph = MagicMock()
            rt.memory_store = None
            rt.summarizer = None
            rt.system_prompt = "test"
            rt.tools = []
            rt.tool_names = []
            rt.close = mock_close
            return rt

        with patch("smartclaw.agent.runtime.setup_agent_runtime", side_effect=fake_setup), \
             patch("builtins.input", side_effect=EOFError):
            from smartclaw.cli import _run_agent_loop
            await _run_agent_loop(settings, args)

        mock_close.assert_awaited_once()
