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

from smartclaw.skills.markdown_skill import parse_skill_md
from smartclaw.skills.models import ParameterDef, SkillDefinition, SkillInfo, ToolDef

logger = structlog.get_logger(component="skills.loader")


def _is_executable(path: Path) -> bool:
    """Check if a file has executable permission (Unix)."""
    import os
    return os.access(path, os.X_OK)


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
        A directory is a valid skill if it contains skill.yaml and/or SKILL.md.
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
                info = self._scan_skill_dir(child, source)
                if info is None:
                    continue
                if info.name in seen:
                    continue
                seen.add(info.name)
                skills.append(info)

        return skills

    def _scan_skill_dir(self, child: Path, source: str) -> SkillInfo | None:
        """Scan a single skill directory for skill.yaml and/or SKILL.md.

        Returns SkillInfo if valid, None otherwise.
        """
        yaml_path = child / "skill.yaml"
        md_path = child / "SKILL.md"
        has_yaml = yaml_path.is_file()
        has_md = md_path.is_file()

        if not has_yaml and not has_md:
            return None

        # Try skill.yaml first for metadata
        if has_yaml:
            try:
                raw = yaml_path.read_text(encoding="utf-8")
                definition = self.parse_skill_yaml(raw)
            except Exception:
                logger.warning(
                    "invalid_skill_yaml",
                    path=str(yaml_path),
                    source=source,
                )
                # If YAML is invalid but SKILL.md exists, fall through to MD
                if not has_md:
                    return None
                has_yaml = False
            else:
                errors = definition.validate()
                if errors:
                    logger.warning(
                        "skill_validation_failed",
                        name=definition.name,
                        path=str(yaml_path),
                        errors=errors,
                    )
                    # If YAML validation fails but SKILL.md exists, fall through
                    if not has_md:
                        return None
                    has_yaml = False
                else:
                    return SkillInfo(
                        name=definition.name,
                        path=str(yaml_path),
                        source=source,
                        description=definition.description,
                    )

        # SKILL.md path
        if has_md:
            try:
                md_content = md_path.read_text(encoding="utf-8")
                name, description, _body = parse_skill_md(md_content, child.name)
            except Exception:
                logger.warning(
                    "invalid_skill_md",
                    path=str(md_path),
                    source=source,
                )
                return None

            if not name or not description:
                return None

            return SkillInfo(
                name=name,
                path=str(md_path),
                source=source,
                description=description,
            )

        return None

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_skill(
        self, name: str
    ) -> tuple[Callable[..., Any], SkillDefinition] | tuple[str, None]:
        """Load a skill by name.

        For YAML skills with entry_point: import entry_point, return
        ``(callable, definition)``.

        For pure SKILL.md skills (no skill.yaml): return
        ``(body_content, None)``.

        For hybrid skills (skill.yaml + SKILL.md): loads entry_point and
        returns ``(callable, definition)`` — SKILL.md body is available
        via :meth:`load_skills_for_context`.

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
            skill_path = Path(skill_dir) / name
            yaml_path = skill_path / "skill.yaml"
            md_path = skill_path / "SKILL.md"

            has_yaml = yaml_path.is_file()
            has_md = md_path.is_file()

            if not has_yaml and not has_md:
                continue

            # If skill.yaml exists, load it
            if has_yaml:
                raw = yaml_path.read_text(encoding="utf-8")
                definition = self.parse_skill_yaml(raw)

                # If there's an entry_point, import it
                if definition.entry_point:
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

                # No entry_point — pure YAML skill with native command tools
                return definition, definition  # type: ignore[return-value]

            # Pure SKILL.md skill (no skill.yaml)
            if has_md:
                md_content = md_path.read_text(encoding="utf-8")
                _name, _desc, body = parse_skill_md(md_content, name)
                return body, None  # type: ignore[return-value]

        raise ImportError(f"Skill '{name}' not found in any skill directory")

    # ------------------------------------------------------------------
    # Script auto-discovery
    # ------------------------------------------------------------------

    _SCRIPT_EXTENSIONS: set[str] = {".sh", ".py", ".js", ".mjs", ".ts", ".rb", ".pl", ".go"}

    def discover_scripts(self, skill_name: str) -> list[ToolDef]:
        """Scan the ``scripts/`` subdirectory of a skill for executable files.

        Convention: files in ``{skill_dir}/scripts/`` are auto-registered as
        script-type tools.

        For each file in ``scripts/``:
        - name: filename without extension (e.g. ``deploy.sh`` → ``deploy``)
        - description: ``"Run {filename} script from {skill_name} skill"``
        - type: ``"script"``
        - command: absolute path to the script file
        - working_dir: skill directory

        Supported extensions: ``.sh``, ``.py``, ``.js``, ``.mjs``, ``.ts``,
        ``.rb``, ``.pl``, ``.go``.
        Files without extensions are also included if they have executable
        permission.

        Returns list of ToolDef for discovered scripts.
        """
        dirs: list[str | None] = [
            self._workspace_dir,
            self._global_dir,
            self._builtin_dir,
        ]

        for skill_dir in dirs:
            if skill_dir is None:
                continue
            skill_path = Path(skill_dir) / skill_name
            scripts_path = skill_path / "scripts"
            if not scripts_path.is_dir():
                continue

            tools: list[ToolDef] = []
            for entry in sorted(scripts_path.iterdir()):
                if not entry.is_file():
                    continue

                suffix = entry.suffix.lower()
                # Include files with known extensions or executable files without extension
                if suffix and suffix not in self._SCRIPT_EXTENSIONS:
                    continue
                if not suffix and not _is_executable(entry):
                    continue

                tool_name = entry.stem if suffix else entry.name
                tools.append(
                    ToolDef(
                        name=tool_name,
                        description=f"Run {entry.name} script from {skill_name} skill",
                        type="script",
                        command=str(entry.resolve()),
                        working_dir=str(skill_path.resolve()),
                    )
                )
            return tools

        return []

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

        For each skill name, attempts to load skill.yaml and/or SKILL.md content.
        Replaces ``{skill_dir}`` in SKILL.md body with the actual skill directory path.
        Returns skill sections separated by ``---``.
        """
        if not skill_names:
            return ""

        parts: list[str] = []
        for name in skill_names:
            dirs: list[str | None] = [
                self._workspace_dir,
                self._global_dir,
                self._builtin_dir,
            ]
            found = False
            for skill_dir in dirs:
                if skill_dir is None:
                    continue
                skill_path = Path(skill_dir) / name
                yaml_path = skill_path / "skill.yaml"
                md_path = skill_path / "SKILL.md"

                content_parts: list[str] = []
                if yaml_path.is_file():
                    content_parts.append(yaml_path.read_text(encoding="utf-8"))
                if md_path.is_file():
                    md_content = md_path.read_text(encoding="utf-8")
                    _n, _d, body = parse_skill_md(md_content, name)
                    # Replace {skill_dir} with actual skill directory path
                    resolved_dir = str(skill_path.resolve())
                    body = body.replace("{skill_dir}", resolved_dir)
                    content_parts.append(body)

                if content_parts:
                    combined = "\n\n".join(content_parts)
                    parts.append(f"### Skill: {name}\n\n{combined}")
                    found = True
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
                    # Parse parameters as dict[str, ParameterDef]
                    raw_params = t.get("parameters", {})
                    parsed_params: dict[str, ParameterDef] = {}
                    if isinstance(raw_params, dict):
                        for pname, pval in raw_params.items():
                            if isinstance(pval, dict):
                                parsed_params[pname] = ParameterDef(
                                    type=pval.get("type", "string"),
                                    description=pval.get("description", ""),
                                    default=pval.get("default"),
                                )
                    tools.append(
                        ToolDef(
                            name=t.get("name", ""),
                            description=t.get("description", ""),
                            function=t.get("function", ""),
                            type=t.get("type"),
                            command=t.get("command", ""),
                            args=t.get("args", []),
                            working_dir=t.get("working_dir"),
                            timeout=t.get("timeout", 60),
                            max_output_chars=t.get("max_output_chars", 10_000),
                            deny_patterns=t.get("deny_patterns", []),
                            parameters=parsed_params,
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
            tools_data: list[dict[str, Any]] = []
            for t in definition.tools:
                td: dict[str, Any] = {
                    "name": t.name,
                    "description": t.description,
                }
                if t.function:
                    td["function"] = t.function
                if t.type is not None:
                    td["type"] = t.type
                if t.command:
                    td["command"] = t.command
                if t.args:
                    td["args"] = t.args
                if t.working_dir is not None:
                    td["working_dir"] = t.working_dir
                if t.timeout != 60:
                    td["timeout"] = t.timeout
                if t.max_output_chars != 10_000:
                    td["max_output_chars"] = t.max_output_chars
                if t.deny_patterns:
                    td["deny_patterns"] = t.deny_patterns
                if t.parameters:
                    params_data: dict[str, dict[str, Any]] = {}
                    for pname, pdef in t.parameters.items():
                        pd: dict[str, Any] = {"type": pdef.type}
                        if pdef.description:
                            pd["description"] = pdef.description
                        if pdef.default is not None:
                            pd["default"] = pdef.default
                        params_data[pname] = pd
                    td["parameters"] = params_data
                tools_data.append(td)
            data["tools"] = tools_data

        if definition.parameters:
            data["parameters"] = dict(definition.parameters)

        return yaml.dump(data, default_flow_style=False, allow_unicode=True)
