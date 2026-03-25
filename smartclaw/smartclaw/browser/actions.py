"""Action Executor — Browser interaction actions.

Provides ``_clamp_timeout`` for timeout normalization and ``ActionExecutor``
for performing browser interactions (click, type, scroll, navigate, etc.)
using Element Reference resolution via ``RoleRefMap``.

Reference: OpenClaw ``pw-tools-core.interactions.ts``.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from smartclaw.browser.exceptions import (
    ActionTimeoutError,
    ElementNotFoundError,
    NavigationError,
)
from smartclaw.browser.page_parser import INTERACTIVE_ROLES, RoleRefMap

if TYPE_CHECKING:
    from playwright.async_api import Locator, Page

logger = structlog.get_logger(component="browser.actions")

# ---------------------------------------------------------------------------
# Timeout clamping
# ---------------------------------------------------------------------------

_MIN_TIMEOUT_MS = 500
_MAX_TIMEOUT_MS = 60_000


def _clamp_timeout(timeout_ms: int | None, default: int = 8000) -> int:
    """Clamp *timeout_ms* to ``[500, 60000]``.

    If *timeout_ms* is ``None``, *default* is used (also clamped).
    """
    value = default if timeout_ms is None else timeout_ms
    return max(_MIN_TIMEOUT_MS, min(_MAX_TIMEOUT_MS, value))


# ---------------------------------------------------------------------------
# ActionExecutor
# ---------------------------------------------------------------------------


class ActionExecutor:
    """Browser interaction action executor.

    All actions resolve Element References via the current ``RoleRefMap``
    to Playwright locators using ``page.get_by_role`` + ``nth``.
    """

    def __init__(self, ref_map: RoleRefMap | None = None) -> None:
        self._ref_map: RoleRefMap = ref_map or {}

    def set_ref_map(self, ref_map: RoleRefMap) -> None:
        """Update the current ref mapping (call after each snapshot)."""
        self._ref_map = ref_map

    # ------------------------------------------------------------------
    # Locator resolution
    # ------------------------------------------------------------------

    def _resolve_locator(self, page: Page, ref: str) -> Locator:
        """Resolve an ``eN`` ref to a Playwright Locator.

        Raises:
            ElementNotFoundError: If *ref* is not in the current ref map.
        """
        role_ref = self._ref_map.get(ref)
        if role_ref is None:
            raise ElementNotFoundError(ref=ref, cause="ref not in current snapshot")

        kwargs: dict[str, object] = {}
        if role_ref.name is not None:
            kwargs["name"] = role_ref.name
            kwargs["exact"] = True

        # Map roles that aren't directly supported by get_by_role
        role = role_ref.role
        if role in INTERACTIVE_ROLES or role in (
            "heading", "listitem", "cell", "columnheader",
            "gridcell", "rowheader", "article", "main",
            "navigation", "region",
        ):
            locator = page.get_by_role(role, **kwargs)  # type: ignore[arg-type]
        else:
            locator = page.get_by_role(role, **kwargs)  # type: ignore[arg-type]

        if role_ref.nth is not None:
            locator = locator.nth(role_ref.nth)

        return locator

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def navigate(self, page: Page, url: str, *, timeout_ms: int = 30000) -> None:
        """Navigate *page* to *url*."""
        t = _clamp_timeout(timeout_ms)
        log = logger.bind(url=url, timeout_ms=t)
        log.info("action_navigate")
        try:
            await page.goto(url, timeout=t, wait_until="load")
        except Exception as exc:
            raise NavigationError(url=url, cause=str(exc)) from exc

    async def click(self, page: Page, ref: str, *, timeout_ms: int = 8000) -> None:
        """Click the element identified by *ref*."""
        t = _clamp_timeout(timeout_ms)
        log = logger.bind(ref=ref, timeout_ms=t)
        log.info("action_click")
        locator = self._resolve_locator(page, ref)
        try:
            await locator.click(timeout=t)
        except Exception as exc:
            raise ActionTimeoutError(action="click", ref_or_selector=ref, timeout_ms=t) from exc

    async def type_text(
        self,
        page: Page,
        ref: str,
        text: str,
        *,
        submit: bool = False,
        timeout_ms: int = 8000,
    ) -> None:
        """Fill *text* into the element identified by *ref*."""
        t = _clamp_timeout(timeout_ms)
        log = logger.bind(ref=ref, text_len=len(text), submit=submit, timeout_ms=t)
        log.info("action_type_text")
        locator = self._resolve_locator(page, ref)
        try:
            await locator.fill(text, timeout=t)
            if submit:
                await locator.press("Enter", timeout=t)
        except ElementNotFoundError:
            raise
        except Exception as exc:
            raise ActionTimeoutError(action="type_text", ref_or_selector=ref, timeout_ms=t) from exc

    async def scroll(self, page: Page, ref: str, *, timeout_ms: int = 8000) -> None:
        """Scroll the element identified by *ref* into view."""
        t = _clamp_timeout(timeout_ms)
        log = logger.bind(ref=ref, timeout_ms=t)
        log.info("action_scroll")
        locator = self._resolve_locator(page, ref)
        try:
            await locator.scroll_into_view_if_needed(timeout=t)
        except ElementNotFoundError:
            raise
        except Exception as exc:
            raise ActionTimeoutError(action="scroll", ref_or_selector=ref, timeout_ms=t) from exc

    async def select(
        self, page: Page, ref: str, values: list[str], *, timeout_ms: int = 8000
    ) -> None:
        """Select option *values* in the dropdown identified by *ref*."""
        t = _clamp_timeout(timeout_ms)
        log = logger.bind(ref=ref, values=values, timeout_ms=t)
        log.info("action_select")
        locator = self._resolve_locator(page, ref)
        try:
            await locator.select_option(values, timeout=t)
        except ElementNotFoundError:
            raise
        except Exception as exc:
            raise ActionTimeoutError(action="select", ref_or_selector=ref, timeout_ms=t) from exc

    async def go_back(self, page: Page) -> None:
        """Navigate *page* back in history."""
        logger.info("action_go_back")
        await page.go_back()

    async def go_forward(self, page: Page) -> None:
        """Navigate *page* forward in history."""
        logger.info("action_go_forward")
        await page.go_forward()

    async def press_key(self, page: Page, key: str) -> None:
        """Press *key* on *page*."""
        log = logger.bind(key=key)
        log.info("action_press_key")
        await page.keyboard.press(key)

    async def hover(self, page: Page, ref: str, *, timeout_ms: int = 8000) -> None:
        """Hover over the element identified by *ref*."""
        t = _clamp_timeout(timeout_ms)
        log = logger.bind(ref=ref, timeout_ms=t)
        log.info("action_hover")
        locator = self._resolve_locator(page, ref)
        try:
            await locator.hover(timeout=t)
        except ElementNotFoundError:
            raise
        except Exception as exc:
            raise ActionTimeoutError(action="hover", ref_or_selector=ref, timeout_ms=t) from exc

    async def wait(
        self,
        page: Page,
        *,
        time_ms: int | None = None,
        text: str | None = None,
        text_gone: str | None = None,
        selector: str | None = None,
        url: str | None = None,
        load_state: str | None = None,
        timeout_ms: int = 20000,
    ) -> None:
        """Wait for a condition on *page*.

        Exactly one condition should be specified. Conditions:
        - ``time_ms``: sleep for N milliseconds.
        - ``text``: wait for text to appear.
        - ``text_gone``: wait for text to disappear.
        - ``selector``: wait for CSS selector to be visible.
        - ``url``: wait for URL to match (substring).
        - ``load_state``: wait for page load state.
        """
        t = _clamp_timeout(timeout_ms)
        log = logger.bind(timeout_ms=t)
        log.info("action_wait")

        if time_ms is not None:
            await asyncio.sleep(time_ms / 1000.0)
        elif text is not None:
            await page.get_by_text(text).wait_for(state="visible", timeout=t)
        elif text_gone is not None:
            await page.get_by_text(text_gone).wait_for(state="hidden", timeout=t)
        elif selector is not None:
            await page.wait_for_selector(selector, state="visible", timeout=t)
        elif url is not None:
            await page.wait_for_url(f"**{url}**", timeout=t)
        elif load_state is not None:
            await page.wait_for_load_state(load_state, timeout=t)  # type: ignore[arg-type]
