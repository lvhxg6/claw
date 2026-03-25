"""Unit tests for skill directory convention support:
- discover_scripts() in SkillsLoader
- {skill_dir} placeholder in NativeCommandTool
- {skill_dir} replacement in load_skills_for_context SKILL.md content
- Auto-discovered scripts registered via load_and_register_all
- Integration: scripts/ + SKILL.md + skill.yaml together
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from smartclaw.skills.loader import SkillsLoader
from smartclaw.skills.models import ParameterDef, ToolDef
from smartclaw.skills.native_command import (
    NativeCommandTool,
    _build_args_schema,
    substitute_placeholders,
)
from smartclaw.skills.registry import SkillsRegistry
from smartclaw.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# discover_scripts tests
# ---------------------------------------------------------------------------


class TestDiscoverScripts:
    """Tests for SkillsLoader.discover_scripts()."""

    def test_discovers_sh_and_py_files(self, tmp_path: Path) -> None:
        """discover_scripts finds .sh and .py files in scripts/ subdirectory."""
        skill_dir = tmp_path / "workspace" / "my-skill"
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir(parents=True)
        (skill_dir / "skill.yaml").write_text(
            yaml.dump({"name": "my-skill", "description": "A skill", "tools": [
                {"name": "t", "description": "t", "type": "shell", "command": "echo"},
            ]}),
            encoding="utf-8",
        )
        (scripts_dir / "deploy.sh").write_text("#!/bin/bash\necho deploy", encoding="utf-8")
        (scripts_dir / "analyze.py").write_text("print('analyze')", encoding="utf-8")

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
        )
        tools = loader.discover_scripts("my-skill")

        assert len(tools) == 2
        names = {t.name for t in tools}
        assert "deploy" in names
        assert "analyze" in names
        for t in tools:
            assert t.type == "script"
            assert t.working_dir == str(skill_dir.resolve())

    def test_returns_empty_when_no_scripts_dir(self, tmp_path: Path) -> None:
        """discover_scripts returns empty list when no scripts/ directory."""
        skill_dir = tmp_path / "workspace" / "no-scripts"
        skill_dir.mkdir(parents=True)
        (skill_dir / "skill.yaml").write_text(
            yaml.dump({"name": "no-scripts", "description": "No scripts", "tools": [
                {"name": "t", "description": "t", "type": "shell", "command": "echo"},
            ]}),
            encoding="utf-8",
        )

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
        )
        tools = loader.discover_scripts("no-scripts")
        assert tools == []

    def test_skips_non_executable_files_without_known_extensions(self, tmp_path: Path) -> None:
        """discover_scripts skips files without known extensions that aren't executable."""
        skill_dir = tmp_path / "workspace" / "ext-skill"
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir(parents=True)
        (skill_dir / "skill.yaml").write_text(
            yaml.dump({"name": "ext-skill", "description": "Ext skill", "tools": [
                {"name": "t", "description": "t", "type": "shell", "command": "echo"},
            ]}),
            encoding="utf-8",
        )

        # Known extension — should be included
        (scripts_dir / "good.sh").write_text("#!/bin/bash", encoding="utf-8")
        # Unknown extension — should be skipped
        (scripts_dir / "data.csv").write_text("a,b,c", encoding="utf-8")
        # No extension, not executable — should be skipped
        readme = scripts_dir / "README"
        readme.write_text("readme", encoding="utf-8")
        readme.chmod(stat.S_IRUSR | stat.S_IWUSR)  # rw only, no execute

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
        )
        tools = loader.discover_scripts("ext-skill")
        assert len(tools) == 1
        assert tools[0].name == "good"

    def test_includes_executable_files_without_extension(self, tmp_path: Path) -> None:
        """discover_scripts includes files without extension if executable."""
        skill_dir = tmp_path / "workspace" / "exec-skill"
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir(parents=True)
        (skill_dir / "skill.yaml").write_text(
            yaml.dump({"name": "exec-skill", "description": "Exec skill", "tools": [
                {"name": "t", "description": "t", "type": "shell", "command": "echo"},
            ]}),
            encoding="utf-8",
        )

        # Executable file without extension
        runner = scripts_dir / "runner"
        runner.write_text("#!/bin/bash\necho run", encoding="utf-8")
        runner.chmod(stat.S_IRWXU)

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
        )
        tools = loader.discover_scripts("exec-skill")
        assert len(tools) == 1
        assert tools[0].name == "runner"

    def test_discovers_all_supported_extensions(self, tmp_path: Path) -> None:
        """discover_scripts finds files with all supported extensions."""
        skill_dir = tmp_path / "workspace" / "multi-ext"
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir(parents=True)
        (skill_dir / "skill.yaml").write_text(
            yaml.dump({"name": "multi-ext", "description": "Multi ext", "tools": [
                {"name": "t", "description": "t", "type": "shell", "command": "echo"},
            ]}),
            encoding="utf-8",
        )

        for ext in [".sh", ".py", ".js", ".mjs", ".ts", ".rb", ".pl", ".go"]:
            (scripts_dir / f"script{ext}").write_text(f"# {ext}", encoding="utf-8")

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
        )
        tools = loader.discover_scripts("multi-ext")
        assert len(tools) == 8

    def test_returns_empty_for_nonexistent_skill(self, tmp_path: Path) -> None:
        """discover_scripts returns empty list for a skill that doesn't exist."""
        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
        )
        tools = loader.discover_scripts("nonexistent")
        assert tools == []


# ---------------------------------------------------------------------------
# {skill_dir} placeholder in NativeCommandTool
# ---------------------------------------------------------------------------


class TestSkillDirPlaceholder:
    """Tests for {skill_dir} placeholder replacement in NativeCommandTool."""

    @pytest.mark.asyncio
    async def test_skill_dir_replaced_in_command(self, tmp_path: Path) -> None:
        """{skill_dir} in command is replaced with the skill directory path."""
        skill_path = str(tmp_path / "my-skill")
        schema = _build_args_schema("test-tool", {})
        tool = NativeCommandTool(
            name="test-tool",
            description="test",
            args_schema=schema,
            tool_type="shell",
            command="{skill_dir}/scripts/run.sh",
            skill_dir=skill_path,
        )

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"ok\n", b""))
        mock_proc.returncode = 0

        with patch(
            "smartclaw.skills.native_command.asyncio.create_subprocess_shell",
            new_callable=AsyncMock,
        ) as mock_shell:
            mock_shell.return_value = mock_proc
            result = await tool._arun()

        call_cmd = mock_shell.call_args[0][0]
        assert skill_path in call_cmd
        assert "{skill_dir}" not in call_cmd

    @pytest.mark.asyncio
    async def test_skill_dir_replaced_in_working_dir(self, tmp_path: Path) -> None:
        """{skill_dir} in working_dir is replaced with the skill directory path."""
        skill_path = tmp_path / "my-skill"
        skill_path.mkdir(parents=True)
        schema = _build_args_schema("test-tool", {})
        tool = NativeCommandTool(
            name="test-tool",
            description="test",
            args_schema=schema,
            tool_type="shell",
            command="echo hello",
            working_dir="{skill_dir}",
            skill_dir=str(skill_path),
        )

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"hello\n", b""))
        mock_proc.returncode = 0

        with patch(
            "smartclaw.skills.native_command.asyncio.create_subprocess_shell",
            new_callable=AsyncMock,
        ) as mock_shell:
            mock_shell.return_value = mock_proc
            result = await tool._arun()

        call_kwargs = mock_shell.call_args[1]
        assert str(skill_path) in str(call_kwargs.get("cwd", ""))

    def test_skill_dir_in_substitute_placeholders(self) -> None:
        """{skill_dir} is resolved via system_placeholders in substitute_placeholders."""
        template = "{skill_dir}/scripts/analyze.py --target {path}"
        params = {"path": "/tmp/code"}
        param_defs = {"path": ParameterDef(type="string", description="target")}
        result = substitute_placeholders(
            template, params, param_defs,
            system_placeholders={"skill_dir": "/home/user/skills/my-skill"},
        )
        assert result == "/home/user/skills/my-skill/scripts/analyze.py --target /tmp/code"

    def test_from_tool_def_stores_skill_dir(self) -> None:
        """from_tool_def with skill_dir stores it on the tool instance."""
        td = ToolDef(
            name="test",
            description="test",
            type="shell",
            command="echo {skill_dir}",
        )
        tool = NativeCommandTool.from_tool_def(td, skill_dir="/my/skill/dir")
        assert tool.skill_dir == "/my/skill/dir"

    def test_from_tool_def_without_skill_dir(self) -> None:
        """from_tool_def without skill_dir defaults to None."""
        td = ToolDef(
            name="test",
            description="test",
            type="shell",
            command="echo hello",
        )
        tool = NativeCommandTool.from_tool_def(td)
        assert tool.skill_dir is None


# ---------------------------------------------------------------------------
# {skill_dir} replacement in load_skills_for_context SKILL.md content
# ---------------------------------------------------------------------------


class TestSkillDirInContext:
    """{skill_dir} replacement in load_skills_for_context SKILL.md content."""

    def test_skill_dir_replaced_in_skill_md_body(self, tmp_path: Path) -> None:
        """{skill_dir} in SKILL.md body is replaced with actual skill directory."""
        skill_dir = tmp_path / "workspace" / "analyzer"
        skill_dir.mkdir(parents=True)
        md_content = (
            "---\nname: analyzer\ndescription: Code analyzer\n---\n"
            "# Analyzer\n\nRun: `{skill_dir}/scripts/analyze.py`"
        )
        (skill_dir / "SKILL.md").write_text(md_content, encoding="utf-8")

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
        )
        context = loader.load_skills_for_context(["analyzer"])

        resolved = str(skill_dir.resolve())
        assert resolved in context
        assert "{skill_dir}" not in context

    def test_skill_dir_not_replaced_when_absent(self, tmp_path: Path) -> None:
        """SKILL.md without {skill_dir} is returned unchanged."""
        skill_dir = tmp_path / "workspace" / "plain"
        skill_dir.mkdir(parents=True)
        md_content = "---\nname: plain\ndescription: Plain skill\n---\n# Plain\n\nNo placeholders."
        (skill_dir / "SKILL.md").write_text(md_content, encoding="utf-8")

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
        )
        context = loader.load_skills_for_context(["plain"])
        assert "No placeholders." in context


# ---------------------------------------------------------------------------
# Registry integration: auto-discovered scripts registered
# ---------------------------------------------------------------------------


class TestRegistryScriptIntegration:
    """Auto-discovered scripts are registered in ToolRegistry via load_and_register_all."""

    def test_auto_discovered_scripts_registered(self, tmp_path: Path) -> None:
        """Scripts in scripts/ are auto-registered alongside explicit tools."""
        skill_dir = tmp_path / "workspace" / "devops"
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir(parents=True)

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
        (skill_dir / "skill.yaml").write_text(yaml.dump(yaml_data), encoding="utf-8")
        (scripts_dir / "deploy.sh").write_text("#!/bin/bash\necho deploy", encoding="utf-8")
        (scripts_dir / "check.py").write_text("print('check')", encoding="utf-8")

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
        )
        tool_registry = ToolRegistry()
        registry = SkillsRegistry(loader, tool_registry)
        registry.load_and_register_all()

        # Explicit tool
        assert tool_registry.get("disk-usage") is not None
        # Auto-discovered scripts
        assert tool_registry.get("deploy") is not None
        assert tool_registry.get("check") is not None

    def test_no_scripts_dir_still_works(self, tmp_path: Path) -> None:
        """Skill without scripts/ directory still registers explicit tools."""
        skill_dir = tmp_path / "workspace" / "simple"
        skill_dir.mkdir(parents=True)

        yaml_data = {
            "name": "simple",
            "description": "Simple skill",
            "tools": [
                {
                    "name": "echo-tool",
                    "description": "Echo",
                    "type": "shell",
                    "command": "echo hello",
                },
            ],
        }
        (skill_dir / "skill.yaml").write_text(yaml.dump(yaml_data), encoding="utf-8")

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
        )
        tool_registry = ToolRegistry()
        registry = SkillsRegistry(loader, tool_registry)
        registry.load_and_register_all()

        assert tool_registry.get("echo-tool") is not None


# ---------------------------------------------------------------------------
# Integration: scripts/ + SKILL.md + skill.yaml all work together
# ---------------------------------------------------------------------------


class TestFullIntegration:
    """Skill with scripts/ + SKILL.md + skill.yaml all work together."""

    def test_full_skill_directory_convention(self, tmp_path: Path) -> None:
        """Skill with skill.yaml, SKILL.md, and scripts/ all integrate correctly."""
        skill_dir = tmp_path / "workspace" / "full-skill"
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir(parents=True)

        # skill.yaml with explicit tool
        yaml_data = {
            "name": "full-skill",
            "description": "Full skill with all conventions",
            "tools": [
                {
                    "name": "lint",
                    "description": "Run linter",
                    "type": "shell",
                    "command": "echo lint",
                },
            ],
        }
        (skill_dir / "skill.yaml").write_text(yaml.dump(yaml_data), encoding="utf-8")

        # SKILL.md with {skill_dir} reference
        md_content = (
            "---\nname: full-skill\ndescription: Full skill\n---\n"
            "# Full Skill\n\nRun analysis: `{skill_dir}/scripts/analyze.py`"
        )
        (skill_dir / "SKILL.md").write_text(md_content, encoding="utf-8")

        # Scripts
        (scripts_dir / "analyze.py").write_text("print('analyze')", encoding="utf-8")
        (scripts_dir / "deploy.sh").write_text("#!/bin/bash\necho deploy", encoding="utf-8")

        loader = SkillsLoader(
            workspace_dir=str(tmp_path / "workspace"),
            global_dir=str(tmp_path / "empty"),
        )

        # 1. Verify discovery
        skills = loader.list_skills()
        assert len(skills) == 1
        assert skills[0].name == "full-skill"

        # 2. Verify script discovery
        script_tools = loader.discover_scripts("full-skill")
        assert len(script_tools) == 2
        script_names = {t.name for t in script_tools}
        assert "analyze" in script_names
        assert "deploy" in script_names

        # 3. Verify SKILL.md context has {skill_dir} replaced
        context = loader.load_skills_for_context(["full-skill"])
        resolved = str(skill_dir.resolve())
        assert resolved in context
        assert "{skill_dir}" not in context

        # 4. Verify registry integration
        tool_registry = ToolRegistry()
        registry = SkillsRegistry(loader, tool_registry)
        registry.load_and_register_all()

        # Explicit tool from skill.yaml
        assert tool_registry.get("lint") is not None
        # Auto-discovered scripts
        assert tool_registry.get("analyze") is not None
        assert tool_registry.get("deploy") is not None
        # Skill itself is registered
        assert registry.get("full-skill") is not None
