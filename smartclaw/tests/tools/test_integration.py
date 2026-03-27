"""Integration tests for create_system_tools and agent graph wiring."""

from __future__ import annotations

import pathlib

from langchain_core.tools import BaseTool

from smartclaw.security.path_policy import PathPolicy
from smartclaw.tools.registry import ToolRegistry, create_system_tools


class TestCreateSystemTools:
    """Test create_system_tools returns expected tools (Req 7.3, 7.4)."""

    def test_returns_tool_registry(self, tmp_path: pathlib.Path) -> None:
        registry = create_system_tools(workspace=str(tmp_path))
        assert isinstance(registry, ToolRegistry)

    def test_contains_all_system_tools(self, tmp_path: pathlib.Path) -> None:
        registry = create_system_tools(workspace=str(tmp_path))
        names = registry.list_tools()

        assert "read_file" in names
        assert "write_file" in names
        assert "list_directory" in names
        assert "edit_file" in names
        assert "append_file" in names
        assert "exec_command" in names
        assert "web_search" in names
        assert "web_fetch" in names
        assert "ask_clarification" in names
        assert registry.count == 9

    def test_all_tools_are_base_tool(self, tmp_path: pathlib.Path) -> None:
        registry = create_system_tools(workspace=str(tmp_path))
        for tool in registry.get_all():
            assert isinstance(tool, BaseTool)

    def test_custom_policy_is_applied(self, tmp_path: pathlib.Path) -> None:
        policy = PathPolicy(allowed_patterns=[f"{tmp_path.resolve()}/**"])
        registry = create_system_tools(workspace=str(tmp_path), path_policy=policy)

        read_tool = registry.get("read_file")
        assert read_tool is not None


class TestCombinedToolList:
    """Test combined browser + system tools produce valid list[BaseTool] (Req 7.1, 7.2)."""

    def test_merge_browser_and_system_tools(self, tmp_path: pathlib.Path) -> None:
        system_reg = create_system_tools(workspace=str(tmp_path))

        # Simulate browser tools by creating a separate registry
        browser_reg = ToolRegistry()

        # Merge
        system_reg.merge(browser_reg)

        all_tools = system_reg.get_all()
        assert all(isinstance(t, BaseTool) for t in all_tools)
        assert len(all_tools) >= 9  # At least the 9 system tools
