"""Property-based tests for Browser Tools.

Covers Property 15 from the design document.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from smartclaw.browser.exceptions import (
    ActionTimeoutError,
    ElementNotFoundError,
    MaxPagesExceededError,
    NavigationError,
    TabNotFoundError,
)
from smartclaw.tools.browser_tools import _safe_tool_call

# ---------------------------------------------------------------------------
# Feature: smartclaw-browser-engine, Property 15: Browser tools catch exceptions and return error strings
# ---------------------------------------------------------------------------
# **Validates: Requirements 7.15**

EXCEPTION_TYPES = [
    TabNotFoundError,
    ElementNotFoundError,
    NavigationError,
    MaxPagesExceededError,
    RuntimeError,
    ValueError,
    TypeError,
]


def _make_exception(exc_type: type, msg: str) -> Exception:
    """Construct an exception instance for the given type."""
    if exc_type is TabNotFoundError:
        return TabNotFoundError(tab_id=msg)
    if exc_type is ElementNotFoundError:
        return ElementNotFoundError(ref=msg)
    if exc_type is NavigationError:
        return NavigationError(url=msg)
    if exc_type is MaxPagesExceededError:
        return MaxPagesExceededError(current=5, limit=10)
    if exc_type is ActionTimeoutError:
        return ActionTimeoutError(action="click", ref_or_selector=msg, timeout_ms=8000)
    return exc_type(msg)


@settings(max_examples=100)
@given(
    exc_type=st.sampled_from(EXCEPTION_TYPES),
    msg=st.text(min_size=1, max_size=50),
)
@pytest.mark.asyncio
async def test_safe_tool_call_catches_exceptions(exc_type: type, msg: str) -> None:
    """For any tool invocation that raises an exception, _safe_tool_call
    returns a string error message instead of propagating.
    """
    exc = _make_exception(exc_type, msg)

    async def failing_func() -> str:
        raise exc

    result = await _safe_tool_call(failing_func)

    assert isinstance(result, str)
    assert result.startswith("Error:")
