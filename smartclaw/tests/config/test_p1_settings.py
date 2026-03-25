"""Unit tests for P1 configuration settings.

Tests cover:
- All P1 config field defaults (MemorySettings, SkillsSettings, SubAgentSettings, MultiAgentSettings)
- Environment variable overrides (SMARTCLAW_MEMORY__*, SMARTCLAW_SKILLS__*, etc.)
- Disabled modules behavior

Requirements: 3.1, 3.2, 3.3, 8.1, 8.2, 8.3, 11.1, 11.2, 11.3, 13.1, 13.3, 13.4
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from smartclaw.config.settings import (
    AgentRoleConfig,
    MemorySettings,
    MultiAgentSettings,
    SkillsSettings,
    SmartClawSettings,
    SubAgentSettings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clear_smartclaw_env() -> dict[str, str]:
    """Remove all SMARTCLAW_ env vars, return saved values for restore."""
    saved: dict[str, str] = {}
    for k in list(os.environ):
        if k.startswith("SMARTCLAW_"):
            saved[k] = os.environ.pop(k)
    return saved


def _restore_env(saved: dict[str, str]) -> None:
    """Restore previously saved env vars."""
    # Clean any SMARTCLAW_ vars set during test
    for k in list(os.environ):
        if k.startswith("SMARTCLAW_"):
            del os.environ[k]
    for k, v in saved.items():
        os.environ[k] = v


# ---------------------------------------------------------------------------
# Test: MemorySettings defaults (Req 3.1)
# ---------------------------------------------------------------------------


class TestMemorySettingsDefaults:
    """Verify MemorySettings default values."""

    def test_enabled_default(self) -> None:
        s = MemorySettings()
        assert s.enabled is True

    def test_db_path_default(self) -> None:
        s = MemorySettings()
        assert s.db_path == "~/.smartclaw/memory.db"

    def test_summary_threshold_default(self) -> None:
        s = MemorySettings()
        assert s.summary_threshold == 20

    def test_keep_recent_default(self) -> None:
        s = MemorySettings()
        assert s.keep_recent == 5

    def test_summarize_token_percent_default(self) -> None:
        s = MemorySettings()
        assert s.summarize_token_percent == 70

    def test_context_window_default(self) -> None:
        s = MemorySettings()
        assert s.context_window == 128_000


# ---------------------------------------------------------------------------
# Test: SkillsSettings defaults (Req 8.1)
# ---------------------------------------------------------------------------


class TestSkillsSettingsDefaults:
    """Verify SkillsSettings default values."""

    def test_enabled_default(self) -> None:
        s = SkillsSettings()
        assert s.enabled is True

    def test_workspace_dir_default(self) -> None:
        s = SkillsSettings()
        assert s.workspace_dir == "{workspace}/skills"

    def test_global_dir_default(self) -> None:
        s = SkillsSettings()
        assert s.global_dir == "~/.smartclaw/skills"


# ---------------------------------------------------------------------------
# Test: SubAgentSettings defaults (Req 11.1)
# ---------------------------------------------------------------------------


class TestSubAgentSettingsDefaults:
    """Verify SubAgentSettings default values."""

    def test_enabled_default(self) -> None:
        s = SubAgentSettings()
        assert s.enabled is True

    def test_max_depth_default(self) -> None:
        s = SubAgentSettings()
        assert s.max_depth == 3

    def test_max_concurrent_default(self) -> None:
        s = SubAgentSettings()
        assert s.max_concurrent == 5

    def test_default_timeout_seconds_default(self) -> None:
        s = SubAgentSettings()
        assert s.default_timeout_seconds == 300

    def test_concurrency_timeout_seconds_default(self) -> None:
        s = SubAgentSettings()
        assert s.concurrency_timeout_seconds == 30


# ---------------------------------------------------------------------------
# Test: MultiAgentSettings defaults (Req 13.1)
# ---------------------------------------------------------------------------


class TestMultiAgentSettingsDefaults:
    """Verify MultiAgentSettings default values."""

    def test_enabled_default_false(self) -> None:
        s = MultiAgentSettings()
        assert s.enabled is False

    def test_max_total_iterations_default(self) -> None:
        s = MultiAgentSettings()
        assert s.max_total_iterations == 100

    def test_roles_default_empty(self) -> None:
        s = MultiAgentSettings()
        assert s.roles == []


# ---------------------------------------------------------------------------
# Test: AgentRoleConfig defaults
# ---------------------------------------------------------------------------


class TestAgentRoleConfigDefaults:
    """Verify AgentRoleConfig default values."""

    def test_name_default_empty(self) -> None:
        c = AgentRoleConfig()
        assert c.name == ""

    def test_tools_default_empty_list(self) -> None:
        c = AgentRoleConfig()
        assert c.tools == []

    def test_system_prompt_default_none(self) -> None:
        c = AgentRoleConfig()
        assert c.system_prompt is None


# ---------------------------------------------------------------------------
# Test: SmartClawSettings includes P1 fields with correct defaults
# ---------------------------------------------------------------------------


class TestSmartClawSettingsP1Fields:
    """Verify P1 fields are present on SmartClawSettings with correct defaults."""

    def setup_method(self) -> None:
        self._saved = _clear_smartclaw_env()

    def teardown_method(self) -> None:
        _restore_env(self._saved)

    def test_memory_field_present(self) -> None:
        s = SmartClawSettings()
        assert isinstance(s.memory, MemorySettings)
        assert s.memory.enabled is True

    def test_skills_field_present(self) -> None:
        s = SmartClawSettings()
        assert isinstance(s.skills, SkillsSettings)
        assert s.skills.enabled is True

    def test_sub_agent_field_present(self) -> None:
        s = SmartClawSettings()
        assert isinstance(s.sub_agent, SubAgentSettings)
        assert s.sub_agent.enabled is True

    def test_multi_agent_field_present(self) -> None:
        s = SmartClawSettings()
        assert isinstance(s.multi_agent, MultiAgentSettings)
        assert s.multi_agent.enabled is False


# ---------------------------------------------------------------------------
# Test: Environment variable overrides (Req 3.3, 8.3, 11.3, 13.4)
# ---------------------------------------------------------------------------


class TestP1EnvOverrides:
    """Verify environment variable overrides for P1 settings."""

    def setup_method(self) -> None:
        self._saved = _clear_smartclaw_env()

    def teardown_method(self) -> None:
        _restore_env(self._saved)

    def test_memory_db_path_override(self) -> None:
        os.environ["SMARTCLAW_MEMORY__DB_PATH"] = "/tmp/test.db"
        s = SmartClawSettings()
        assert s.memory.db_path == "/tmp/test.db"

    def test_memory_enabled_override(self) -> None:
        os.environ["SMARTCLAW_MEMORY__ENABLED"] = "false"
        s = SmartClawSettings()
        assert s.memory.enabled is False

    def test_memory_summary_threshold_override(self) -> None:
        os.environ["SMARTCLAW_MEMORY__SUMMARY_THRESHOLD"] = "50"
        s = SmartClawSettings()
        assert s.memory.summary_threshold == 50

    def test_skills_enabled_override(self) -> None:
        os.environ["SMARTCLAW_SKILLS__ENABLED"] = "false"
        s = SmartClawSettings()
        assert s.skills.enabled is False

    def test_skills_global_dir_override(self) -> None:
        os.environ["SMARTCLAW_SKILLS__GLOBAL_DIR"] = "/opt/skills"
        s = SmartClawSettings()
        assert s.skills.global_dir == "/opt/skills"

    def test_sub_agent_enabled_override(self) -> None:
        os.environ["SMARTCLAW_SUB_AGENT__ENABLED"] = "false"
        s = SmartClawSettings()
        assert s.sub_agent.enabled is False

    def test_sub_agent_max_depth_override(self) -> None:
        os.environ["SMARTCLAW_SUB_AGENT__MAX_DEPTH"] = "10"
        s = SmartClawSettings()
        assert s.sub_agent.max_depth == 10

    def test_multi_agent_enabled_override(self) -> None:
        os.environ["SMARTCLAW_MULTI_AGENT__ENABLED"] = "true"
        s = SmartClawSettings()
        assert s.multi_agent.enabled is True

    def test_multi_agent_max_total_iterations_override(self) -> None:
        os.environ["SMARTCLAW_MULTI_AGENT__MAX_TOTAL_ITERATIONS"] = "200"
        s = SmartClawSettings()
        assert s.multi_agent.max_total_iterations == 200


# ---------------------------------------------------------------------------
# Test: Disabled modules behavior (Req 3.2, 8.2, 11.2, 13.3)
# ---------------------------------------------------------------------------


class TestDisabledModules:
    """Verify disabled P1 modules can be configured."""

    def setup_method(self) -> None:
        self._saved = _clear_smartclaw_env()

    def teardown_method(self) -> None:
        _restore_env(self._saved)

    def test_all_p1_disabled(self) -> None:
        """All P1 modules can be disabled simultaneously."""
        os.environ["SMARTCLAW_MEMORY__ENABLED"] = "false"
        os.environ["SMARTCLAW_SKILLS__ENABLED"] = "false"
        os.environ["SMARTCLAW_SUB_AGENT__ENABLED"] = "false"
        os.environ["SMARTCLAW_MULTI_AGENT__ENABLED"] = "false"
        s = SmartClawSettings()
        assert s.memory.enabled is False
        assert s.skills.enabled is False
        assert s.sub_agent.enabled is False
        assert s.multi_agent.enabled is False

    def test_p0_fields_unchanged_when_p1_disabled(self) -> None:
        """P0 fields retain defaults when P1 modules are disabled."""
        os.environ["SMARTCLAW_MEMORY__ENABLED"] = "false"
        os.environ["SMARTCLAW_SKILLS__ENABLED"] = "false"
        os.environ["SMARTCLAW_SUB_AGENT__ENABLED"] = "false"
        s = SmartClawSettings()
        # P0 defaults should be intact
        assert s.agent_defaults.workspace == "~/.smartclaw/workspace"
        assert s.agent_defaults.max_tokens == 32768
        assert s.logging.level == "INFO"
        assert s.credentials.keyring_service == "smartclaw"
