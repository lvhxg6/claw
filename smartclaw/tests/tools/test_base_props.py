"""Property-based tests for SmartClawTool base class.

Uses hypothesis with @settings(max_examples=100).
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import BaseModel

from smartclaw.tools.base import SmartClawTool


class _DummyInput(BaseModel):
    value: str = ""


class _DummyTool(SmartClawTool):
    name: str = "test_tool"
    description: str = "test"
    args_schema: type[BaseModel] = _DummyInput

    async def _arun(self, **kwargs: Any) -> str:
        return "ok"


# ---------------------------------------------------------------------------
# Property 1: _safe_run catches all exceptions and returns formatted error string
# ---------------------------------------------------------------------------


# Feature: smartclaw-tool-system, Property 1: _safe_run error format
@given(
    error_msg=st.text(min_size=1, max_size=200).filter(lambda s: s.strip()),
    exc_type=st.sampled_from([ValueError, RuntimeError, TypeError, OSError]),
)
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_safe_run_catches_all_exceptions(error_msg: str, exc_type: type[Exception]) -> None:
    """For any exception type and error message, _safe_run wrapping a raising
    coroutine returns 'Error: {error_message}'.

    Note: KeyError is excluded because its __str__ adds quotes around the key,
    which is standard Python behavior, not a bug in _safe_run.

    **Validates: Requirements 1.2, 1.3**
    """
    tool = _DummyTool()

    async def raising_coro() -> str:
        raise exc_type(error_msg)

    result = await tool._safe_run(raising_coro())
    assert result == f"Error: {error_msg}"
