"""SkillsRegistry — skill registration, management, and ToolRegistry integration.

Manages loaded skills, extracts BaseTool instances from skill entry points,
and registers/unregisters them in the central ToolRegistry.
"""

from __future__ import annotations

from typing import Any

import structlog
from langchain_core.tools import BaseTool

from smartclaw.skills.loader import SkillsLoader
from smartclaw.skills.models import SkillDefinition
from smartclaw.skills.native_command import NativeCommandTool
from smartclaw.tools.registry import ToolRegistry

logger = structlog.get_logger(component="skills.registry")


class SkillsRegistry:
    """Skill registration, management, and ToolRegistry integration."""

    def __init__(
        self,
        loader: SkillsLoader,
        tool_registry: ToolRegistry,
    ) -> None:
        self._loader = loader
        self._tool_registry = tool_registry
        self._skills: dict[str, object] = {}
        # Track which tool names belong to which skill (for unregister cleanup)
        self._skill_tools: dict[str, list[str]] = {}

    def register(self, name: str, module: object) -> None:
        """Register a skill module and extract/register its BaseTool instances.

        If the module has an ``entry_point`` callable attribute or is itself
        callable and returns a ``list[BaseTool]``, those tools are registered
        in the ToolRegistry.

        Duplicate registration overwrites the previous skill (with a warning).
        """
        if name in self._skills:
            logger.warning("duplicate_skill_registration", name=name)
            # Clean up old tools before overwriting
            self.unregister(name)

        self._skills[name] = module
        tool_names: list[str] = []

        # Try to extract tools from the module
        tools = self._extract_tools(module)
        for tool in tools:
            self._tool_registry.register(tool)
            tool_names.append(tool.name)

        self._skill_tools[name] = tool_names

        logger.info(
            "skill_registered",
            name=name,
            tool_count=len(tool_names),
            tools=tool_names,
        )

    def unregister(self, name: str) -> None:
        """Unregister a skill and remove its tools from ToolRegistry.

        Silently ignores if the skill is not registered.
        """
        if name not in self._skills:
            return

        # Remove associated tools from ToolRegistry
        tool_names = self._skill_tools.pop(name, [])
        for tool_name in tool_names:
            self._tool_registry.unregister(tool_name)

        del self._skills[name]
        logger.info("skill_unregistered", name=name, removed_tools=tool_names)

    def get(self, name: str) -> object | None:
        """Return the registered skill module, or None if not registered."""
        return self._skills.get(name)

    def list_skills(self) -> list[str]:
        """Return all registered skill names in ascending sorted order."""
        return sorted(self._skills.keys())

    def load_and_register_all(self) -> None:
        """Discover all skills via loader, load and register each.

        For skills with native command tools (type=shell/script/exec),
        creates NativeCommandTool instances via the factory.
        For skills with Python entry_points, uses the existing import mechanism.
        Logs errors and continues on individual skill/tool failures.
        """
        skill_infos = self._loader.list_skills()

        for info in skill_infos:
            try:
                result_or_body, definition = self._loader.load_skill(info.name)

                # Pure SKILL.md skill (no definition) — register as prompt skill
                # Also discover scripts/ subdirectory for auto-registered tools
                if definition is None:
                    self._skills[info.name] = result_or_body
                    script_tool_names: list[str] = []

                    # Resolve skill_dir from info.path (SKILL.md path)
                    import pathlib as _pathlib
                    md_skill_dir = str(_pathlib.Path(info.path).parent.resolve())

                    try:
                        script_defs = self._loader.discover_scripts(info.name)
                        for script_def in script_defs:
                            try:
                                bt = NativeCommandTool.from_tool_def(
                                    script_def, skill_dir=md_skill_dir
                                )
                                self._tool_registry.register(bt)
                                script_tool_names.append(bt.name)
                            except Exception as exc:
                                logger.error(
                                    "script_tool_registration_failed",
                                    skill=info.name,
                                    tool=script_def.name,
                                    error=str(exc),
                                )
                    except Exception as exc:
                        logger.error(
                            "script_discovery_failed",
                            skill=info.name,
                            error=str(exc),
                        )

                    self._skill_tools[info.name] = script_tool_names
                    logger.info(
                        "skill_registered",
                        name=info.name,
                        tool_count=len(script_tool_names),
                        tools=script_tool_names,
                        skill_type="markdown",
                    )
                    continue

                # Register native command tools from the definition
                native_tool_names: list[str] = []
                skill_dir_path: str | None = None
                if isinstance(definition, SkillDefinition):
                    # Resolve skill directory path for {skill_dir} placeholder
                    info_path = info.path  # path to skill.yaml or SKILL.md
                    skill_dir_path = str(
                        __import__("pathlib").Path(info_path).parent.resolve()
                    )

                    for tool_def in definition.tools:
                        if tool_def.type in ("shell", "script", "exec"):
                            try:
                                errors = tool_def.validate()
                                if errors:
                                    logger.error(
                                        "tool_def_validation_failed",
                                        skill=info.name,
                                        tool=tool_def.name,
                                        errors=errors,
                                    )
                                    continue
                                bt = NativeCommandTool.from_tool_def(
                                    tool_def, skill_dir=skill_dir_path
                                )
                                self._tool_registry.register(bt)
                                native_tool_names.append(bt.name)
                            except Exception as exc:
                                logger.error(
                                    "native_tool_registration_failed",
                                    skill=info.name,
                                    tool=tool_def.name,
                                    error=str(exc),
                                )
                                continue

                    # Auto-discover scripts/ subdirectory
                    try:
                        script_defs = self._loader.discover_scripts(info.name)
                        for script_def in script_defs:
                            try:
                                bt = NativeCommandTool.from_tool_def(
                                    script_def, skill_dir=skill_dir_path
                                )
                                self._tool_registry.register(bt)
                                native_tool_names.append(bt.name)
                            except Exception as exc:
                                logger.error(
                                    "script_tool_registration_failed",
                                    skill=info.name,
                                    tool=script_def.name,
                                    error=str(exc),
                                )
                    except Exception as exc:
                        logger.error(
                            "script_discovery_failed",
                            skill=info.name,
                            error=str(exc),
                        )

                # If there's a Python entry_point, call it and register
                if isinstance(definition, SkillDefinition) and definition.entry_point:
                    entry_fn = result_or_body
                    result = entry_fn()
                    self._skills[info.name] = result

                    # Extract Python tools
                    py_tool_names: list[str] = []
                    py_tools = self._extract_tools(result)
                    for tool in py_tools:
                        self._tool_registry.register(tool)
                        py_tool_names.append(tool.name)

                    self._skill_tools[info.name] = py_tool_names + native_tool_names
                else:
                    # Pure YAML skill (native command tools only, no entry_point)
                    self._skills[info.name] = definition
                    self._skill_tools[info.name] = native_tool_names

                logger.info(
                    "skill_registered",
                    name=info.name,
                    tool_count=len(self._skill_tools.get(info.name, [])),
                    tools=self._skill_tools.get(info.name, []),
                )
            except Exception as exc:
                logger.error(
                    "skill_load_failed",
                    name=info.name,
                    error=str(exc),
                )
                continue

    @staticmethod
    def _extract_tools(module: object) -> list[BaseTool]:
        """Extract BaseTool instances from a skill module/result.

        Supports:
        - A list of BaseTool instances (returned by entry_point)
        - An object with a ``tools`` attribute that is a list of BaseTool
        """
        tools: list[BaseTool] = []

        if isinstance(module, list):
            for item in module:
                if isinstance(item, BaseTool):
                    tools.append(item)
        elif hasattr(module, "tools"):
            attr = getattr(module, "tools")
            if isinstance(attr, list):
                for item in attr:
                    if isinstance(item, BaseTool):
                        tools.append(item)

        return tools
