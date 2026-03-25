"""SkillsRegistry — skill registration, management, and ToolRegistry integration.

Manages loaded skills, extracts BaseTool instances from skill entry points,
and registers/unregisters them in the central ToolRegistry.
"""

from __future__ import annotations

from typing import Any

import structlog
from langchain_core.tools import BaseTool

from smartclaw.skills.loader import SkillsLoader
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

        Logs errors and continues on individual skill failures.
        """
        skill_infos = self._loader.list_skills()

        for info in skill_infos:
            try:
                entry_fn, _definition = self._loader.load_skill(info.name)
                # Call the entry point to get the module/tools
                result = entry_fn()
                self.register(info.name, result)
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
