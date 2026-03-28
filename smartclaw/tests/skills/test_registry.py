"""Unit tests for SkillsRegistry."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import yaml
from langchain_core.tools import BaseTool

from smartclaw.skills.loader import SkillsLoader
from smartclaw.skills.models import SkillDefinition, SkillInfo
from smartclaw.skills.registry import SkillsRegistry
from smartclaw.tools.registry import ToolRegistry


def _make_mock_tool(name: str) -> BaseTool:
    """Create a minimal mock BaseTool."""
    tool = MagicMock(spec=BaseTool)
    tool.name = name
    return tool


class TestRegistrationFailureContinues:
    """Tests that registration failure continues with remaining skills. (Req 7.9)"""

    def test_load_and_register_all_continues_on_failure(self) -> None:
        """When one skill fails to load, remaining skills are still registered."""
        loader = MagicMock(spec=SkillsLoader)
        tool_registry = ToolRegistry()
        registry = SkillsRegistry(loader, tool_registry)

        # Two skills: first will fail, second will succeed
        loader.list_skills.return_value = [
            SkillInfo(name="bad-skill", path="/fake/bad", source="workspace", description="Bad"),
            SkillInfo(name="good-skill", path="/fake/good", source="workspace", description="Good"),
        ]

        good_module = object()

        def side_effect(name: str) -> Any:
            if name == "bad-skill":
                raise ImportError("Cannot import bad-skill")
            # Return a callable entry_fn and a definition
            return (lambda: good_module, SkillDefinition(
                name="good-skill",
                description="Good",
                entry_point="pkg:func",
            ))

        loader.load_skill.side_effect = side_effect

        registry.load_and_register_all()

        # bad-skill should not be registered
        assert registry.get("bad-skill") is None
        # good-skill should be registered
        assert registry.get("good-skill") is good_module

    def test_entry_point_exception_continues(self) -> None:
        """When entry_point callable raises, remaining skills are registered."""
        loader = MagicMock(spec=SkillsLoader)
        tool_registry = ToolRegistry()
        registry = SkillsRegistry(loader, tool_registry)

        loader.list_skills.return_value = [
            SkillInfo(name="crash-skill", path="/fake/crash", source="workspace", description="Crash"),
            SkillInfo(name="ok-skill", path="/fake/ok", source="workspace", description="OK"),
        ]

        ok_module = object()

        def crash_entry() -> None:
            raise RuntimeError("entry point crashed")

        def side_effect(name: str) -> Any:
            if name == "crash-skill":
                return (crash_entry, SkillDefinition(
                    name="crash-skill", description="Crash", entry_point="pkg:crash",
                ))
            return (lambda: ok_module, SkillDefinition(
                name="ok-skill", description="OK", entry_point="pkg:ok",
            ))

        loader.load_skill.side_effect = side_effect

        registry.load_and_register_all()

        assert registry.get("crash-skill") is None
        assert registry.get("ok-skill") is ok_module

    def test_load_and_register_names_only_loads_requested_skills(self) -> None:
        """Named loading should not eagerly activate unrelated skills."""
        loader = MagicMock(spec=SkillsLoader)
        tool_registry = ToolRegistry()
        registry = SkillsRegistry(loader, tool_registry)

        loader.list_skills.return_value = [
            SkillInfo(name="inspect-skill", path="/fake/inspect", source="workspace", description="Inspect"),
            SkillInfo(name="report-skill", path="/fake/report", source="workspace", description="Report"),
        ]

        inspect_module = object()
        report_module = object()

        def side_effect(name: str) -> Any:
            if name == "inspect-skill":
                return (lambda: inspect_module, SkillDefinition(
                    name="inspect-skill",
                    description="Inspect",
                    entry_point="pkg:inspect",
                ))
            return (lambda: report_module, SkillDefinition(
                name="report-skill",
                description="Report",
                entry_point="pkg:report",
            ))

        loader.load_skill.side_effect = side_effect

        registry.load_and_register_names(["inspect-skill"])

        assert registry.get("inspect-skill") is inspect_module
        assert registry.get("report-skill") is None


class TestDuplicateRegistration:
    """Tests that duplicate registration overwrites the old skill."""

    def test_duplicate_registration_overwrites(self) -> None:
        """Registering a skill with the same name replaces the old one."""
        loader = MagicMock(spec=SkillsLoader)
        tool_registry = ToolRegistry()
        registry = SkillsRegistry(loader, tool_registry)

        module_v1 = object()
        module_v2 = object()

        registry.register("my-skill", module_v1)
        assert registry.get("my-skill") is module_v1

        registry.register("my-skill", module_v2)
        assert registry.get("my-skill") is module_v2

    def test_duplicate_registration_replaces_tools(self) -> None:
        """Overwriting a skill replaces old tools with new ones."""
        loader = MagicMock(spec=SkillsLoader)
        tool_registry = ToolRegistry()
        registry = SkillsRegistry(loader, tool_registry)

        old_tool = _make_mock_tool("old-tool")
        new_tool = _make_mock_tool("new-tool")

        registry.register("my-skill", [old_tool])
        assert tool_registry.get("old-tool") is not None

        registry.register("my-skill", [new_tool])
        # Old tool should be removed
        assert tool_registry.get("old-tool") is None
        # New tool should be present
        assert tool_registry.get("new-tool") is not None


class TestLoadAndRegisterAll:
    """Tests for load_and_register_all integration flow. (Req 7.7)"""

    def test_load_and_register_all_registers_skills_with_tools(self) -> None:
        """load_and_register_all discovers, loads, and registers skills and their tools."""
        loader = MagicMock(spec=SkillsLoader)
        tool_registry = ToolRegistry()
        registry = SkillsRegistry(loader, tool_registry)

        tool_a = _make_mock_tool("tool-a")
        tool_b = _make_mock_tool("tool-b")

        loader.list_skills.return_value = [
            SkillInfo(name="skill-a", path="/fake/a", source="workspace", description="A"),
            SkillInfo(name="skill-b", path="/fake/b", source="global", description="B"),
        ]

        def side_effect(name: str) -> Any:
            if name == "skill-a":
                return (lambda: [tool_a], SkillDefinition(
                    name="skill-a", description="A", entry_point="pkg:a",
                ))
            return (lambda: [tool_b], SkillDefinition(
                name="skill-b", description="B", entry_point="pkg:b",
            ))

        loader.load_skill.side_effect = side_effect

        registry.load_and_register_all()

        # Both skills registered
        assert registry.get("skill-a") is not None
        assert registry.get("skill-b") is not None
        assert sorted(registry.list_skills()) == ["skill-a", "skill-b"]

        # Tools registered in ToolRegistry
        assert tool_registry.get("tool-a") is tool_a
        assert tool_registry.get("tool-b") is tool_b

    def test_load_and_register_all_empty(self) -> None:
        """load_and_register_all with no skills does nothing."""
        loader = MagicMock(spec=SkillsLoader)
        tool_registry = ToolRegistry()
        registry = SkillsRegistry(loader, tool_registry)

        loader.list_skills.return_value = []

        registry.load_and_register_all()

        assert registry.list_skills() == []

    def test_load_and_register_all_skill_without_tools(self) -> None:
        """Skills that don't provide tools are still registered."""
        loader = MagicMock(spec=SkillsLoader)
        tool_registry = ToolRegistry()
        registry = SkillsRegistry(loader, tool_registry)

        plain_module = {"config": "value"}

        loader.list_skills.return_value = [
            SkillInfo(name="no-tools", path="/fake/nt", source="workspace", description="No tools"),
        ]
        loader.load_skill.return_value = (
            lambda: plain_module,
            SkillDefinition(name="no-tools", description="No tools", entry_point="pkg:nt"),
        )

        registry.load_and_register_all()

        assert registry.get("no-tools") is plain_module
        assert registry.list_skills() == ["no-tools"]
