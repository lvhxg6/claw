"""Backward compatibility integration tests for P1 modules.

Verifies that:
- All P1 switches off = P0 behavior (Req 14.1)
- AgentState new fields default None (Req 14.3)
- P1 modules importable independently (Req 14.4)
- SmartClawSettings P0 fields unchanged (Req 14.2)

Requirements: 14.1, 14.2, 14.3, 14.4
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from smartclaw.agent.state import AgentState
from smartclaw.config.settings import SmartClawSettings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clear_smartclaw_env() -> dict[str, str]:
    saved: dict[str, str] = {}
    for k in list(os.environ):
        if k.startswith("SMARTCLAW_"):
            saved[k] = os.environ.pop(k)
    return saved


def _restore_env(saved: dict[str, str]) -> None:
    for k in list(os.environ):
        if k.startswith("SMARTCLAW_"):
            del os.environ[k]
    for k, v in saved.items():
        os.environ[k] = v


# ---------------------------------------------------------------------------
# Test: All P1 switches off = P0 behavior (Req 14.1)
# ---------------------------------------------------------------------------


class TestAllP1DisabledIsP0:
    """When all P1 modules are disabled, system behaves like P0."""

    def setup_method(self) -> None:
        self._saved = _clear_smartclaw_env()

    def teardown_method(self) -> None:
        _restore_env(self._saved)

    def test_settings_all_p1_disabled(self) -> None:
        """SmartClawSettings with all P1 disabled still has valid P0 defaults."""
        os.environ["SMARTCLAW_MEMORY__ENABLED"] = "false"
        os.environ["SMARTCLAW_SKILLS__ENABLED"] = "false"
        os.environ["SMARTCLAW_SUB_AGENT__ENABLED"] = "false"
        os.environ["SMARTCLAW_MULTI_AGENT__ENABLED"] = "false"

        s = SmartClawSettings()
        assert s.memory.enabled is False
        assert s.skills.enabled is False
        assert s.sub_agent.enabled is False
        assert s.multi_agent.enabled is False

        # P0 defaults intact
        assert s.agent_defaults.max_tokens == 32768
        assert s.agent_defaults.max_tool_iterations == 50
        assert s.logging.level == "INFO"

    async def test_invoke_without_session_key_is_stateless(self) -> None:
        """invoke() without session_key operates statelessly (P0 behavior)."""
        from smartclaw.agent.graph import invoke

        # Build a minimal mock graph
        mock_result: AgentState = {
            "messages": [HumanMessage(content="hi"), AIMessage(content="hello")],
            "iteration": 1,
            "max_iterations": 50,
            "final_answer": "hello",
            "error": None,
            "session_key": None,
            "summary": None,
            "sub_agent_depth": None,
        }
        mock_graph = MagicMock()
        mock_graph.ainvoke = AsyncMock(return_value=mock_result)

        result = await invoke(mock_graph, "hi")
        assert result["final_answer"] == "hello"
        # No memory_store interaction since session_key is None
        mock_graph.ainvoke.assert_called_once()


# ---------------------------------------------------------------------------
# Test: AgentState new fields default None (Req 14.3)
# ---------------------------------------------------------------------------


class TestAgentStateP1Fields:
    """P1 optional fields on AgentState default to None."""

    def test_session_key_in_annotations(self) -> None:
        assert "session_key" in AgentState.__annotations__

    def test_summary_in_annotations(self) -> None:
        assert "summary" in AgentState.__annotations__

    def test_sub_agent_depth_in_annotations(self) -> None:
        assert "sub_agent_depth" in AgentState.__annotations__

    def test_p1_fields_accept_none(self) -> None:
        """AgentState can be constructed with P1 fields as None."""
        state: AgentState = {
            "messages": [],
            "iteration": 0,
            "max_iterations": 50,
            "final_answer": None,
            "error": None,
            "session_key": None,
            "summary": None,
            "sub_agent_depth": None,
        }
        assert state["session_key"] is None
        assert state["summary"] is None
        assert state["sub_agent_depth"] is None

    def test_p0_fields_still_present(self) -> None:
        """P0 fields (messages, iteration, etc.) are still in AgentState."""
        annotations = AgentState.__annotations__
        assert "messages" in annotations
        assert "iteration" in annotations
        assert "max_iterations" in annotations
        assert "final_answer" in annotations
        assert "error" in annotations


# ---------------------------------------------------------------------------
# Test: P1 modules importable independently (Req 14.4)
# ---------------------------------------------------------------------------


class TestP1ModulesImportable:
    """All P1 modules can be imported independently without errors."""

    def test_import_memory_store(self) -> None:
        from smartclaw.memory.store import MemoryStore
        assert MemoryStore is not None

    def test_import_auto_summarizer(self) -> None:
        from smartclaw.memory.summarizer import AutoSummarizer
        assert AutoSummarizer is not None

    def test_import_skills_loader(self) -> None:
        from smartclaw.skills.loader import SkillsLoader
        assert SkillsLoader is not None

    def test_import_skills_registry(self) -> None:
        from smartclaw.skills.registry import SkillsRegistry
        assert SkillsRegistry is not None

    def test_import_sub_agent(self) -> None:
        from smartclaw.agent.sub_agent import (
            EphemeralStore,
            SpawnSubAgentTool,
            SubAgentConfig,
            spawn_sub_agent,
        )
        assert SubAgentConfig is not None
        assert EphemeralStore is not None
        assert spawn_sub_agent is not None
        assert SpawnSubAgentTool is not None

    def test_import_multi_agent(self) -> None:
        from smartclaw.agent.multi_agent import (
            AgentRole,
            MultiAgentCoordinator,
            MultiAgentState,
        )
        assert AgentRole is not None
        assert MultiAgentCoordinator is not None
        assert MultiAgentState is not None

    def test_import_p1_settings(self) -> None:
        from smartclaw.config.settings import (
            AgentRoleConfig,
            MemorySettings,
            MultiAgentSettings,
            SkillsSettings,
            SubAgentSettings,
        )
        assert MemorySettings is not None
        assert SkillsSettings is not None
        assert SubAgentSettings is not None
        assert MultiAgentSettings is not None
        assert AgentRoleConfig is not None

    def test_import_memory_init(self) -> None:
        from smartclaw.memory import AutoSummarizer, MemoryStore
        assert MemoryStore is not None
        assert AutoSummarizer is not None

    def test_import_skills_init(self) -> None:
        from smartclaw.skills import (
            SkillDefinition,
            SkillInfo,
            SkillsLoader,
            SkillsRegistry,
        )
        assert SkillsLoader is not None
        assert SkillsRegistry is not None
        assert SkillDefinition is not None
        assert SkillInfo is not None


# ---------------------------------------------------------------------------
# Test: SmartClawSettings P0 fields unchanged (Req 14.2)
# ---------------------------------------------------------------------------


class TestSmartClawSettingsP0Unchanged:
    """P0 fields on SmartClawSettings are not modified by P1 additions."""

    def setup_method(self) -> None:
        self._saved = _clear_smartclaw_env()

    def teardown_method(self) -> None:
        _restore_env(self._saved)

    def test_p0_field_names_present(self) -> None:
        """All P0 field names are still present on SmartClawSettings."""
        s = SmartClawSettings()
        assert hasattr(s, "agent_defaults")
        assert hasattr(s, "logging")
        assert hasattr(s, "credentials")
        assert hasattr(s, "model")
        assert hasattr(s, "browser")
        assert hasattr(s, "mcp")

    def test_p0_agent_defaults_type(self) -> None:
        from smartclaw.config.settings import AgentDefaultsSettings
        s = SmartClawSettings()
        assert isinstance(s.agent_defaults, AgentDefaultsSettings)

    def test_p0_logging_type(self) -> None:
        from smartclaw.config.settings import LoggingSettings
        s = SmartClawSettings()
        assert isinstance(s.logging, LoggingSettings)

    def test_p0_credentials_type(self) -> None:
        from smartclaw.config.settings import CredentialSettings
        s = SmartClawSettings()
        assert isinstance(s.credentials, CredentialSettings)

    def test_p0_defaults_values_unchanged(self) -> None:
        """P0 default values are exactly the same as before P1."""
        s = SmartClawSettings()
        assert s.agent_defaults.workspace == "~/.smartclaw/workspace"
        assert s.agent_defaults.max_tokens == 32768
        assert s.agent_defaults.max_tool_iterations == 50
        assert s.logging.level == "INFO"
        assert s.logging.format == "console"
        assert s.logging.file is None
        assert s.credentials.keyring_service == "smartclaw"
        assert s.mcp.enabled is False
