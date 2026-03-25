"""Unit tests for Browser Tools.

Covers Requirements 7.1–7.14, 7.16.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from smartclaw.browser.actions import ActionExecutor
from smartclaw.browser.page_parser import PageParser
from smartclaw.browser.screenshot import ScreenshotCapturer
from smartclaw.browser.session import SessionManager, TabInfo
from smartclaw.tools.browser_tools import (
    ClickTool,
    CloseTabTool,
    GetPageSnapshotTool,
    GoBackTool,
    GoForwardTool,
    HoverTool,
    ListTabsTool,
    NavigateTool,
    NewTabTool,
    PressKeyTool,
    ScreenshotTool,
    ScrollTool,
    SelectOptionTool,
    SwitchTabTool,
    TypeTextTool,
    WaitTool,
    get_all_browser_tools,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mocks():
    """Return mock session, parser, actions, capturer."""
    mock_page = AsyncMock()
    mock_page.title = AsyncMock(return_value="Test Page")
    mock_page.url = "https://example.com"
    mock_page.accessibility = MagicMock()
    mock_page.accessibility.snapshot = AsyncMock(return_value=None)

    mock_session = MagicMock(spec=SessionManager)
    mock_session.active_page = mock_page
    mock_session.list_tabs = AsyncMock(return_value=[
        TabInfo(tab_id="tab_1", title="Page 1", url="https://a.com"),
    ])
    mock_session.switch_tab = AsyncMock(
        return_value=TabInfo(tab_id="tab_1", title="Page 1", url="https://a.com")
    )
    mock_session.new_tab = AsyncMock(
        return_value=TabInfo(tab_id="tab_2", title="New", url="about:blank")
    )
    mock_session.close_tab = AsyncMock()

    mock_parser = MagicMock(spec=PageParser)
    mock_parser.snapshot = MagicMock(
        return_value=MagicMock(snapshot="(empty)", refs={})
    )

    mock_actions = MagicMock(spec=ActionExecutor)
    mock_actions.navigate = AsyncMock()
    mock_actions.click = AsyncMock()
    mock_actions.type_text = AsyncMock()
    mock_actions.scroll = AsyncMock()
    mock_actions.go_back = AsyncMock()
    mock_actions.go_forward = AsyncMock()
    mock_actions.wait = AsyncMock()
    mock_actions.select = AsyncMock()
    mock_actions.press_key = AsyncMock()
    mock_actions.hover = AsyncMock()
    mock_actions.set_ref_map = MagicMock()

    mock_capturer = MagicMock(spec=ScreenshotCapturer)
    mock_capturer.capture_viewport = AsyncMock(
        return_value=MagicMock(mime_type="image/png", width=1280, height=720, data="abc")
    )
    mock_capturer.capture_full_page = AsyncMock(
        return_value=MagicMock(mime_type="image/png", width=1280, height=720, data="abc")
    )

    return mock_session, mock_parser, mock_actions, mock_capturer


# ---------------------------------------------------------------------------
# get_all_browser_tools returns correct count (Requirement 7.16)
# ---------------------------------------------------------------------------


def test_get_all_browser_tools_count():
    """get_all_browser_tools returns at least 14 tools."""
    session, parser, actions, capturer = _make_mocks()
    tools = get_all_browser_tools(session, parser, actions, capturer)

    assert len(tools) >= 14
    names = {t.name for t in tools}
    expected = {
        "navigate", "click", "type_text", "scroll", "screenshot",
        "get_page_snapshot", "go_back", "go_forward", "wait",
        "select_option", "press_key", "switch_tab", "list_tabs",
        "new_tab", "close_tab",
    }
    assert expected.issubset(names)


# ---------------------------------------------------------------------------
# Individual tool tests (Requirements 7.1–7.14)
# ---------------------------------------------------------------------------


async def test_navigate_tool():
    """navigate tool calls actions.navigate and returns result."""
    session, parser, actions, capturer = _make_mocks()
    tool = NavigateTool(session=session, actions=actions)
    result = await tool._arun(url="https://example.com")
    assert "Navigated" in result


async def test_click_tool():
    """click tool calls actions.click."""
    session, parser, actions, capturer = _make_mocks()
    tool = ClickTool(session=session, actions=actions)
    result = await tool._arun(ref="e1")
    assert "Clicked" in result


async def test_type_text_tool():
    """type_text tool calls actions.type_text."""
    session, parser, actions, capturer = _make_mocks()
    tool = TypeTextTool(session=session, actions=actions)
    result = await tool._arun(ref="e1", text="hello")
    assert "Typed" in result


async def test_scroll_tool():
    """scroll tool calls actions.scroll."""
    session, parser, actions, capturer = _make_mocks()
    tool = ScrollTool(session=session, actions=actions)
    result = await tool._arun(ref="e1")
    assert "Scrolled" in result


async def test_screenshot_tool():
    """screenshot tool captures viewport."""
    session, parser, actions, capturer = _make_mocks()
    tool = ScreenshotTool(session=session, capturer=capturer)
    result = await tool._arun(full_page=False)
    assert "Screenshot" in result


async def test_get_page_snapshot_tool():
    """get_page_snapshot tool returns snapshot text."""
    session, parser, actions, capturer = _make_mocks()
    tool = GetPageSnapshotTool(session=session, parser=parser, actions=actions)
    result = await tool._arun()
    assert "(empty)" in result


async def test_go_back_tool():
    """go_back tool calls actions.go_back."""
    session, parser, actions, capturer = _make_mocks()
    tool = GoBackTool(session=session, actions=actions)
    result = await tool._arun()
    assert "back" in result.lower()


async def test_go_forward_tool():
    """go_forward tool calls actions.go_forward."""
    session, parser, actions, capturer = _make_mocks()
    tool = GoForwardTool(session=session, actions=actions)
    result = await tool._arun()
    assert "forward" in result.lower()


async def test_wait_tool():
    """wait tool calls actions.wait."""
    session, parser, actions, capturer = _make_mocks()
    tool = WaitTool(session=session, actions=actions)
    result = await tool._arun(time_ms=100)
    assert "Wait" in result


async def test_select_option_tool():
    """select_option tool calls actions.select."""
    session, parser, actions, capturer = _make_mocks()
    tool = SelectOptionTool(session=session, actions=actions)
    result = await tool._arun(ref="e1", values=["US"])
    assert "Selected" in result


async def test_press_key_tool():
    """press_key tool calls actions.press_key."""
    session, parser, actions, capturer = _make_mocks()
    tool = PressKeyTool(session=session, actions=actions)
    result = await tool._arun(key="Enter")
    assert "Pressed" in result


async def test_switch_tab_tool():
    """switch_tab tool calls session.switch_tab."""
    session, parser, actions, capturer = _make_mocks()
    tool = SwitchTabTool(session=session)
    result = await tool._arun(tab_id="tab_1")
    assert "Switched" in result


async def test_list_tabs_tool():
    """list_tabs tool returns tab list."""
    session, parser, actions, capturer = _make_mocks()
    tool = ListTabsTool(session=session)
    result = await tool._arun()
    assert "tab_1" in result


async def test_new_tab_tool():
    """new_tab tool calls session.new_tab."""
    session, parser, actions, capturer = _make_mocks()
    tool = NewTabTool(session=session)
    result = await tool._arun(url="https://example.com")
    assert "New tab" in result


async def test_close_tab_tool():
    """close_tab tool calls session.close_tab."""
    session, parser, actions, capturer = _make_mocks()
    tool = CloseTabTool(session=session)
    result = await tool._arun(tab_id="tab_1")
    assert "Closed" in result


async def test_hover_tool():
    """hover tool calls actions.hover."""
    session, parser, actions, capturer = _make_mocks()
    tool = HoverTool(session=session, actions=actions)
    result = await tool._arun(ref="e1")
    assert "Hovered" in result


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


async def test_tool_returns_error_on_exception():
    """Tools return error strings instead of raising."""
    session, parser, actions, capturer = _make_mocks()
    actions.click = AsyncMock(side_effect=Exception("element detached"))
    tool = ClickTool(session=session, actions=actions)
    result = await tool._arun(ref="e1")
    assert "Error:" in result
