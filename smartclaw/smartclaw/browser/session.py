"""Session Manager — Multi-tab browser session management.

Provides ``SessionManager`` for creating, switching, closing tabs,
and tracking per-tab events (console, errors, network).

Reference: OpenClaw ``pw-session.ts``.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

from smartclaw.browser.exceptions import MaxPagesExceededError, TabNotFoundError
from smartclaw.browser.page_parser import RoleRefMap

if TYPE_CHECKING:
    from playwright.async_api import Page

    from smartclaw.browser.engine import BrowserEngine

logger = structlog.get_logger(component="browser.session")

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class TabInfo:
    """Tab metadata (public)."""

    tab_id: str
    title: str
    url: str


@dataclass
class ConsoleEntry:
    """Console message."""

    type: str  # "log", "warning", "error", ...
    text: str
    timestamp: str  # ISO 8601


@dataclass
class ErrorEntry:
    """Page error."""

    message: str
    name: str | None = None
    stack: str | None = None
    timestamp: str = ""


@dataclass
class NetworkEntry:
    """Network request record."""

    request_id: str
    timestamp: str
    method: str
    url: str
    resource_type: str | None = None
    status: int | None = None
    ok: bool | None = None
    failure_text: str | None = None


@dataclass
class TabState:
    """Per-tab internal state (event buffers + ref mapping)."""

    page: Page
    console_messages: deque[ConsoleEntry] = field(
        default_factory=lambda: deque(maxlen=500)
    )
    page_errors: deque[ErrorEntry] = field(
        default_factory=lambda: deque(maxlen=200)
    )
    network_requests: deque[NetworkEntry] = field(
        default_factory=lambda: deque(maxlen=500)
    )
    ref_map: RoleRefMap = field(default_factory=dict)


# ---------------------------------------------------------------------------
# SessionManager
# ---------------------------------------------------------------------------


class SessionManager:
    """Browser session and tab manager.

    Supports the async context manager protocol for automatic cleanup.
    """

    def __init__(self, engine: BrowserEngine) -> None:
        self._engine = engine
        self._tabs: dict[str, TabState] = {}
        self._active_tab_id: str | None = None
        self._tab_counter: int = 0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def active_tab_id(self) -> str | None:
        """Currently active tab identifier."""
        return self._active_tab_id

    @property
    def active_page(self) -> Page | None:
        """Playwright Page for the active tab, or None."""
        if self._active_tab_id is None:
            return None
        state = self._tabs.get(self._active_tab_id)
        return state.page if state else None

    # ------------------------------------------------------------------
    # Tab operations
    # ------------------------------------------------------------------

    async def new_tab(self, url: str = "about:blank") -> TabInfo:
        """Create a new tab, navigate to *url*, and set it as active.

        Raises:
            MaxPagesExceededError: If the max_pages limit is reached.
        """
        max_pages = self._engine.config.max_pages
        if len(self._tabs) >= max_pages:
            raise MaxPagesExceededError(current=len(self._tabs), limit=max_pages)

        context = self._engine.context
        if context is None:
            msg = "No browser context available"
            raise RuntimeError(msg)

        page: Page = await context.new_page()
        await page.goto(url)

        self._tab_counter += 1
        tab_id = f"tab_{self._tab_counter}"

        state = TabState(page=page)
        self._tabs[tab_id] = state
        self._active_tab_id = tab_id

        # Attach event listeners
        self._attach_listeners(tab_id, page)

        title = await page.title()
        log = logger.bind(tab_id=tab_id, url=url)
        log.info("tab_created")

        return TabInfo(tab_id=tab_id, title=title, url=page.url)

    async def list_tabs(self) -> list[TabInfo]:
        """Return metadata for all open tabs."""
        result: list[TabInfo] = []
        for tab_id, state in self._tabs.items():
            title = await state.page.title()
            result.append(TabInfo(tab_id=tab_id, title=title, url=state.page.url))
        return result

    async def switch_tab(self, tab_id: str) -> TabInfo:
        """Switch to the tab identified by *tab_id*.

        Raises:
            TabNotFoundError: If *tab_id* is not in the registry.
        """
        if tab_id not in self._tabs:
            raise TabNotFoundError(tab_id=tab_id)

        self._active_tab_id = tab_id
        state = self._tabs[tab_id]
        await state.page.bring_to_front()

        title = await state.page.title()
        log = logger.bind(tab_id=tab_id)
        log.info("tab_switched")

        return TabInfo(tab_id=tab_id, title=title, url=state.page.url)

    async def close_tab(self, tab_id: str) -> None:
        """Close the tab identified by *tab_id*.

        Raises:
            TabNotFoundError: If *tab_id* is not in the registry.
        """
        if tab_id not in self._tabs:
            raise TabNotFoundError(tab_id=tab_id)

        state = self._tabs.pop(tab_id)
        await state.page.close()

        log = logger.bind(tab_id=tab_id)
        log.info("tab_closed")

        # Update active tab
        if self._active_tab_id == tab_id:
            if self._tabs:
                self._active_tab_id = next(iter(self._tabs))
            else:
                self._active_tab_id = None

    async def cleanup(self) -> None:
        """Close all tabs and clear internal state."""
        log = logger.bind(tab_count=len(self._tabs))
        log.info("session_cleanup_start")

        for tab_id, state in list(self._tabs.items()):
            try:
                await state.page.close()
            except Exception as exc:
                logger.warning("tab_close_failed", tab_id=tab_id, error=str(exc))

        self._tabs.clear()
        self._active_tab_id = None
        log.info("session_cleanup_complete")

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> SessionManager:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.cleanup()

    # ------------------------------------------------------------------
    # Event listeners
    # ------------------------------------------------------------------

    def _attach_listeners(self, tab_id: str, page: Page) -> None:
        """Attach console/error/network event listeners to *page*."""
        state = self._tabs[tab_id]

        def on_console(msg: object) -> None:
            entry = ConsoleEntry(
                type=getattr(msg, "type", "log"),
                text=str(getattr(msg, "text", str(msg))),
                timestamp=datetime.now(tz=UTC).isoformat(),
            )
            state.console_messages.append(entry)

        def on_page_error(error: object) -> None:
            entry = ErrorEntry(
                message=str(error),
                timestamp=datetime.now(tz=UTC).isoformat(),
            )
            state.page_errors.append(entry)

        def on_request(request: object) -> None:
            entry = NetworkEntry(
                request_id=str(id(request)),
                timestamp=datetime.now(tz=UTC).isoformat(),
                method=getattr(request, "method", "GET"),
                url=str(getattr(request, "url", "")),
                resource_type=getattr(request, "resource_type", None),
            )
            state.network_requests.append(entry)

        page.on("console", on_console)
        page.on("pageerror", on_page_error)
        page.on("request", on_request)
