"""Browser Tools — LangChain Tool wrappers for browser automation.

Exposes browser actions as LangChain ``BaseTool`` instances for the
Agent Graph ReAct loop. All tools catch exceptions and return
human-readable error strings.

Reference: OpenClaw ``pw-tools-core.interactions.ts``.
"""

from __future__ import annotations

from typing import Any

import structlog
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from smartclaw.browser.actions import ActionExecutor
from smartclaw.browser.exceptions import (
    ActionTimeoutError,
    ElementNotFoundError,
    MaxPagesExceededError,
    NavigationError,
    TabNotFoundError,
)
from smartclaw.browser.page_parser import PageParser
from smartclaw.browser.screenshot import ScreenshotCapturer
from smartclaw.browser.session import SessionManager

logger = structlog.get_logger(component="tools.browser")

# ---------------------------------------------------------------------------
# Safe tool call wrapper
# ---------------------------------------------------------------------------


async def _safe_tool_call(func: Any, *args: Any, **kwargs: Any) -> str:
    """Catch exceptions and return human-readable error messages."""
    try:
        result: str = await func(*args, **kwargs)
        return result
    except TabNotFoundError as e:
        return f"Error: Tab not found - {e}"
    except ElementNotFoundError as e:
        return f"Error: Element not found - {e}. Try running get_page_snapshot first."
    except ActionTimeoutError as e:
        return f"Error: Action timed out - {e}"
    except NavigationError as e:
        return f"Error: Navigation failed - {e}"
    except MaxPagesExceededError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.error("browser_tool_error", error=str(e))
        return f"Error: {e}"


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------


class NavigateInput(BaseModel):
    url: str = Field(description="URL to navigate to")


class ClickInput(BaseModel):
    ref: str = Field(description="Element reference (e.g. 'e1')")


class TypeTextInput(BaseModel):
    ref: str = Field(description="Element reference (e.g. 'e1')")
    text: str = Field(description="Text to type")
    submit: bool = Field(default=False, description="Press Enter after typing")


class ScrollInput(BaseModel):
    ref: str = Field(description="Element reference to scroll into view")


class ScreenshotInput(BaseModel):
    full_page: bool = Field(default=False, description="Capture full page")


class WaitInput(BaseModel):
    time_ms: int | None = Field(default=None, description="Time to wait in ms")
    text: str | None = Field(default=None, description="Text to wait for")
    text_gone: str | None = Field(default=None, description="Text to wait to disappear")
    selector: str | None = Field(default=None, description="CSS selector to wait for")
    url: str | None = Field(default=None, description="URL pattern to wait for")
    load_state: str | None = Field(default=None, description="Load state to wait for")


class SelectOptionInput(BaseModel):
    ref: str = Field(description="Element reference")
    values: list[str] = Field(description="Option values to select")


class PressKeyInput(BaseModel):
    key: str = Field(description="Key name (e.g. 'Enter', 'Tab')")


class SwitchTabInput(BaseModel):
    tab_id: str = Field(description="Tab identifier")


class NewTabInput(BaseModel):
    url: str = Field(default="about:blank", description="URL for the new tab")


class CloseTabInput(BaseModel):
    tab_id: str = Field(description="Tab identifier to close")


class HoverInput(BaseModel):
    ref: str = Field(description="Element reference to hover over")


class EmptyInput(BaseModel):
    pass


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


class NavigateTool(BaseTool):
    name: str = "navigate"
    description: str = "Navigate to a URL and return the page title and URL."
    args_schema: type[BaseModel] = NavigateInput

    session: Any = None
    actions: Any = None

    async def _arun(self, url: str) -> str:
        async def _do() -> str:
            page = self.session.active_page
            if page is None:
                return "Error: No active page"
            await self.actions.navigate(page, url)
            title = await page.title()
            return f"Navigated to {page.url} — {title}"
        return await _safe_tool_call(_do)

    def _run(self, url: str) -> str:
        raise NotImplementedError("Use async")


class ClickTool(BaseTool):
    name: str = "click"
    description: str = "Click an element by its reference (e.g. 'e1')."
    args_schema: type[BaseModel] = ClickInput

    session: Any = None
    actions: Any = None

    async def _arun(self, ref: str) -> str:
        async def _do() -> str:
            page = self.session.active_page
            if page is None:
                return "Error: No active page"
            await self.actions.click(page, ref)
            return f"Clicked {ref}"
        return await _safe_tool_call(_do)

    def _run(self, ref: str) -> str:
        raise NotImplementedError("Use async")


class TypeTextTool(BaseTool):
    name: str = "type_text"
    description: str = "Type text into an element. Optionally press Enter."
    args_schema: type[BaseModel] = TypeTextInput

    session: Any = None
    actions: Any = None

    async def _arun(self, ref: str, text: str, submit: bool = False) -> str:
        async def _do() -> str:
            page = self.session.active_page
            if page is None:
                return "Error: No active page"
            await self.actions.type_text(page, ref, text, submit=submit)
            return f"Typed into {ref}"
        return await _safe_tool_call(_do)

    def _run(self, ref: str, text: str, submit: bool = False) -> str:
        raise NotImplementedError("Use async")


class ScrollTool(BaseTool):
    name: str = "scroll"
    description: str = "Scroll an element into view."
    args_schema: type[BaseModel] = ScrollInput

    session: Any = None
    actions: Any = None

    async def _arun(self, ref: str) -> str:
        async def _do() -> str:
            page = self.session.active_page
            if page is None:
                return "Error: No active page"
            await self.actions.scroll(page, ref)
            return f"Scrolled to {ref}"
        return await _safe_tool_call(_do)

    def _run(self, ref: str) -> str:
        raise NotImplementedError("Use async")


class ScreenshotTool(BaseTool):
    name: str = "screenshot"
    description: str = "Take a screenshot of the current page."
    args_schema: type[BaseModel] = ScreenshotInput

    session: Any = None
    capturer: Any = None

    async def _arun(self, full_page: bool = False) -> str:
        async def _do() -> str:
            page = self.session.active_page
            if page is None:
                return "Error: No active page"
            if full_page:
                result = await self.capturer.capture_full_page(page)
            else:
                result = await self.capturer.capture_viewport(page)
            return (
                f"Screenshot captured: {result.mime_type}, "
                f"{result.width}x{result.height}, data_length={len(result.data)}"
            )
        return await _safe_tool_call(_do)

    def _run(self, full_page: bool = False) -> str:
        raise NotImplementedError("Use async")


class GetPageSnapshotTool(BaseTool):
    name: str = "get_page_snapshot"
    description: str = "Get the Accessibility Tree snapshot of the current page."
    args_schema: type[BaseModel] = EmptyInput

    session: Any = None
    parser: Any = None
    actions: Any = None

    async def _arun(self) -> str:
        async def _do() -> str:
            page = self.session.active_page
            if page is None:
                return "Error: No active page"
            raw_tree = await page.accessibility.snapshot()
            result = self.parser.snapshot(raw_tree)
            self.actions.set_ref_map(result.refs)
            snapshot_text: str = result.snapshot
            return snapshot_text
        return await _safe_tool_call(_do)

    def _run(self) -> str:
        raise NotImplementedError("Use async")


class GoBackTool(BaseTool):
    name: str = "go_back"
    description: str = "Navigate back in browser history."
    args_schema: type[BaseModel] = EmptyInput

    session: Any = None
    actions: Any = None

    async def _arun(self) -> str:
        async def _do() -> str:
            page = self.session.active_page
            if page is None:
                return "Error: No active page"
            await self.actions.go_back(page)
            return "Navigated back"
        return await _safe_tool_call(_do)

    def _run(self) -> str:
        raise NotImplementedError("Use async")


class GoForwardTool(BaseTool):
    name: str = "go_forward"
    description: str = "Navigate forward in browser history."
    args_schema: type[BaseModel] = EmptyInput

    session: Any = None
    actions: Any = None

    async def _arun(self) -> str:
        async def _do() -> str:
            page = self.session.active_page
            if page is None:
                return "Error: No active page"
            await self.actions.go_forward(page)
            return "Navigated forward"
        return await _safe_tool_call(_do)

    def _run(self) -> str:
        raise NotImplementedError("Use async")


class WaitTool(BaseTool):
    name: str = "wait"
    description: str = "Wait for a condition (time, text, selector, URL, load state)."
    args_schema: type[BaseModel] = WaitInput

    session: Any = None
    actions: Any = None

    async def _arun(
        self,
        time_ms: int | None = None,
        text: str | None = None,
        text_gone: str | None = None,
        selector: str | None = None,
        url: str | None = None,
        load_state: str | None = None,
    ) -> str:
        async def _do() -> str:
            page = self.session.active_page
            if page is None:
                return "Error: No active page"
            await self.actions.wait(
                page,
                time_ms=time_ms,
                text=text,
                text_gone=text_gone,
                selector=selector,
                url=url,
                load_state=load_state,
            )
            return "Wait completed"
        result: str = await _safe_tool_call(_do)
        return result

    def _run(self, **kwargs: Any) -> str:
        raise NotImplementedError("Use async")


class SelectOptionTool(BaseTool):
    name: str = "select_option"
    description: str = "Select option(s) in a dropdown element."
    args_schema: type[BaseModel] = SelectOptionInput

    session: Any = None
    actions: Any = None

    async def _arun(self, ref: str, values: list[str]) -> str:
        async def _do() -> str:
            page = self.session.active_page
            if page is None:
                return "Error: No active page"
            await self.actions.select(page, ref, values)
            return f"Selected {values} in {ref}"
        return await _safe_tool_call(_do)

    def _run(self, ref: str, values: list[str]) -> str:
        raise NotImplementedError("Use async")


class PressKeyTool(BaseTool):
    name: str = "press_key"
    description: str = "Press a keyboard key."
    args_schema: type[BaseModel] = PressKeyInput

    session: Any = None
    actions: Any = None

    async def _arun(self, key: str) -> str:
        async def _do() -> str:
            page = self.session.active_page
            if page is None:
                return "Error: No active page"
            await self.actions.press_key(page, key)
            return f"Pressed {key}"
        return await _safe_tool_call(_do)

    def _run(self, key: str) -> str:
        raise NotImplementedError("Use async")


class SwitchTabTool(BaseTool):
    name: str = "switch_tab"
    description: str = "Switch to a different browser tab."
    args_schema: type[BaseModel] = SwitchTabInput

    session: Any = None

    async def _arun(self, tab_id: str) -> str:
        async def _do() -> str:
            info = await self.session.switch_tab(tab_id)
            return f"Switched to {info.tab_id}: {info.title} ({info.url})"
        return await _safe_tool_call(_do)

    def _run(self, tab_id: str) -> str:
        raise NotImplementedError("Use async")


class ListTabsTool(BaseTool):
    name: str = "list_tabs"
    description: str = "List all open browser tabs."
    args_schema: type[BaseModel] = EmptyInput

    session: Any = None

    async def _arun(self) -> str:
        async def _do() -> str:
            tabs = await self.session.list_tabs()
            if not tabs:
                return "No tabs open"
            lines = [f"- {t.tab_id}: {t.title} ({t.url})" for t in tabs]
            return "\n".join(lines)
        return await _safe_tool_call(_do)

    def _run(self) -> str:
        raise NotImplementedError("Use async")


class NewTabTool(BaseTool):
    name: str = "new_tab"
    description: str = "Open a new browser tab."
    args_schema: type[BaseModel] = NewTabInput

    session: Any = None

    async def _arun(self, url: str = "about:blank") -> str:
        async def _do() -> str:
            info = await self.session.new_tab(url)
            return f"New tab {info.tab_id}: {info.title} ({info.url})"
        return await _safe_tool_call(_do)

    def _run(self, url: str = "about:blank") -> str:
        raise NotImplementedError("Use async")


class CloseTabTool(BaseTool):
    name: str = "close_tab"
    description: str = "Close a browser tab."
    args_schema: type[BaseModel] = CloseTabInput

    session: Any = None

    async def _arun(self, tab_id: str) -> str:
        async def _do() -> str:
            await self.session.close_tab(tab_id)
            return f"Closed tab {tab_id}"
        return await _safe_tool_call(_do)

    def _run(self, tab_id: str) -> str:
        raise NotImplementedError("Use async")


class HoverTool(BaseTool):
    name: str = "hover"
    description: str = "Hover over an element."
    args_schema: type[BaseModel] = HoverInput

    session: Any = None
    actions: Any = None

    async def _arun(self, ref: str) -> str:
        async def _do() -> str:
            page = self.session.active_page
            if page is None:
                return "Error: No active page"
            await self.actions.hover(page, ref)
            return f"Hovered over {ref}"
        return await _safe_tool_call(_do)

    def _run(self, ref: str) -> str:
        raise NotImplementedError("Use async")


# ---------------------------------------------------------------------------
# get_all_browser_tools
# ---------------------------------------------------------------------------


def get_all_browser_tools(
    session: SessionManager,
    parser: PageParser,
    actions: ActionExecutor,
    capturer: ScreenshotCapturer,
) -> list[BaseTool]:
    """Return all browser LangChain Tool instances."""
    return [
        NavigateTool(session=session, actions=actions),
        ClickTool(session=session, actions=actions),
        TypeTextTool(session=session, actions=actions),
        ScrollTool(session=session, actions=actions),
        ScreenshotTool(session=session, capturer=capturer),
        GetPageSnapshotTool(session=session, parser=parser, actions=actions),
        GoBackTool(session=session, actions=actions),
        GoForwardTool(session=session, actions=actions),
        WaitTool(session=session, actions=actions),
        SelectOptionTool(session=session, actions=actions),
        PressKeyTool(session=session, actions=actions),
        SwitchTabTool(session=session),
        ListTabsTool(session=session),
        NewTabTool(session=session),
        CloseTabTool(session=session),
        HoverTool(session=session, actions=actions),
    ]
