"""ToolRegistry — central registry for all SmartClaw tool instances.

Manages tool lifecycle: register, discover, list, merge, and produce
a unified ``list[BaseTool]`` for ``build_graph()``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from langchain_core.tools import BaseTool

if TYPE_CHECKING:
    from smartclaw.security.path_policy import PathPolicy

logger = structlog.get_logger(component="tools.registry")


class ToolRegistry:
    """Tool registration and discovery center."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a single tool. Replaces existing tool with same name (logs warning)."""
        if tool.name in self._tools:
            logger.warning("duplicate_tool_registration", name=tool.name)
        self._tools[tool.name] = tool

    def register_many(self, tools: list[BaseTool]) -> None:
        """Register multiple tools."""
        for tool in tools:
            self.register(tool)

    def unregister(self, name: str) -> bool:
        """Remove a tool by name. Returns True if removed, False if not found."""
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def get(self, name: str) -> BaseTool | None:
        """Return a tool by name, or None if not found."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """Return all registered tool names, sorted ascending."""
        return sorted(self._tools.keys())

    def get_all(self) -> list[BaseTool]:
        """Return all registered tools as a list."""
        return list(self._tools.values())

    def merge(self, other: ToolRegistry) -> None:
        """Merge all tools from *other* into this registry."""
        for tool in other.get_all():
            self.register(tool)

    @property
    def count(self) -> int:
        """Return the number of registered tools."""
        return len(self._tools)


def create_system_tools(
    workspace: str,
    path_policy: PathPolicy | None = None,
) -> ToolRegistry:
    """Instantiate all system tools and return a populated ToolRegistry.

    Args:
        workspace: Workspace directory path for filesystem/shell tools.
        path_policy: Optional PathPolicy for filesystem access control.

    Returns:
        A ToolRegistry containing all system tool instances.
    """
    from smartclaw.security.path_policy import PathPolicy as _PathPolicy
    from smartclaw.tools.edit import AppendFileTool, EditFileTool
    from smartclaw.tools.filesystem import ListDirectoryTool, ReadFileTool, WriteFileTool
    from smartclaw.tools.shell import ShellTool
    from smartclaw.tools.web_fetch import WebFetchTool
    from smartclaw.tools.web_search import WebSearchTool

    policy = path_policy if path_policy is not None else _PathPolicy()

    registry = ToolRegistry()
    registry.register_many([
        ReadFileTool(path_policy=policy),
        WriteFileTool(path_policy=policy),
        ListDirectoryTool(path_policy=policy),
        EditFileTool(path_policy=policy),
        AppendFileTool(path_policy=policy),
        ShellTool(),
        WebSearchTool(),
        WebFetchTool(),
    ])
    return registry
