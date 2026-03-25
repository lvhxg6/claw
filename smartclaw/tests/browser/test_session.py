"""Unit tests for SessionManager.

Covers Requirements 6.1, 6.6, 8.3.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from smartclaw.browser.engine import BrowserConfig, BrowserEngine
from smartclaw.browser.exceptions import MaxPagesExceededError, TabNotFoundError
from smartclaw.browser.session import SessionManager, TabInfo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_engine(max_pages: int = 10) -> tuple[MagicMock, AsyncMock]:
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.title = AsyncMock(return_value="Test Page")
    mock_page.url = "https://example.com"
    mock_page.close = AsyncMock()
    mock_page.bring_to_front = AsyncMock()
    mock_page.on = MagicMock()

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    mock_engine = MagicMock(spec=BrowserEngine)
    mock_engine.config = BrowserConfig(max_pages=max_pages)
    mock_engine.context = mock_context

    return mock_engine, mock_page


# ---------------------------------------------------------------------------
# New tab creation (Requirement 6.1)
# ---------------------------------------------------------------------------


async def test_new_tab():
    """new_tab creates a page, navigates, and returns TabInfo."""
    engine, page = _make_mock_engine()
    session = SessionManager(engine)

    info = await session.new_tab("https://example.com")

    assert isinstance(info, TabInfo)
    assert info.tab_id == "tab_1"
    assert info.title == "Test Page"
    assert session.active_tab_id == "tab_1"
    assert session.active_page is page
    page.goto.assert_awaited_once_with("https://example.com")


async def test_new_tab_multiple():
    """Creating multiple tabs increments tab_id."""
    engine, _ = _make_mock_engine()
    session = SessionManager(engine)

    t1 = await session.new_tab()
    t2 = await session.new_tab()

    assert t1.tab_id == "tab_1"
    assert t2.tab_id == "tab_2"
    assert session.active_tab_id == "tab_2"


async def test_new_tab_exceeds_limit():
    """new_tab raises MaxPagesExceededError when limit reached."""
    engine, _ = _make_mock_engine(max_pages=1)
    session = SessionManager(engine)

    await session.new_tab()

    with pytest.raises(MaxPagesExceededError):
        await session.new_tab()


# ---------------------------------------------------------------------------
# Session cleanup (Requirement 6.6)
# ---------------------------------------------------------------------------


async def test_cleanup():
    """cleanup closes all tabs and clears state."""
    engine, page = _make_mock_engine()
    session = SessionManager(engine)

    await session.new_tab()
    await session.new_tab()

    await session.cleanup()

    assert session.active_tab_id is None
    assert session.active_page is None
    tabs = await session.list_tabs()
    assert len(tabs) == 0


# ---------------------------------------------------------------------------
# Context manager (Requirement 8.3)
# ---------------------------------------------------------------------------


async def test_context_manager():
    """async with SessionManager calls cleanup on exit."""
    engine, page = _make_mock_engine()

    async with SessionManager(engine) as session:
        await session.new_tab()
        assert session.active_tab_id is not None

    # After exit, cleanup should have been called
    assert session.active_tab_id is None


async def test_context_manager_cleanup_on_exception():
    """Context manager cleans up even when body raises."""
    engine, page = _make_mock_engine()

    with pytest.raises(ValueError, match="boom"):
        async with SessionManager(engine) as session:
            await session.new_tab()
            raise ValueError("boom")

    assert session.active_tab_id is None


# ---------------------------------------------------------------------------
# Tab operations
# ---------------------------------------------------------------------------


async def test_list_tabs():
    """list_tabs returns all open tabs."""
    engine, _ = _make_mock_engine()
    session = SessionManager(engine)

    await session.new_tab()
    await session.new_tab()

    tabs = await session.list_tabs()
    assert len(tabs) == 2


async def test_switch_tab():
    """switch_tab changes the active tab."""
    engine, _ = _make_mock_engine()
    session = SessionManager(engine)

    t1 = await session.new_tab()
    await session.new_tab()

    await session.switch_tab(t1.tab_id)
    assert session.active_tab_id == t1.tab_id


async def test_close_tab():
    """close_tab removes the tab and updates active."""
    engine, page = _make_mock_engine()
    session = SessionManager(engine)

    t1 = await session.new_tab()
    t2 = await session.new_tab()

    await session.close_tab(t2.tab_id)

    tabs = await session.list_tabs()
    assert len(tabs) == 1
    assert session.active_tab_id == t1.tab_id


async def test_close_tab_invalid_raises():
    """close_tab raises TabNotFoundError for unknown tab_id."""
    engine, _ = _make_mock_engine()
    session = SessionManager(engine)

    with pytest.raises(TabNotFoundError):
        await session.close_tab("nonexistent")
