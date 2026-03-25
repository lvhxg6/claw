"""Unit tests for ShellTool."""

from __future__ import annotations

import pytest

from smartclaw.tools.shell import ShellTool


class TestDefaultTimeout:
    """Test default timeout 60s (Req 4.2)."""

    @pytest.mark.asyncio
    async def test_default_timeout_is_60(self) -> None:
        from smartclaw.tools.shell import ShellInput

        schema = ShellInput(command="echo hi")
        assert schema.timeout_seconds == 60


class TestTimeoutKillsProcess:
    """Test timeout kills process and returns partial output (Req 4.3)."""

    @pytest.mark.asyncio
    async def test_timeout_returns_error(self) -> None:
        tool = ShellTool()
        result = await tool._arun(command="sleep 10", timeout_seconds=1)
        assert "Error: Command timed out after 1s" in result


class TestWorkingDirNotFound:
    """Test working_dir not found error (Req 4.5)."""

    @pytest.mark.asyncio
    async def test_nonexistent_working_dir(self) -> None:
        tool = ShellTool()
        result = await tool._arun(
            command="echo hi",
            working_dir="/nonexistent_dir_12345",
        )
        assert "Error" in result
        assert "not found" in result.lower() or "Working directory" in result
