"""Unit tests for filesystem tools."""

from __future__ import annotations

import pathlib

import pytest

from smartclaw.security.path_policy import PathPolicy
from smartclaw.tools.filesystem import ListDirectoryTool, ReadFileTool, WriteFileTool


def _permissive_policy(tmp_path: pathlib.Path) -> PathPolicy:
    """Create a policy that allows tmp_path and everything under it."""
    resolved = str(tmp_path.resolve())
    return PathPolicy(allowed_patterns=[resolved, f"{resolved}/**"])


class TestWriteFileParentCreation:
    """Test parent directory creation (Req 3.4)."""

    @pytest.mark.asyncio
    async def test_creates_parent_dirs(self, tmp_path: pathlib.Path) -> None:
        policy = _permissive_policy(tmp_path)
        tool = WriteFileTool(path_policy=policy)
        target = tmp_path / "a" / "b" / "c" / "file.txt"

        result = await tool._arun(path=str(target), content="hello")
        assert "Successfully wrote" in result
        assert target.exists()
        assert target.read_text() == "hello"


class TestListDirectoryFormat:
    """Test list_directory format with file type indicators (Req 3.5)."""

    @pytest.mark.asyncio
    async def test_format_with_indicators(self, tmp_path: pathlib.Path) -> None:
        policy = _permissive_policy(tmp_path)
        tool = ListDirectoryTool(path_policy=policy)

        (tmp_path / "file.txt").touch()
        (tmp_path / "subdir").mkdir()

        result = await tool._arun(path=str(tmp_path))
        assert "[FILE] file.txt" in result
        assert "[DIR]  subdir" in result


class TestReadFileNotFound:
    """Test read_file with non-existent file returns error with path (Req 3.2)."""

    @pytest.mark.asyncio
    async def test_nonexistent_file_error(self, tmp_path: pathlib.Path) -> None:
        policy = _permissive_policy(tmp_path)
        tool = ReadFileTool(path_policy=policy)
        missing = str(tmp_path / "nope.txt")

        result = await tool._arun(path=missing)
        assert "Error" in result
        assert missing in result
