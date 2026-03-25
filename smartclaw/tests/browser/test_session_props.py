"""Property-based tests for SessionManager.

Covers Properties 11, 12, 13, 14, 16 from the design document.
"""

from __future__ import annotations

from collections import deque
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from smartclaw.browser.engine import BrowserConfig, BrowserEngine
from smartclaw.browser.exceptions import MaxPagesExceededError, TabNotFoundError
from smartclaw.browser.session import (
    ConsoleEntry,
    ErrorEntry,
    NetworkEntry,
    SessionManager,
    TabState,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_engine(max_pages: int = 10) -> tuple[MagicMock, MagicMock]:
    """Return (mock_engine, mock_context) wired together."""
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.title = AsyncMock(return_value="Test Page")
    mock_page.url = "about:blank"
    mock_page.close = AsyncMock()
    mock_page.bring_to_front = AsyncMock()
    mock_page.on = MagicMock()

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    mock_engine = MagicMock(spec=BrowserEngine)
    mock_engine.config = BrowserConfig(max_pages=max_pages)
    mock_engine.context = mock_context

    return mock_engine, mock_context


def _make_fresh_mock_page() -> AsyncMock:
    """Return a fresh mock page for each new_page call."""
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.title = AsyncMock(return_value="Test Page")
    mock_page.url = "about:blank"
    mock_page.close = AsyncMock()
    mock_page.bring_to_front = AsyncMock()
    mock_page.on = MagicMock()
    return mock_page


# ---------------------------------------------------------------------------
# Feature: smartclaw-browser-engine, Property 11: Tab registry consistency
# ---------------------------------------------------------------------------
# **Validates: Requirements 6.2, 6.4, 6.7**


@settings(max_examples=100)
@given(ops=st.lists(st.sampled_from(["new", "close"]), min_size=1, max_size=20))
@pytest.mark.asyncio
async def test_tab_registry_consistency(ops: list[str]) -> None:
    """For any sequence of new_tab/close_tab, list_tabs returns exactly
    created-but-not-closed tabs; active_page corresponds to a tab in the
    list or is None.
    """
    mock_engine, mock_context = _make_mock_engine(max_pages=50)
    mock_context.new_page = AsyncMock(side_effect=lambda: _make_fresh_mock_page())

    session = SessionManager(mock_engine)
    created_tabs: list[str] = []

    for op in ops:
        if op == "new":
            try:
                tab_info = await session.new_tab()
                created_tabs.append(tab_info.tab_id)
            except MaxPagesExceededError:
                pass
        elif op == "close" and created_tabs:
            tab_id = created_tabs.pop(0)
            try:
                await session.close_tab(tab_id)
            except TabNotFoundError:
                pass

    tabs = await session.list_tabs()
    tab_ids = {t.tab_id for t in tabs}

    # All created-but-not-closed tabs should be in the list
    assert tab_ids == set(created_tabs)

    # active_page corresponds to a tab in the list or is None
    if session.active_tab_id is not None:
        assert session.active_tab_id in tab_ids
    if not tab_ids:
        assert session.active_page is None


# ---------------------------------------------------------------------------
# Feature: smartclaw-browser-engine, Property 12: Tab switching sets active tab
# ---------------------------------------------------------------------------
# **Validates: Requirements 6.3**


@settings(max_examples=100)
@given(num_tabs=st.integers(2, 10), switch_idx=st.integers(0, 9))
@pytest.mark.asyncio
async def test_tab_switching_sets_active(num_tabs: int, switch_idx: int) -> None:
    """After switch_tab(tab_id), active_tab_id equals that tab_id."""
    assume(switch_idx < num_tabs)

    mock_engine, mock_context = _make_mock_engine(max_pages=50)
    mock_context.new_page = AsyncMock(side_effect=lambda: _make_fresh_mock_page())

    session = SessionManager(mock_engine)
    tab_ids: list[str] = []

    for _ in range(num_tabs):
        info = await session.new_tab()
        tab_ids.append(info.tab_id)

    target = tab_ids[switch_idx]
    await session.switch_tab(target)

    assert session.active_tab_id == target


# ---------------------------------------------------------------------------
# Feature: smartclaw-browser-engine, Property 13: Invalid tab identifier raises TabNotFoundError
# ---------------------------------------------------------------------------
# **Validates: Requirements 6.5**


@settings(max_examples=100)
@given(invalid_id=st.text(min_size=1).filter(lambda s: not s.startswith("tab_")))
@pytest.mark.asyncio
async def test_invalid_tab_raises_error(invalid_id: str) -> None:
    """Any string not in the registry raises TabNotFoundError with the identifier."""
    mock_engine, _ = _make_mock_engine()
    session = SessionManager(mock_engine)

    with pytest.raises(TabNotFoundError) as exc_info:
        await session.switch_tab(invalid_id)

    assert invalid_id in str(exc_info.value)

    with pytest.raises(TabNotFoundError) as exc_info2:
        await session.close_tab(invalid_id)

    assert invalid_id in str(exc_info2.value)


# ---------------------------------------------------------------------------
# Feature: smartclaw-browser-engine, Property 14: Event buffer respects size limits
# ---------------------------------------------------------------------------
# **Validates: Requirements 6.8**


@settings(max_examples=100)
@given(count=st.integers(1, 2000))
def test_event_buffer_limits(count: int) -> None:
    """For N > limit, deque contains at most the limit (most recent entries)."""
    mock_page = MagicMock()

    state = TabState(page=mock_page)

    for i in range(count):
        state.console_messages.append(
            ConsoleEntry(type="log", text=f"msg_{i}", timestamp="")
        )
        state.page_errors.append(
            ErrorEntry(message=f"err_{i}", timestamp="")
        )
        state.network_requests.append(
            NetworkEntry(
                request_id=str(i), timestamp="", method="GET", url=f"http://x/{i}"
            )
        )

    assert len(state.console_messages) <= 500
    assert len(state.page_errors) <= 200
    assert len(state.network_requests) <= 500

    # Most recent entries are preserved
    if count > 500:
        assert state.console_messages[-1].text == f"msg_{count - 1}"
    if count > 200:
        assert state.page_errors[-1].message == f"err_{count - 1}"
    if count > 500:
        assert state.network_requests[-1].url == f"http://x/{count - 1}"


# ---------------------------------------------------------------------------
# Feature: smartclaw-browser-engine, Property 16: Max concurrent pages enforcement
# ---------------------------------------------------------------------------
# **Validates: Requirements 8.6**


@settings(max_examples=100)
@given(max_pages=st.integers(1, 20))
@pytest.mark.asyncio
async def test_max_concurrent_pages(max_pages: int) -> None:
    """With max_pages=N, after creating N tabs, tab N+1 is rejected."""
    mock_engine, mock_context = _make_mock_engine(max_pages=max_pages)
    mock_context.new_page = AsyncMock(side_effect=lambda: _make_fresh_mock_page())

    session = SessionManager(mock_engine)

    for _ in range(max_pages):
        await session.new_tab()

    with pytest.raises(MaxPagesExceededError):
        await session.new_tab()
