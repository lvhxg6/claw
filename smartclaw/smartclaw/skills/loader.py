"""SkillsLoader — YAML skill definition discovery and dynamic loading.

Scans configured skill directories for ``{skill_name}/skill.yaml`` files,
parses them into SkillDefinition objects, and dynamically loads entry points
via importlib. Adapted from PicoClaw's ``pkg/skills/loader.go``.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Callable

import structlog
import yaml

from smartclaw.skills.models import SkillDefinition, SkillInfo, ToolDef

logger = structlog.get_logger(component="skills.loader")


class SkillsLoader:
    """YAML skill definition discovery and dynamic loading."""

    def __init__(
        self,
        workspace_dir: str | None = None,
        global_dir: str = "~/.smartclaw/skills",
        builtin_dir: str | None = None,
    ) -> None:
        self._workspace_dir = (
            str(Path(workspace_dir).expanduser()) if workspace_dir else None
        )
        self._global_dir = str(Path(global_dir).expanduser())
        self._builtin_dir = (
            str(Path(builtin_dir).expanduser()) if builtin_dir else None
        )

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def list_skills(self) -> list[SkillInfo]:
        """Scan all skill directories and return valid skill info.

        Priority: workspace > global > builtin.
        Duplicate names from lower-priority sources are ignored.
        """
        skills: list[SkillInfo] = []
        seen: set[str] = set()

        dirs_with_source: list[tuple[str | None, str]] = [
            (self._workspace_dir, "workspace"),
            (self._global_dir, "global"),
            (self._builtin_dir, "builtin"),
        ]

        for skill_dir, source in dirs_with_source:
            if skill_dir is None:
                continue
            base = Path(skill_dir)
            if not base.is_dir():
                continue
            for child in sorted(base.iterdir()):
                if not child.is_dir():
                    continue
                yaml_path = child / "skill.yaml"
                if not yaml_path.is_file():
                    continue
                try:
                    raw = yaml_path.read_text(encoding="utf-8")
                    definition = self.parse_skill_yaml(raw)
                except Exception:
                    logger.warning(
                        "invalid_skill_yaml",
                        path=str(yaml_path),
                        source=source,
                    )
                    continue

                errors = definition.validate()
                if errors:
                    logger.warning(
                        "skill_validation_failed",
                        name=definition.name,
                        path=str(yaml_path),
                        errors=errors,
                    )
                    continue

                if definition.name in seen:
                    continue
                seen.add(definition.name)

                skills.append(
                    SkillInfo(
                        name=definition.name,
                        path=str(yaml_path),
                        source=source,
                        description=definition.description,
                    )
                )

        return skills

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_skill(
        self, name: str
    ) -> tuple[Callable[..., Any], SkillDefinition]:
        """Load a skill by name: import entry_point, return (callable, definition).

        Searches workspace > global > builtin for the skill's skill.yaml,
        parses it, then uses importlib to import the entry_point module
        and retrieve the function.

        Raises ImportError with a descriptive message on import failure.
        """
        dirs_with_source: list[tuple[str | None, str]] = [
            (self._workspace_dir, "workspace"),
            (self._global_dir, "global"),
            (self._builtin_dir, "builtin"),
        ]

        for skill_dir, source in dirs_with_source:
            if skill_dir is None:
                continue
            yaml_path = Path(skill_dir) / name / "skill.yaml"
            if not yaml_path.is_file():
                continue

            raw = yaml_path.read_text(encoding="utf-8")
            definition = self.parse_skill_yaml(raw)

            entry_point = definition.entry_point
            if ":" not in entry_point:
                raise ImportError(
                    f"Invalid entry_point format '{entry_point}' for skill "
                    f"'{name}': expected 'module.path:function_name'"
                )

            module_path, func_name = entry_point.rsplit(":", 1)
            try:
                mod = importlib.import_module(module_path)
            except ModuleNotFoundError as exc:
                raise ImportError(
                    f"Cannot import module '{module_path}' for skill "
                    f"'{name}': {exc}"
                ) from exc

            func = getattr(mod, func_name, None)
            if func is None:
                raise ImportError(
                    f"Module '{module_path}' has no attribute '{func_name}' "
                    f"for skill '{name}'"
                )

            return func, definition

        raise ImportError(f"Skill '{name}' not found in any skill directory")

    # ------------------------------------------------------------------
    # Summary / context
    # ------------------------------------------------------------------

    def build_skills_summary(self) -> str:
        """Generate a formatted summary of all discovered skills.

        Returns a string suitable for injection into the Agent's system
        prompt, listing each skill's name, description, and source.
        """
        all_skills = self.list_skills()
        if not all_skills:
            return ""

        lines: list[str] = ["<skills>"]
        for s in all_skills:
            lines.append("  <skill>")
            lines.append(f"    <name>{s.name}</name>")
            lines.append(f"    <description>{s.description}</description>")
            lines.append(f"    <source>{s.source}</source>")
            lines.append("  </skill>")
        lines.append("</skills>")
        return "\n".join(lines)

    def load_skills_for_context(
        self, skill_names: list[str]
    ) -> str:
        """Load multiple skills and concatenate their content.

        For each skill name, attempts to load the skill.yaml content.
        Returns skill sections separated by ``---``.
        """
        if not skill_names:
            return ""

        parts: list[str] = []
        for name in skill_names:
            # Search for the skill.yaml across directories
            dirs: list[str | None] = [
                self._workspace_dir,
                self._global_dir,
                self._builtin_dir,
            ]
            for skill_dir in dirs:
                if skill_dir is None:
                    continue
                yaml_path = Path(skill_dir) / name / "skill.yaml"
                if yaml_path.is_file():
                    content = yaml_path.read_text(encoding="utf-8")
                    parts.append(f"### Skill: {name}\n\n{content}")
                    break

        return "\n\n---\n\n".join(parts)

    # ------------------------------------------------------------------
    # YAML serialization
    # ------------------------------------------------------------------

    @staticmethod
    def parse_skill_yaml(yaml_str: str) -> SkillDefinition:
        """Parse a YAML string into a SkillDefinition."""
        data = yaml.safe_load(yaml_str)
        if not isinstance(data, dict):
            raise ValueError("skill.yaml must be a YAML mapping")

        tools_raw = data.get("tools", [])
        tools: list[ToolDef] = []
        if isinstance(tools_raw, list):
            for t in tools_raw:
                if isinstance(t, dict):
                    tools.append(
                        ToolDef(
                            name=t.get("name", ""),
                            description=t.get("description", ""),
                            function=t.get("function", ""),
                        )
                    )

        parameters = data.get("parameters", {})
        if not isinstance(parameters, dict):
            parameters = {}

        return SkillDefinition(
            name=data.get("name", ""),
            description=data.get("description", ""),
            entry_point=data.get("entry_point", ""),
            version=data.get("version"),
            author=data.get("author"),
            tools=tools,
            parameters=parameters,
        )

    @staticmethod
    def serialize_skill_yaml(definition: SkillDefinition) -> str:
        """Serialize a SkillDefinition to a YAML string."""
        data: dict[str, Any] = {
            "name": definition.name,
            "description": definition.description,
            "entry_point": definition.entry_point,
        }

        if definition.version is not None:
            data["version"] = definition.version
        if definition.author is not None:
            data["author"] = definition.author

        if definition.tools:
            data["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "function": t.function,
                }
                for t in definition.tools
            ]

        if definition.parameters:
            data["parameters"] = dict(definition.parameters)

        return yaml.dump(data, default_flow_style=False, allow_unicode=True)
