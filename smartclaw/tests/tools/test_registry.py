"""Unit tests for ToolRegistry."""

from __future__ import annotations

from typing import Any

import structlog
from pydantic import BaseModel

from smartclaw.tools.base import SmartClawTool
from smartclaw.tools.registry import ToolRegistry


class _Input(BaseModel):
    pass


class _FakeTool(SmartClawTool):
    name: str = "fake"
    description: str = "fake"
    args_schema: type[BaseModel] = _Input

    async def _arun(self, **kwargs: Any) -> str:
        return "ok"


def _make_tool(name: str) -> _FakeTool:
    return _FakeTool(name=name, description=f"Tool {name}")


class TestGetReturnsNone:
    """Test get returns None for missing name (Req 2.3)."""

    def test_get_missing_returns_none(self) -> None:
        reg = ToolRegistry()
        assert reg.get("nonexistent") is None


class TestDuplicateWarning:
    """Test duplicate registration logs warning (Req 2.6)."""

    def test_duplicate_logs_warning(self) -> None:
        reg = ToolRegistry()
        tool1 = _make_tool("dup")
        tool2 = _make_tool("dup")

        logged: list[dict[str, Any]] = []

        def capture(logger: Any, method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
            logged.append(event_dict.copy())
            return event_dict

        old_config = structlog.get_config()
        structlog.configure(
            processors=[capture, structlog.dev.ConsoleRenderer()],
            wrapper_class=structlog.BoundLogger,
            cache_logger_on_first_use=False,
        )
        try:
            reg.register(tool1)
            reg.register(tool2)

            assert any(
                "duplicate_tool_registration" in str(ev.get("event", ""))
                for ev in logged
            )
        finally:
            structlog.configure(**old_config)

    def test_duplicate_replaces_tool(self) -> None:
        reg = ToolRegistry()
        tool1 = _make_tool("dup")
        tool2 = _FakeTool(name="dup", description="replacement")

        reg.register(tool1)
        reg.register(tool2)

        assert reg.get("dup") is tool2
        assert reg.count == 1
