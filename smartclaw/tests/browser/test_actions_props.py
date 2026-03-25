"""Property-based tests for ActionExecutor.

Covers Properties 8 and 9 from the design document.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from smartclaw.browser.actions import _clamp_timeout
from smartclaw.browser.exceptions import ElementNotFoundError
from smartclaw.browser.actions import ActionExecutor

# ---------------------------------------------------------------------------
# Feature: smartclaw-browser-engine, Property 9: Timeout clamping bounds
# ---------------------------------------------------------------------------
# **Validates: Requirements 4.12**


@settings(max_examples=100)
@given(timeout=st.integers(-100000, 200000))
def test_clamp_timeout_bounds(timeout: int) -> None:
    """_clamp_timeout always returns a value in [500, 60000].

    Below 500 → 500, above 60000 → 60000, within range → preserved.
    """
    result = _clamp_timeout(timeout)
    assert 500 <= result <= 60000

    if timeout < 500:
        assert result == 500
    elif timeout > 60000:
        assert result == 60000
    else:
        assert result == timeout


@settings(max_examples=100)
@given(default=st.integers(0, 100000))
def test_clamp_timeout_none_uses_default(default: int) -> None:
    """_clamp_timeout(None, default) uses the default, also clamped."""
    result = _clamp_timeout(None, default)
    assert 500 <= result <= 60000


# ---------------------------------------------------------------------------
# Feature: smartclaw-browser-engine, Property 8: Action error messages include element reference
# ---------------------------------------------------------------------------
# **Validates: Requirements 4.11**


@settings(max_examples=100)
@given(ref=st.from_regex(r"e\d+", fullmatch=True))
def test_action_error_includes_ref(ref: str) -> None:
    """For any eN ref not in the ref_map, the error message contains the ref."""
    executor = ActionExecutor(ref_map={})

    mock_page = MagicMock()

    with pytest.raises(ElementNotFoundError) as exc_info:
        executor._resolve_locator(mock_page, ref)

    assert ref in str(exc_info.value)
    assert exc_info.value.ref == ref
