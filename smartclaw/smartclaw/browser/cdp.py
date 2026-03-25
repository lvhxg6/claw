"""CDP Client — Playwright CDPSession wrapper.

Provides ``CDPClient`` for low-level Chrome DevTools Protocol operations
including command execution with configurable timeouts, JavaScript evaluation,
and screenshot capture.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

from smartclaw.browser.exceptions import CDPEvaluateError, CDPSessionError, CDPTimeoutError

if TYPE_CHECKING:
    from playwright.async_api import CDPSession, Page

logger = structlog.get_logger(component="browser.cdp")


class CDPClient:
    """Playwright CDPSession wrapper.

    Wraps a Playwright ``CDPSession`` to provide timeout-controlled CDP
    command execution, JavaScript evaluation, and screenshot capture.
    """

    def __init__(self, page: Page) -> None:
        self._page = page
        self._session: CDPSession | None = None

    @property
    def session(self) -> CDPSession | None:
        """Return the underlying CDPSession, if created."""
        return self._session

    async def create_session(self) -> None:
        """Create a CDPSession via ``page.context.new_cdp_session(page)``.

        Raises:
            CDPSessionError: If session creation fails.
        """
        log = logger.bind(page_url=self._page.url)
        log.info("cdp_session_creating")
        try:
            context = self._page.context
            self._session = await context.new_cdp_session(self._page)
            log.info("cdp_session_created")
        except Exception as exc:
            raise CDPSessionError(page_url=self._page.url, cause=str(exc)) from exc

    async def execute(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Execute a CDP command with configurable timeout.

        Args:
            method: CDP domain method name (e.g. ``"Page.captureScreenshot"``).
            params: Optional parameters for the command.
            timeout: Timeout in seconds (default 10).

        Returns:
            The CDP command result as a dictionary.

        Raises:
            CDPSessionError: If no session has been created.
            CDPTimeoutError: If the command exceeds the timeout.
        """
        if self._session is None:
            raise CDPSessionError(page_url=self._page.url, cause="No active CDPSession. Call create_session() first.")

        log = logger.bind(method=method)
        log.debug("cdp_execute", timeout=timeout)

        try:
            result: dict[str, Any] = await asyncio.wait_for(
                self._session.send(method, params or {}),
                timeout=timeout,
            )
            return result
        except TimeoutError as exc:
            raise CDPTimeoutError(method=method, elapsed=timeout) from exc

    async def evaluate_js(self, expression: str) -> Any:
        """Execute a JavaScript expression via ``Runtime.evaluate``.

        Args:
            expression: JavaScript expression to evaluate.

        Returns:
            The evaluation result value.

        Raises:
            CDPSessionError: If no session has been created.
            CDPEvaluateError: If the evaluation fails.
        """
        if self._session is None:
            raise CDPSessionError(page_url=self._page.url, cause="No active CDPSession. Call create_session() first.")

        log = logger.bind(expression=expression[:80])
        log.debug("cdp_evaluate_js")

        try:
            result = await self._session.send(
                "Runtime.evaluate",
                {"expression": expression, "returnByValue": True},
            )
        except Exception as exc:
            raise CDPEvaluateError(expression=expression, cause=str(exc)) from exc

        if "exceptionDetails" in result:
            detail = result["exceptionDetails"]
            text = detail.get("text", str(detail))
            raise CDPEvaluateError(expression=expression, cause=text)

        return result.get("result", {}).get("value")

    async def capture_screenshot(self) -> str:
        """Capture a screenshot via ``Page.captureScreenshot``.

        Returns:
            Base64-encoded screenshot data.

        Raises:
            CDPSessionError: If no session has been created.
        """
        result = await self.execute("Page.captureScreenshot")
        data: str = result.get("data", "")
        return data

    async def detach(self) -> None:
        """Detach the CDPSession to free resources."""
        if self._session is not None:
            log = logger.bind(page_url=self._page.url)
            log.info("cdp_session_detaching")
            try:
                await self._session.detach()
            except Exception as exc:
                log.warning("cdp_session_detach_failed", error=str(exc))
            finally:
                self._session = None
                log.info("cdp_session_detached")
