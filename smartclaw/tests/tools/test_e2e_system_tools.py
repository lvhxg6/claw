"""End-to-end tests for all system tools.

These tests call the real tool implementations against the real filesystem
and real shell — no mocks. They verify the complete execution path from
tool input to final output.

Network-dependent tools (web_search, web_fetch) are tested with real HTTP
calls and marked with ``pytest.mark.network`` so CI can skip them if needed.
"""

from __future__ import annotations

import pathlib
import platform

import pytest

from smartclaw.security.path_policy import PathPolicy
from smartclaw.tools.edit import AppendFileTool, EditFileTool
from smartclaw.tools.filesystem import ListDirectoryTool, ReadFileTool, WriteFileTool
from smartclaw.tools.shell import ShellTool
from smartclaw.tools.web_fetch import WebFetchTool
from smartclaw.tools.web_search import WebSearchTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _permissive_policy(tmp_path: pathlib.Path) -> PathPolicy:
    resolved = str(tmp_path.resolve())
    return PathPolicy(allowed_patterns=[resolved, f"{resolved}/**"])


# ===================================================================
# 1. read_file — E2E
# ===================================================================


class TestReadFileE2E:
    """E2E: read_file reads real files from disk."""

    async def test_read_small_file(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "hello.txt"
        f.write_text("Hello, SmartClaw!", encoding="utf-8")

        tool = ReadFileTool(path_policy=_permissive_policy(tmp_path))
        result = await tool._arun(path=str(f))

        assert result == "Hello, SmartClaw!"

    async def test_read_utf8_chinese(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "chinese.txt"
        f.write_text("你好世界", encoding="utf-8")

        tool = ReadFileTool(path_policy=_permissive_policy(tmp_path))
        result = await tool._arun(path=str(f))

        assert result == "你好世界"

    async def test_read_binary_safe(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "binary.bin"
        f.write_bytes(b"\x00\x01\x02\xff")

        tool = ReadFileTool(path_policy=_permissive_policy(tmp_path))
        result = await tool._arun(path=str(f))

        # Should not crash — decode with errors="replace"
        assert isinstance(result, str)

    async def test_read_truncation(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "big.txt"
        f.write_text("A" * 2000, encoding="utf-8")

        tool = ReadFileTool(path_policy=_permissive_policy(tmp_path))
        result = await tool._arun(path=str(f), max_bytes=100)

        assert len(result) < 2000
        assert "truncated" in result

    async def test_read_nonexistent(self, tmp_path: pathlib.Path) -> None:
        tool = ReadFileTool(path_policy=_permissive_policy(tmp_path))
        result = await tool._arun(path=str(tmp_path / "ghost.txt"))

        assert "Error" in result
        assert "not found" in result.lower()

    async def test_read_empty_file(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "empty.txt"
        f.write_text("", encoding="utf-8")

        tool = ReadFileTool(path_policy=_permissive_policy(tmp_path))
        result = await tool._arun(path=str(f))

        assert result == ""


# ===================================================================
# 2. write_file — E2E
# ===================================================================


class TestWriteFileE2E:
    """E2E: write_file creates real files on disk."""

    async def test_write_new_file(self, tmp_path: pathlib.Path) -> None:
        target = tmp_path / "output.txt"
        tool = WriteFileTool(path_policy=_permissive_policy(tmp_path))

        result = await tool._arun(path=str(target), content="written by e2e")

        assert "Successfully wrote" in result
        assert target.read_text() == "written by e2e"

    async def test_write_creates_nested_dirs(self, tmp_path: pathlib.Path) -> None:
        target = tmp_path / "a" / "b" / "c" / "deep.txt"
        tool = WriteFileTool(path_policy=_permissive_policy(tmp_path))

        result = await tool._arun(path=str(target), content="deep")

        assert "Successfully wrote" in result
        assert target.exists()
        assert target.read_text() == "deep"

    async def test_write_overwrites_existing(self, tmp_path: pathlib.Path) -> None:
        target = tmp_path / "overwrite.txt"
        target.write_text("old", encoding="utf-8")

        tool = WriteFileTool(path_policy=_permissive_policy(tmp_path))
        await tool._arun(path=str(target), content="new")

        assert target.read_text() == "new"

    async def test_write_empty_content(self, tmp_path: pathlib.Path) -> None:
        target = tmp_path / "empty.txt"
        tool = WriteFileTool(path_policy=_permissive_policy(tmp_path))

        result = await tool._arun(path=str(target), content="")

        assert "Successfully wrote" in result
        assert target.read_text() == ""


# ===================================================================
# 3. list_directory — E2E
# ===================================================================


class TestListDirectoryE2E:
    """E2E: list_directory lists real directory contents."""

    async def test_list_mixed_entries(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "file_a.txt").touch()
        (tmp_path / "file_b.py").touch()
        (tmp_path / "subdir").mkdir()

        tool = ListDirectoryTool(path_policy=_permissive_policy(tmp_path))
        result = await tool._arun(path=str(tmp_path))

        assert "[FILE] file_a.txt" in result
        assert "[FILE] file_b.py" in result
        assert "[DIR]  subdir" in result

    async def test_list_empty_directory(self, tmp_path: pathlib.Path) -> None:
        empty = tmp_path / "empty_dir"
        empty.mkdir()

        tool = ListDirectoryTool(path_policy=_permissive_policy(tmp_path))
        result = await tool._arun(path=str(empty))

        assert "empty directory" in result

    async def test_list_nonexistent(self, tmp_path: pathlib.Path) -> None:
        tool = ListDirectoryTool(path_policy=_permissive_policy(tmp_path))
        result = await tool._arun(path=str(tmp_path / "nope"))

        assert "Error" in result

    async def test_list_file_not_dir(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "file.txt"
        f.touch()

        tool = ListDirectoryTool(path_policy=_permissive_policy(tmp_path))
        result = await tool._arun(path=str(f))

        assert "Error" in result
        assert "Not a directory" in result


# ===================================================================
# 4. edit_file — E2E
# ===================================================================


class TestEditFileE2E:
    """E2E: edit_file performs real file edits."""

    async def test_edit_single_occurrence(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "code.py"
        f.write_text('name = "old_value"\nprint(name)\n', encoding="utf-8")

        tool = EditFileTool(path_policy=_permissive_policy(tmp_path))
        result = await tool._arun(
            path=str(f), old_text='"old_value"', new_text='"new_value"'
        )

        assert "Successfully edited" in result
        content = f.read_text()
        assert '"new_value"' in content
        assert '"old_value"' not in content

    async def test_edit_multiline(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "multi.txt"
        f.write_text("line1\nline2\nline3\n", encoding="utf-8")

        tool = EditFileTool(path_policy=_permissive_policy(tmp_path))
        result = await tool._arun(
            path=str(f), old_text="line2\nline3", new_text="replaced2\nreplaced3"
        )

        assert "Successfully edited" in result
        assert "replaced2\nreplaced3" in f.read_text()

    async def test_edit_ambiguous_rejected(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "dup.txt"
        f.write_text("foo bar foo", encoding="utf-8")

        tool = EditFileTool(path_policy=_permissive_policy(tmp_path))
        result = await tool._arun(path=str(f), old_text="foo", new_text="baz")

        assert "Error" in result
        assert "2 times" in result

    async def test_edit_preserves_encoding(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "utf8.txt"
        f.write_text("你好世界", encoding="utf-8")

        tool = EditFileTool(path_policy=_permissive_policy(tmp_path))
        result = await tool._arun(path=str(f), old_text="世界", new_text="SmartClaw")

        assert "Successfully edited" in result
        assert f.read_text(encoding="utf-8") == "你好SmartClaw"


# ===================================================================
# 5. append_file — E2E
# ===================================================================


class TestAppendFileE2E:
    """E2E: append_file appends to real files."""

    async def test_append_to_existing(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "log.txt"
        f.write_text("line1\n", encoding="utf-8")

        tool = AppendFileTool(path_policy=_permissive_policy(tmp_path))
        result = await tool._arun(path=str(f), content="line2\n")

        assert "Successfully appended" in result
        assert f.read_text() == "line1\nline2\n"

    async def test_append_creates_new_file(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "new_log.txt"

        tool = AppendFileTool(path_policy=_permissive_policy(tmp_path))
        result = await tool._arun(path=str(f), content="first line\n")

        assert "Successfully appended" in result
        assert f.exists()
        assert f.read_text() == "first line\n"

    async def test_append_multiple_times(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "multi.txt"
        f.write_text("", encoding="utf-8")

        tool = AppendFileTool(path_policy=_permissive_policy(tmp_path))
        await tool._arun(path=str(f), content="a")
        await tool._arun(path=str(f), content="b")
        await tool._arun(path=str(f), content="c")

        assert f.read_text() == "abc"

    async def test_append_creates_parent_dirs(self, tmp_path: pathlib.Path) -> None:
        f = tmp_path / "x" / "y" / "z.txt"

        tool = AppendFileTool(path_policy=_permissive_policy(tmp_path))
        result = await tool._arun(path=str(f), content="deep append")

        assert "Successfully appended" in result
        assert f.read_text() == "deep append"


# ===================================================================
# 6. exec_command (shell) — E2E
# ===================================================================


class TestShellE2E:
    """E2E: exec_command runs real shell commands."""

    async def test_echo(self) -> None:
        tool = ShellTool()
        result = await tool._arun(command="echo hello_e2e")

        assert "hello_e2e" in result

    async def test_working_dir(self, tmp_path: pathlib.Path) -> None:
        tool = ShellTool()
        result = await tool._arun(command="pwd", working_dir=str(tmp_path))

        assert str(tmp_path.resolve()) in result

    async def test_exit_code_nonzero(self) -> None:
        tool = ShellTool()
        result = await tool._arun(command="exit 42")

        assert "Exit code: 42" in result

    async def test_stderr_captured(self) -> None:
        tool = ShellTool()
        result = await tool._arun(command="echo err_msg >&2")

        assert "err_msg" in result
        assert "STDERR" in result

    async def test_deny_pattern_blocks_rm_rf(self) -> None:
        tool = ShellTool()
        result = await tool._arun(command="rm -rf /")

        assert "Error" in result
        assert "blocked" in result.lower()

    async def test_deny_pattern_blocks_sudo(self) -> None:
        tool = ShellTool()
        result = await tool._arun(command="sudo ls")

        assert "Error" in result
        assert "blocked" in result.lower()

    async def test_timeout(self) -> None:
        tool = ShellTool()
        result = await tool._arun(command="sleep 30", timeout_seconds=1)

        assert "timed out" in result

    async def test_pipe_command(self) -> None:
        tool = ShellTool()
        result = await tool._arun(command="echo 'line1\nline2\nline3' | wc -l")

        assert "3" in result

    async def test_env_variable(self) -> None:
        tool = ShellTool()
        result = await tool._arun(command="echo $HOME")

        assert result.strip() != ""
        assert "Error" not in result


# ===================================================================
# 7. web_search — E2E (network required)
# ===================================================================


@pytest.mark.network
class TestWebSearchE2E:
    """E2E: web_search performs real web searches (DuckDuckGo fallback)."""

    async def test_search_returns_results(self) -> None:
        tool = WebSearchTool()
        result = await tool._arun(query="Python programming language", max_results=3)

        # With no API keys, DDG is the only fallback.
        # If DDG is reachable we get real results; otherwise the
        # "no provider" message is acceptable (network issue, not a bug).
        if "No search provider available" in result:
            pytest.skip("DuckDuckGo unreachable and no API keys configured")
        assert "Title:" in result
        assert "URL:" in result

    async def test_search_max_results_respected(self) -> None:
        tool = WebSearchTool()
        result = await tool._arun(query="OpenAI GPT", max_results=2)

        if "No search provider available" in result:
            pytest.skip("DuckDuckGo unreachable and no API keys configured")
        # Count result blocks (separated by ---)
        blocks = result.split("---")
        assert len(blocks) <= 3  # max_results=2, separators create at most 3 parts


# ===================================================================
# 8. web_fetch — E2E (network required)
# ===================================================================


@pytest.mark.network
class TestWebFetchE2E:
    """E2E: web_fetch fetches real web pages."""

    async def test_fetch_public_api(self) -> None:
        tool = WebFetchTool()
        result = await tool._arun(url="https://api.github.com/zen")

        assert "Error" not in result
        assert len(result) > 0

    async def test_fetch_html_page(self) -> None:
        tool = WebFetchTool()
        # Use a JSON API endpoint that resolves to real public IPs
        # (proxy fake-IP ranges like 198.18.0.0/15 trigger SSRF checks)
        result = await tool._arun(
            url="https://api.github.com/repos/python/cpython", max_chars=5000
        )

        assert "Error" not in result
        assert "cpython" in result.lower()

    async def test_fetch_ssrf_blocked(self) -> None:
        tool = WebFetchTool()
        result = await tool._arun(url="http://127.0.0.1:8080/secret")

        assert "Error" in result
        assert "SSRF" in result

    async def test_fetch_invalid_scheme(self) -> None:
        tool = WebFetchTool()
        result = await tool._arun(url="ftp://example.com/file")

        assert "Error" in result

    async def test_fetch_truncation(self) -> None:
        tool = WebFetchTool()
        result = await tool._arun(url="https://api.github.com/zen", max_chars=5)

        # GitHub zen returns a short phrase; with max_chars=5 it should truncate
        assert "truncated" in result


# ===================================================================
# 9. Cross-tool workflow — E2E
# ===================================================================


class TestCrossToolWorkflowE2E:
    """E2E: verify tools work together in realistic workflows."""

    async def test_write_then_read(self, tmp_path: pathlib.Path) -> None:
        """Write a file, then read it back — full round-trip."""
        policy = _permissive_policy(tmp_path)
        write_tool = WriteFileTool(path_policy=policy)
        read_tool = ReadFileTool(path_policy=policy)

        target = str(tmp_path / "roundtrip.txt")
        await write_tool._arun(path=target, content="round-trip content")
        result = await read_tool._arun(path=target)

        assert result == "round-trip content"

    async def test_write_edit_read(self, tmp_path: pathlib.Path) -> None:
        """Write → Edit → Read: verify edit modifies correctly."""
        policy = _permissive_policy(tmp_path)
        write_tool = WriteFileTool(path_policy=policy)
        edit_tool = EditFileTool(path_policy=policy)
        read_tool = ReadFileTool(path_policy=policy)

        target = str(tmp_path / "workflow.py")
        await write_tool._arun(path=target, content='version = "1.0.0"\n')
        await edit_tool._arun(path=target, old_text='"1.0.0"', new_text='"2.0.0"')
        result = await read_tool._arun(path=target)

        assert 'version = "2.0.0"' in result

    async def test_write_append_read(self, tmp_path: pathlib.Path) -> None:
        """Write → Append → Read: verify append adds content."""
        policy = _permissive_policy(tmp_path)
        write_tool = WriteFileTool(path_policy=policy)
        append_tool = AppendFileTool(path_policy=policy)
        read_tool = ReadFileTool(path_policy=policy)

        target = str(tmp_path / "log.txt")
        await write_tool._arun(path=target, content="[INFO] start\n")
        await append_tool._arun(path=target, content="[INFO] end\n")
        result = await read_tool._arun(path=target)

        assert "[INFO] start\n[INFO] end\n" == result

    async def test_shell_creates_file_then_read(self, tmp_path: pathlib.Path) -> None:
        """Shell creates a file, then read_file reads it."""
        policy = _permissive_policy(tmp_path)
        shell_tool = ShellTool()
        read_tool = ReadFileTool(path_policy=policy)

        target = tmp_path / "from_shell.txt"
        await shell_tool._arun(command=f"echo 'shell wrote this' > {target}")
        result = await read_tool._arun(path=str(target))

        assert "shell wrote this" in result

    async def test_list_after_write(self, tmp_path: pathlib.Path) -> None:
        """Write files, then list_directory shows them."""
        policy = _permissive_policy(tmp_path)
        write_tool = WriteFileTool(path_policy=policy)
        list_tool = ListDirectoryTool(path_policy=policy)

        await write_tool._arun(path=str(tmp_path / "a.txt"), content="a")
        await write_tool._arun(path=str(tmp_path / "b.txt"), content="b")
        result = await list_tool._arun(path=str(tmp_path))

        assert "[FILE] a.txt" in result
        assert "[FILE] b.txt" in result
