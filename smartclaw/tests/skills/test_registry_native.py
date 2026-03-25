"""Unit tests for SkillsRegistry native command tool integration."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import yaml
from langchain_core.tools import BaseTool

from smartclaw.skills.loader import SkillsLoader
from smartclaw.skills.models import (
    ParameterDef,
    SkillDefinition,
    SkillInfo,
    ToolDef,
)
from smartclaw.skills.registry import SkillsRegistry
from smartclaw.tools.registry import ToolRegistry


def _make_mock_tool(name: str) -> BaseTool:
    """Create a minimal mock BaseTool."""
    tool = MagicMock(spec=BaseTool)
    tool.name = name
    return tool


class TestNativeCommandToolRegistration:
    """Tests for native command tool registration via load_and_register_all."""

    def test_shell_tool_registered(self, tmp_path: Path) -> None:
        """Shell type native command tool is registered in ToolRegistry. (Req 8.1)"""
        skill_dir = tmp_path / "workspace" / "devops"
        skill_dir.mkdir(parents=True)
        yaml_data = {
            "name": "devops",
            "description": "DevOps tools",
            "tools": [
                {
                    "name": "disk-usage",
                    "description": "Check disk usage",
                    "type": "shell",
                    "command": "du -sh /tmp",
                },
            ],
        }
        (skill_dir / "skill.yaml").write_text(
            yaml.dump(yaml_data), encoding="utf-8"
        )

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
            builtin_dir=None,
        )
        tool_registry = ToolRegistry()
        registry = SkillsRegistry(loader, tool_registry)
        registry.load_and_register_all()

        # Native tool should be registered
        tool = tool_registry.get("disk-usage")
        assert tool is not None
        assert tool.name == "disk-usage"

    def test_exec_tool_registered(self, tmp_path: Path) -> None:
        """Exec type native command tool is registered. (Req 8.1)"""
        skill_dir = tmp_path / "workspace" / "lint-tools"
        skill_dir.mkdir(parents=True)
        yaml_data = {
            "name": "lint-tools",
            "description": "Linting tools",
            "tools": [
                {
                    "name": "lint-go",
                    "description": "Run golangci-lint",
                    "type": "exec",
                    "command": "golangci-lint",
                    "args": ["run"],
                },
            ],
        }
        (skill_dir / "skill.yaml").write_text(
            yaml.dump(yaml_data), encoding="utf-8"
        )

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
            builtin_dir=None,
        )
        tool_registry = ToolRegistry()
        registry = SkillsRegistry(loader, tool_registry)
        registry.load_and_register_all()

        tool = tool_registry.get("lint-go")
        assert tool is not None
        assert tool.name == "lint-go"

    def test_script_tool_registered(self, tmp_path: Path) -> None:
        """Script type native command tool is registered. (Req 8.1)"""
        skill_dir = tmp_path / "workspace" / "deploy"
        skill_dir.mkdir(parents=True)
        yaml_data = {
            "name": "deploy",
            "description": "Deploy tools",
            "tools": [
                {
                    "name": "deploy-check",
                    "description": "Run deploy check",
                    "type": "script",
                    "command": "./check.sh",
                },
            ],
        }
        (skill_dir / "skill.yaml").write_text(
            yaml.dump(yaml_data), encoding="utf-8"
        )

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
            builtin_dir=None,
        )
        tool_registry = ToolRegistry()
        registry = SkillsRegistry(loader, tool_registry)
        registry.load_and_register_all()

        tool = tool_registry.get("deploy-check")
        assert tool is not None


class TestMixedSkillRegistration:
    """Tests for skills with both entry_point and native command tools."""

    def test_mixed_skill_registers_both(self) -> None:
        """Mixed skill registers both Python and native tools. (Req 8.3)"""
        loader = MagicMock(spec=SkillsLoader)
        tool_registry = ToolRegistry()
        registry = SkillsRegistry(loader, tool_registry)

        py_tool = _make_mock_tool("py-tool")

        # Create a definition with both entry_point and native tools
        defn = SkillDefinition(
            name="mixed-skill",
            description="Mixed skill",
            entry_point="pkg:func",
            tools=[
                ToolDef(
                    name="native-cmd",
                    description="A native command",
                    type="shell",
                    command="echo hello",
                ),
            ],
        )

        loader.list_skills.return_value = [
            SkillInfo(name="mixed-skill", path="/fake", source="workspace", description="Mixed"),
        ]
        # load_skill returns (callable, definition) for entry_point skills
        loader.load_skill.return_value = (lambda: [py_tool], defn)

        registry.load_and_register_all()

        # Both tools should be registered
        assert tool_registry.get("py-tool") is not None
        assert tool_registry.get("native-cmd") is not None


class TestPureYamlSkillRegistration:
    """Tests for pure YAML skills (no entry_point, only native tools)."""

    def test_pure_yaml_skill_registered(self, tmp_path: Path) -> None:
        """Pure YAML skill with only native tools registers successfully. (Req 8.5)"""
        skill_dir = tmp_path / "workspace" / "pure-native"
        skill_dir.mkdir(parents=True)
        yaml_data = {
            "name": "pure-native",
            "description": "Pure native tools",
            "tools": [
                {
                    "name": "tool-a",
                    "description": "Tool A",
                    "type": "shell",
                    "command": "echo a",
                },
                {
                    "name": "tool-b",
                    "description": "Tool B",
                    "type": "exec",
                    "command": "ls",
                    "args": ["-la"],
                },
            ],
        }
        (skill_dir / "skill.yaml").write_text(
            yaml.dump(yaml_data), encoding="utf-8"
        )

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
            builtin_dir=None,
        )
        tool_registry = ToolRegistry()
        registry = SkillsRegistry(loader, tool_registry)
        registry.load_and_register_all()

        assert tool_registry.get("tool-a") is not None
        assert tool_registry.get("tool-b") is not None
        assert registry.get("pure-native") is not None


class TestFailureContinuation:
    """Tests that individual tool registration failures don't block others."""

    def test_invalid_tool_def_skipped(self, tmp_path: Path) -> None:
        """Invalid ToolDef (no command) is skipped, valid tools still register. (Req 8.4)"""
        skill_dir = tmp_path / "workspace" / "mixed-valid"
        skill_dir.mkdir(parents=True)
        yaml_data = {
            "name": "mixed-valid",
            "description": "Mixed validity tools",
            "tools": [
                {
                    "name": "bad-tool",
                    "description": "Missing command",
                    "type": "shell",
                    # No command field — validation should fail
                },
                {
                    "name": "good-tool",
                    "description": "Good tool",
                    "type": "shell",
                    "command": "echo good",
                },
            ],
        }
        (skill_dir / "skill.yaml").write_text(
            yaml.dump(yaml_data), encoding="utf-8"
        )

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
            builtin_dir=None,
        )
        tool_registry = ToolRegistry()
        registry = SkillsRegistry(loader, tool_registry)
        registry.load_and_register_all()

        # Bad tool should not be registered
        assert tool_registry.get("bad-tool") is None
        # Good tool should still be registered
        assert tool_registry.get("good-tool") is not None

    def test_skill_failure_continues_to_next(self, tmp_path: Path) -> None:
        """One skill failing doesn't prevent other skills from loading."""
        workspace = tmp_path / "workspace"

        # Bad skill — invalid YAML
        bad_dir = workspace / "bad-skill"
        bad_dir.mkdir(parents=True)
        (bad_dir / "skill.yaml").write_text("{{invalid yaml", encoding="utf-8")

        # Good skill
        good_dir = workspace / "good-skill"
        good_dir.mkdir(parents=True)
        yaml_data = {
            "name": "good-skill",
            "description": "Good skill",
            "tools": [
                {
                    "name": "good-cmd",
                    "description": "Good command",
                    "type": "shell",
                    "command": "echo good",
                },
            ],
        }
        (good_dir / "skill.yaml").write_text(
            yaml.dump(yaml_data), encoding="utf-8"
        )

        loader = SkillsLoader(
            workspace_dir=str(workspace),
            global_dir=str(tmp_path / "empty"),
            builtin_dir=None,
        )
        tool_registry = ToolRegistry()
        registry = SkillsRegistry(loader, tool_registry)
        registry.load_and_register_all()

        # Good skill should be registered despite bad skill
        assert tool_registry.get("good-cmd") is not None


class TestBackwardCompatibility:
    """Tests that existing Python entry_point skills work unchanged."""

    def test_python_entry_point_unchanged(self) -> None:
        """Traditional Python entry_point skill registration is unchanged. (Req 10.1, 10.4)"""
        loader = MagicMock(spec=SkillsLoader)
        tool_registry = ToolRegistry()
        registry = SkillsRegistry(loader, tool_registry)

        py_tool = _make_mock_tool("py-tool")
        module_result = [py_tool]

        defn = SkillDefinition(
            name="python-skill",
            description="Python skill",
            entry_point="pkg.mod:create_tools",
            tools=[
                ToolDef(
                    name="py-tool",
                    description="A Python tool",
                    function="pkg.mod:tool_func",
                ),
            ],
        )

        loader.list_skills.return_value = [
            SkillInfo(
                name="python-skill",
                path="/fake/python-skill/skill.yaml",
                source="workspace",
                description="Python skill",
            ),
        ]
        loader.load_skill.return_value = (lambda: module_result, defn)

        registry.load_and_register_all()

        # Python tool should be registered via entry_point mechanism
        assert tool_registry.get("py-tool") is not None
        assert registry.get("python-skill") is not None

    def test_traditional_skill_no_native_tools(self) -> None:
        """Traditional skill with no native tools works as before. (Req 10.2)"""
        loader = MagicMock(spec=SkillsLoader)
        tool_registry = ToolRegistry()
        registry = SkillsRegistry(loader, tool_registry)

        plain_module = {"config": "value"}

        defn = SkillDefinition(
            name="plain-skill",
            description="Plain skill",
            entry_point="pkg:func",
        )

        loader.list_skills.return_value = [
            SkillInfo(
                name="plain-skill",
                path="/fake/plain-skill/skill.yaml",
                source="workspace",
                description="Plain skill",
            ),
        ]
        loader.load_skill.return_value = (lambda: plain_module, defn)

        registry.load_and_register_all()

        assert registry.get("plain-skill") is plain_module
