"""Unit tests for NativeCommandTool — shell/script/exec execution, timeout,
truncation, deny patterns, working_dir, exit codes, and factory method.

All subprocess calls are mocked via AsyncMock to avoid real process execution.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from smartclaw.skills.models import ParameterDef, ToolDef
from smartclaw.skills.native_command import (
    NativeCommandTool,
    _build_args_schema,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_process(
    stdout: bytes = b"",
    stderr: bytes = b"",
    returncode: int = 0,
) -> MagicMock:
    """Create a mock asyncio subprocess process."""
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


def _make_tool(
    tool_type: str = "shell",
    command: str = "echo hello",
    command_args: list[str] | None = None,
    working_dir: str | None = None,
    timeout: int = 60,
    max_output_chars: int = 10_000,
    deny_patterns: list[str] | None = None,
    param_defs: dict[str, ParameterDef] | None = None,
) -> NativeCommandTool:
    """Create a NativeCommandTool with sensible defaults."""
    pd = param_defs or {}
    schema = _build_args_schema("test-tool", pd)
    return NativeCommandTool(
        name="test-tool",
        description="test tool",
        args_schema=schema,
        tool_type=tool_type,
        command=command,
        command_args=command_args or [],
        working_dir=working_dir,
        timeout=timeout,
        max_output_chars=max_output_chars,
        deny_patterns=deny_patterns or [],
        param_defs=pd,
    )


# ---------------------------------------------------------------------------
# Shell type happy path
# ---------------------------------------------------------------------------


class TestShellType:
    """Tests for shell type execution."""

    @pytest.mark.asyncio
    async def test_shell_happy_path(self) -> None:
        """Shell type executes command and returns stdout."""
        tool = _make_tool(tool_type="shell", command="echo hello")
        mock_proc = _make_mock_process(stdout=b"hello\n")

        with patch("smartclaw.skills.native_command.asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_shell:
            mock_shell.return_value = mock_proc
            result = await tool._arun()

        assert "hello" in result
        mock_shell.assert_called_once()

    @pytest.mark.asyncio
    async def test_shell_with_stderr(self) -> None:
        """Shell type includes stderr with STDERR: prefix."""
        tool = _make_tool(tool_type="shell", command="cmd")
        mock_proc = _make_mock_process(stdout=b"out\n", stderr=b"warn\n")

        with patch("smartclaw.skills.native_command.asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_shell:
            mock_shell.return_value = mock_proc
            result = await tool._arun()

        assert "out" in result
        assert "STDERR:" in result
        assert "warn" in result


# ---------------------------------------------------------------------------
# Script type happy path
# ---------------------------------------------------------------------------


class TestScriptType:
    """Tests for script type execution."""

    @pytest.mark.asyncio
    async def test_script_happy_path(self) -> None:
        """Script type executes command via shell with args."""
        tool = _make_tool(
            tool_type="script",
            command="./scripts/deploy.sh",
            command_args=["{env}"],
            param_defs={"env": ParameterDef(type="string", description="env")},
        )
        mock_proc = _make_mock_process(stdout=b"deployed\n")

        with patch("smartclaw.skills.native_command.asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_shell:
            mock_shell.return_value = mock_proc
            result = await tool._arun(env="staging")

        assert "deployed" in result
        # Verify the command includes args
        call_args = mock_shell.call_args
        assert "staging" in call_args[0][0]


# ---------------------------------------------------------------------------
# Exec type happy path
# ---------------------------------------------------------------------------


class TestExecType:
    """Tests for exec type execution."""

    @pytest.mark.asyncio
    async def test_exec_happy_path(self) -> None:
        """Exec type executes via create_subprocess_exec with args."""
        tool = _make_tool(
            tool_type="exec",
            command="golangci-lint",
            command_args=["run", "--config", "{config}"],
            param_defs={"config": ParameterDef(type="string", description="config path")},
        )
        mock_proc = _make_mock_process(stdout=b"lint ok\n")

        with patch("smartclaw.skills.native_command.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_proc
            result = await tool._arun(config=".golangci.yaml")

        assert "lint ok" in result
        mock_exec.assert_called_once()
        call_args = mock_exec.call_args[0]
        assert call_args[0] == "golangci-lint"
        assert "run" in call_args
        assert ".golangci.yaml" in call_args


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


class TestTimeout:
    """Tests for timeout handling."""

    @pytest.mark.asyncio
    async def test_timeout_kills_process(self) -> None:
        """When command times out, process is killed and error returned."""
        tool = _make_tool(tool_type="shell", command="sleep 100", timeout=1)

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(side_effect=TimeoutError)
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with patch("smartclaw.skills.native_command.asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_shell:
            mock_shell.return_value = mock_proc
            with patch("smartclaw.skills.native_command.asyncio.wait_for", side_effect=TimeoutError):
                result = await tool._arun()

        assert "timed out" in result
        assert "1s" in result


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


class TestTruncation:
    """Tests for output truncation."""

    @pytest.mark.asyncio
    async def test_output_truncation(self) -> None:
        """Output exceeding max_output_chars is truncated with indicator."""
        tool = _make_tool(tool_type="shell", command="cat bigfile", max_output_chars=50)
        long_output = b"x" * 200
        mock_proc = _make_mock_process(stdout=long_output)

        with patch("smartclaw.skills.native_command.asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_shell:
            mock_shell.return_value = mock_proc
            result = await tool._arun()

        assert "truncated" in result
        assert "characters omitted" in result


# ---------------------------------------------------------------------------
# Deny patterns
# ---------------------------------------------------------------------------


class TestDenyPatterns:
    """Tests for deny pattern security blocking."""

    @pytest.mark.asyncio
    async def test_deny_pattern_blocks_command(self) -> None:
        """Command matching deny pattern is blocked."""
        tool = _make_tool(
            tool_type="shell",
            command="rm -rf /",
            deny_patterns=[r"\brm\s+-rf\b"],
        )
        result = await tool._arun()
        assert "blocked by security policy" in result

    @pytest.mark.asyncio
    async def test_deny_pattern_no_match_allows(self) -> None:
        """Command not matching deny pattern is allowed."""
        tool = _make_tool(
            tool_type="shell",
            command="echo safe",
            deny_patterns=[r"\brm\s+-rf\b"],
        )
        mock_proc = _make_mock_process(stdout=b"safe\n")

        with patch("smartclaw.skills.native_command.asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_shell:
            mock_shell.return_value = mock_proc
            result = await tool._arun()

        assert "safe" in result
        assert "blocked" not in result


# ---------------------------------------------------------------------------
# Working directory
# ---------------------------------------------------------------------------


class TestWorkingDir:
    """Tests for working directory handling."""

    @pytest.mark.asyncio
    async def test_working_dir_not_found(self) -> None:
        """Non-existent working_dir returns error."""
        tool = _make_tool(
            tool_type="shell",
            command="ls",
            working_dir="/nonexistent/path/that/does/not/exist",
        )
        result = await tool._arun()
        assert "Working directory not found" in result


# ---------------------------------------------------------------------------
# Non-zero exit code
# ---------------------------------------------------------------------------


class TestExitCode:
    """Tests for non-zero exit code handling."""

    @pytest.mark.asyncio
    async def test_nonzero_exit_code_in_output(self) -> None:
        """Non-zero exit code is included in output."""
        tool = _make_tool(tool_type="shell", command="false")
        mock_proc = _make_mock_process(stdout=b"", stderr=b"error\n", returncode=1)

        with patch("smartclaw.skills.native_command.asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_shell:
            mock_shell.return_value = mock_proc
            result = await tool._arun()

        assert "Exit code: 1" in result


# ---------------------------------------------------------------------------
# Factory method
# ---------------------------------------------------------------------------


class TestFactory:
    """Tests for NativeCommandTool.from_tool_def() factory."""

    def test_factory_shell(self) -> None:
        """Factory creates tool from shell ToolDef."""
        td = ToolDef(
            name="disk-usage",
            description="Check disk usage",
            type="shell",
            command="du -sh {path}",
            parameters={"path": ParameterDef(type="string", description="dir path")},
        )
        tool = NativeCommandTool.from_tool_def(td)
        assert tool.name == "disk-usage"
        assert tool.description == "Check disk usage"
        assert tool.tool_type == "shell"
        assert "path" in tool.args_schema.model_fields

    def test_factory_script(self) -> None:
        """Factory creates tool from script ToolDef."""
        td = ToolDef(
            name="deploy",
            description="Deploy app",
            type="script",
            command="./deploy.sh",
            parameters={"env": ParameterDef(type="string", default="staging")},
        )
        tool = NativeCommandTool.from_tool_def(td)
        assert tool.name == "deploy"
        assert tool.tool_type == "script"

    def test_factory_exec(self) -> None:
        """Factory creates tool from exec ToolDef."""
        td = ToolDef(
            name="lint-go",
            description="Lint Go code",
            type="exec",
            command="golangci-lint",
            args=["run", "{target}"],
            parameters={"target": ParameterDef(type="string", default="./...")},
        )
        tool = NativeCommandTool.from_tool_def(td)
        assert tool.name == "lint-go"
        assert tool.tool_type == "exec"
        assert tool.command_args == ["run", "{target}"]

    def test_factory_unsupported_type_raises(self) -> None:
        """Factory raises ValueError for unsupported type."""
        td = ToolDef(name="bad", description="bad", type="unknown", command="cmd")
        with pytest.raises(ValueError, match="Unsupported tool type"):
            NativeCommandTool.from_tool_def(td)

    def test_factory_none_type_raises(self) -> None:
        """Factory raises ValueError for type=None (Python entry_point)."""
        td = ToolDef(name="py", description="py", type=None, function="pkg:func")
        with pytest.raises(ValueError, match="Unsupported tool type"):
            NativeCommandTool.from_tool_def(td)

    def test_factory_preserves_all_fields(self) -> None:
        """Factory preserves timeout, max_output_chars, deny_patterns, working_dir."""
        td = ToolDef(
            name="full",
            description="Full config",
            type="shell",
            command="echo {msg}",
            working_dir="/tmp",
            timeout=30,
            max_output_chars=5000,
            deny_patterns=[r"\brm\b"],
            parameters={"msg": ParameterDef(type="string", description="message")},
        )
        tool = NativeCommandTool.from_tool_def(td)
        assert tool.working_dir == "/tmp"
        assert tool.timeout == 30
        assert tool.max_output_chars == 5000
        assert tool.deny_patterns == [r"\brm\b"]
