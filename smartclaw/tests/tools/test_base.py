"""Unit tests for SmartClawTool base class."""

from __future__ import annotations

from typing import Any

import pytest
import structlog
from pydantic import BaseModel

from smartclaw.tools.base import SmartClawTool


class DummyInput(BaseModel):
    value: str = "test"


class DummyTool(SmartClawTool):
    name: str = "dummy_tool"
    description: str = "A dummy tool for testing"
    args_schema: type[BaseModel] = DummyInput

    async def _arun(self, value: str = "test", **kwargs: Any) -> str:
        return f"ok: {value}"


class TestSmartClawToolRun:
    """Test _run raises NotImplementedError (Req 1.4)."""

    def test_run_raises_not_implemented(self) -> None:
        tool = DummyTool()
        with pytest.raises(NotImplementedError, match="Use async"):
            tool._run()


class TestSmartClawToolSafeRun:
    """Test _safe_run error handling."""

    @pytest.mark.asyncio
    async def test_safe_run_returns_result_on_success(self) -> None:
        tool = DummyTool()

        async def ok_coro() -> str:
            return "hello"

        result = await tool._safe_run(ok_coro())
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_safe_run_catches_exception(self) -> None:
        tool = DummyTool()

        async def bad_coro() -> str:
            raise ValueError("boom")

        result = await tool._safe_run(bad_coro())
        assert result == "Error: boom"


class TestStructlogComponent:
    """Test structlog component name format (Req 1.5)."""

    @pytest.mark.asyncio
    async def test_error_logged_with_component_name(self) -> None:
        tool = DummyTool()
        logged_events: list[dict[str, Any]] = []

        def capture(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
            logged_events.append(event_dict.copy())
            return event_dict

        # Configure structlog to capture events
        old_config = structlog.get_config()
        structlog.configure(
            processors=[capture, structlog.dev.ConsoleRenderer()],
            wrapper_class=structlog.BoundLogger,
            cache_logger_on_first_use=False,
        )

        try:
            async def failing() -> str:
                raise RuntimeError("test error")

            await tool._safe_run(failing())

            # Check that the log event has the right component
            assert any(
                ev.get("component") == "tools.dummy_tool"
                for ev in logged_events
            )
        finally:
            structlog.configure(**old_config)
