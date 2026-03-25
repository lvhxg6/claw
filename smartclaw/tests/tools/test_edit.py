"""Unit tests for EditFileTool and AppendFileTool."""

from __future__ import annotations

import pathlib

import pytest

from smartclaw.security.path_policy import PathPolicy
from smartclaw.tools.edit import AppendFileTool, EditFileTool, replace_single_occurrence


# ---------------------------------------------------------------------------
# replace_single_occurrence pure function
# ---------------------------------------------------------------------------


class TestReplaceSingleOccurrence:
    def test_happy_path(self) -> None:
        assert replace_single_occurrence("hello world", "world", "python") == "hello python"

    def test_not_found(self) -> None:
        with pytest.raises(ValueError, match="not found"):
            replace_single_occurrence("hello world", "missing", "x")

    def test_ambiguous(self) -> None:
        with pytest.raises(ValueError, match="2 times"):
            replace_single_occurrence("aa bb aa", "aa", "cc")


# ---------------------------------------------------------------------------
# EditFileTool
# ---------------------------------------------------------------------------


class TestEditFileTool:
    async def test_successful_edit(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        tool = EditFileTool(path_policy=PathPolicy())
        result = await tool._arun(path=str(f), old_text="world", new_text="python")
        assert "Successfully edited" in result
        assert f.read_text() == "hello python"

    async def test_file_not_found(self, tmp_path: pathlib.Path) -> None:
        tool = EditFileTool(path_policy=PathPolicy())
        result = await tool._arun(path=str(tmp_path / "nope.txt"), old_text="a", new_text="b")
        assert "File not found" in result

    async def test_old_text_not_found(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("hello", encoding="utf-8")
        tool = EditFileTool(path_policy=PathPolicy())
        result = await tool._arun(path=str(f), old_text="missing", new_text="x")
        assert "not found" in result

    async def test_path_denied(self, tmp_path: pathlib.Path) -> None:
        policy = PathPolicy(denied_patterns=[f"{tmp_path.resolve()}/**"])
        tool = EditFileTool(path_policy=policy)
        result = await tool._arun(path=str(tmp_path / "f.txt"), old_text="a", new_text="b")
        assert "Access denied" in result


# ---------------------------------------------------------------------------
# AppendFileTool
# ---------------------------------------------------------------------------


class TestAppendFileTool:
    async def test_append_to_existing(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("hello", encoding="utf-8")
        tool = AppendFileTool(path_policy=PathPolicy())
        result = await tool._arun(path=str(f), content=" world")
        assert "Successfully appended" in result
        assert f.read_text() == "hello world"

    async def test_create_new_file(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "sub" / "new.txt"
        tool = AppendFileTool(path_policy=PathPolicy())
        result = await tool._arun(path=str(f), content="new content")
        assert "Successfully appended" in result
        assert f.read_text() == "new content"

    async def test_path_denied(self, tmp_path: pathlib.Path) -> None:
        policy = PathPolicy(denied_patterns=[f"{tmp_path.resolve()}/**"])
        tool = AppendFileTool(path_policy=policy)
        result = await tool._arun(path=str(tmp_path / "f.txt"), content="x")
        assert "Access denied" in result

    async def test_empty_content_append(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("original", encoding="utf-8")
        tool = AppendFileTool(path_policy=PathPolicy())
        await tool._arun(path=str(f), content="")
        assert f.read_text() == "original"
