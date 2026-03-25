"""End-to-end tests for browser tools with real Playwright Chromium.

These tests launch a real headless browser, navigate to real pages,
and verify the complete tool execution path.

Mark: ``pytest.mark.browser`` — skip with ``-m 'not browser'``.

Usage:
    pytest tests/browser/test_e2e_browser_tools.py --run-browser -v
"""

from __future__ import annotations

import pytest

from smartclaw.browser.actions import ActionExecutor
from smartclaw.browser.engine import BrowserConfig, BrowserEngine
from smartclaw.browser.page_parser import PageParser
from smartclaw.browser.screenshot import ScreenshotCapturer
from smartclaw.browser.session import SessionManager
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
    SwitchTabTool,
    TypeTextTool,
    WaitTool,
    get_all_browser_tools,
)

pytestmark = pytest.mark.browser

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def browser_env():
    """Launch a real headless Chromium and yield (session, parser, actions, capturer).

    Automatically shuts down after the test.
    """
    config = BrowserConfig(headless=True, viewport_width=1280, viewport_height=720)
    engine = BrowserEngine(config)
    await engine.launch()

    session = SessionManager(engine)
    parser = PageParser()
    actions = ActionExecutor()
    capturer = ScreenshotCapturer()

    # Create an initial tab
    await session.new_tab("about:blank")

    yield session, parser, actions, capturer

    await session.cleanup()
    await engine.shutdown()


# ===================================================================
# 1. NavigateTool — E2E
# ===================================================================


class TestNavigateE2E:
    async def test_navigate_to_page(self, browser_env: tuple) -> None:
        session, parser, actions, capturer = browser_env
        tool = NavigateTool(session=session, actions=actions)

        result = await tool._arun(url="https://api.github.com/zen")
        assert "Navigated" in result
        assert "api.github.com" in result

    async def test_navigate_no_active_page(self) -> None:
        """NavigateTool returns error when no page is open."""
        config = BrowserConfig(headless=True)
        engine = BrowserEngine(config)
        await engine.launch()
        session = SessionManager(engine)
        actions = ActionExecutor()

        tool = NavigateTool(session=session, actions=actions)
        result = await tool._arun(url="https://example.com")
        assert "Error" in result

        await engine.shutdown()


# ===================================================================
# 2. ScreenshotTool — E2E
# ===================================================================


class TestScreenshotE2E:
    async def test_viewport_screenshot(self, browser_env: tuple) -> None:
        session, parser, actions, capturer = browser_env
        nav = NavigateTool(session=session, actions=actions)
        await nav._arun(url="https://api.github.com/zen")

        tool = ScreenshotTool(session=session, capturer=capturer)
        result = await tool._arun(full_page=False)

        assert "Screenshot captured" in result
        assert "1280" in result  # viewport width

    async def test_full_page_screenshot(self, browser_env: tuple) -> None:
        session, parser, actions, capturer = browser_env
        nav = NavigateTool(session=session, actions=actions)
        await nav._arun(url="https://api.github.com/zen")

        tool = ScreenshotTool(session=session, capturer=capturer)
        result = await tool._arun(full_page=True)

        assert "Screenshot captured" in result


# ===================================================================
# 3. GetPageSnapshotTool — E2E
# ===================================================================


class TestGetPageSnapshotE2E:
    async def test_snapshot_returns_content(self, browser_env: tuple) -> None:
        session, parser, actions, capturer = browser_env
        nav = NavigateTool(session=session, actions=actions)
        await nav._arun(url="https://api.github.com/zen")

        tool = GetPageSnapshotTool(session=session, parser=parser, actions=actions)
        result = await tool._arun()

        # Should return some accessibility tree content
        assert isinstance(result, str)
        assert len(result) > 0


# ===================================================================
# 4. GoBack / GoForward — E2E
# ===================================================================


class TestNavigationHistoryE2E:
    async def test_go_back_and_forward(self, browser_env: tuple) -> None:
        session, parser, actions, capturer = browser_env
        nav = NavigateTool(session=session, actions=actions)

        # Navigate to two pages
        await nav._arun(url="https://api.github.com/zen")
        await nav._arun(url="https://api.github.com/octocat")

        back_tool = GoBackTool(session=session, actions=actions)
        result = await back_tool._arun()
        assert "back" in result.lower()

        forward_tool = GoForwardTool(session=session, actions=actions)
        result = await forward_tool._arun()
        assert "forward" in result.lower()


# ===================================================================
# 5. WaitTool — E2E
# ===================================================================


class TestWaitE2E:
    async def test_wait_time(self, browser_env: tuple) -> None:
        session, parser, actions, capturer = browser_env
        tool = WaitTool(session=session, actions=actions)

        result = await tool._arun(time_ms=100)
        assert "Wait completed" in result


# ===================================================================
# 6. PressKeyTool — E2E
# ===================================================================


class TestPressKeyE2E:
    async def test_press_escape(self, browser_env: tuple) -> None:
        session, parser, actions, capturer = browser_env
        nav = NavigateTool(session=session, actions=actions)
        await nav._arun(url="https://api.github.com/zen")

        tool = PressKeyTool(session=session, actions=actions)
        result = await tool._arun(key="Escape")
        assert "Pressed" in result


# ===================================================================
# 7. Tab management — E2E
# ===================================================================


class TestTabManagementE2E:
    async def test_new_tab_and_list(self, browser_env: tuple) -> None:
        session, parser, actions, capturer = browser_env

        new_tab_tool = NewTabTool(session=session)
        result = await new_tab_tool._arun(url="about:blank")
        assert "New tab" in result

        list_tool = ListTabsTool(session=session)
        result = await list_tool._arun()
        assert "tab_" in result

    async def test_switch_tab(self, browser_env: tuple) -> None:
        session, parser, actions, capturer = browser_env

        # Create a second tab
        new_tab_tool = NewTabTool(session=session)
        await new_tab_tool._arun(url="about:blank")

        # List tabs to get IDs
        list_tool = ListTabsTool(session=session)
        tabs_result = await list_tool._arun()

        # Switch to first tab (tab_1)
        switch_tool = SwitchTabTool(session=session)
        result = await switch_tool._arun(tab_id="tab_1")
        assert "Switched" in result

    async def test_close_tab(self, browser_env: tuple) -> None:
        session, parser, actions, capturer = browser_env

        # Create a second tab
        new_tab_tool = NewTabTool(session=session)
        await new_tab_tool._arun(url="about:blank")

        close_tool = CloseTabTool(session=session)
        result = await close_tool._arun(tab_id="tab_1")
        assert "Closed" in result

    async def test_close_nonexistent_tab(self, browser_env: tuple) -> None:
        session, parser, actions, capturer = browser_env

        close_tool = CloseTabTool(session=session)
        result = await close_tool._arun(tab_id="tab_999")
        assert "Error" in result


# ===================================================================
# 8. get_all_browser_tools — E2E
# ===================================================================


class TestGetAllBrowserToolsE2E:
    async def test_all_tools_created(self, browser_env: tuple) -> None:
        session, parser, actions, capturer = browser_env
        tools = get_all_browser_tools(session, parser, actions, capturer)

        assert len(tools) == 16
        names = {t.name for t in tools}
        expected = {
            "navigate", "click", "type_text", "scroll", "screenshot",
            "get_page_snapshot", "go_back", "go_forward", "wait",
            "select_option", "press_key", "switch_tab", "list_tabs",
            "new_tab", "close_tab", "hover",
        }
        assert names == expected


# ===================================================================
# 9. Cross-tool workflow — E2E
# ===================================================================


class TestBrowserWorkflowE2E:
    async def test_navigate_snapshot_screenshot(self, browser_env: tuple) -> None:
        """Full workflow: navigate → snapshot → screenshot."""
        session, parser, actions, capturer = browser_env

        nav = NavigateTool(session=session, actions=actions)
        result = await nav._arun(url="https://api.github.com/zen")
        assert "Navigated" in result

        snap = GetPageSnapshotTool(session=session, parser=parser, actions=actions)
        snap_result = await snap._arun()
        assert isinstance(snap_result, str)

        shot = ScreenshotTool(session=session, capturer=capturer)
        shot_result = await shot._arun(full_page=False)
        assert "Screenshot captured" in shot_result

    async def test_multi_tab_workflow(self, browser_env: tuple) -> None:
        """Open multiple tabs, switch between them, close one."""
        session, parser, actions, capturer = browser_env

        nav = NavigateTool(session=session, actions=actions)
        await nav._arun(url="https://api.github.com/zen")

        new_tab = NewTabTool(session=session)
        await new_tab._arun(url="https://api.github.com/octocat")

        list_tabs = ListTabsTool(session=session)
        result = await list_tabs._arun()
        assert "tab_1" in result
        assert "tab_2" in result

        switch = SwitchTabTool(session=session)
        await switch._arun(tab_id="tab_1")
        assert session.active_tab_id == "tab_1"

        close = CloseTabTool(session=session)
        await close._arun(tab_id="tab_2")

        result = await list_tabs._arun()
        assert "tab_2" not in result
