"""Browser Engine — Playwright browser lifecycle management.

Provides ``BrowserConfig`` for configuration and ``BrowserEngine`` for
launching, connecting to, and shutting down Chromium browser instances.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

import structlog
from playwright.async_api import async_playwright
from pydantic import BaseModel, Field

from smartclaw.browser.exceptions import BrowserConnectionError, BrowserLaunchError

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Playwright

logger = structlog.get_logger(component="browser.engine")


class BrowserConfig(BaseModel):
    """Browser launch configuration."""

    headless: bool = Field(default=True, description="Run in headless mode")
    viewport_width: int = Field(default=1280, gt=0, description="Viewport width in pixels")
    viewport_height: int = Field(default=720, gt=0, description="Viewport height in pixels")
    proxy: str | None = Field(default=None, description="Proxy server URL")
    user_agent: str | None = Field(default=None, description="User-Agent override")
    launch_args: list[str] = Field(default_factory=list, description="Extra Chromium launch arguments")
    max_pages: int = Field(default=10, gt=0, description="Maximum concurrent pages")


class BrowserEngine:
    """Playwright browser lifecycle manager.

    Supports the async context manager protocol for automatic cleanup.
    """

    _LAUNCH_TIMEOUT_S: float = 30.0
    _CONNECT_TIMEOUT_S: float = 10.0
    _CONNECT_RETRIES: int = 3
    _SHUTDOWN_TIMEOUT_S: float = 10.0

    def __init__(self, config: BrowserConfig | None = None) -> None:
        self._config = config or BrowserConfig()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def config(self) -> BrowserConfig:
        """Return the current browser configuration."""
        return self._config

    @property
    def is_connected(self) -> bool:
        """Whether the browser is currently connected."""
        return self._browser is not None and self._browser.is_connected()

    @property
    def browser(self) -> Browser | None:
        """Return the underlying Playwright Browser, if any."""
        return self._browser

    @property
    def context(self) -> BrowserContext | None:
        """Return the default BrowserContext, if any."""
        return self._context

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def launch(self) -> None:
        """Launch a Chromium browser instance.

        Timeout: 30 seconds.  Headless/headed mode is determined by config.
        """
        log = logger.bind(headless=self._config.headless)
        log.info("browser_launching")

        try:
            self._playwright = await async_playwright().start()

            launch_kwargs: dict[str, object] = {
                "headless": self._config.headless,
                "args": self._config.launch_args,
            }
            if self._config.proxy:
                launch_kwargs["proxy"] = {"server": self._config.proxy}

            self._browser = await asyncio.wait_for(
                self._playwright.chromium.launch(**launch_kwargs),  # type: ignore[arg-type]
                timeout=self._LAUNCH_TIMEOUT_S,
            )

            # Create default context with viewport / user-agent
            ctx_kwargs: dict[str, object] = {
                "viewport": {
                    "width": self._config.viewport_width,
                    "height": self._config.viewport_height,
                },
            }
            if self._config.user_agent:
                ctx_kwargs["user_agent"] = self._config.user_agent

            assert self._browser is not None
            self._context = await self._browser.new_context(**ctx_kwargs)  # type: ignore[arg-type]

            log.info("browser_launched")
        except TimeoutError as exc:
            await self._cleanup_on_error()
            raise BrowserLaunchError(
                headless=self._config.headless,
                timeout=self._LAUNCH_TIMEOUT_S,
                cause="launch timed out",
            ) from exc
        except Exception as exc:
            await self._cleanup_on_error()
            raise BrowserLaunchError(
                headless=self._config.headless,
                timeout=self._LAUNCH_TIMEOUT_S,
                cause=str(exc),
            ) from exc

    async def connect(self, cdp_url: str) -> None:
        """Connect to an existing browser via CDP URL.

        Timeout: 10 seconds per attempt, up to 3 retries with incremental backoff.
        """
        log = logger.bind(cdp_url=cdp_url)
        log.info("browser_connecting")

        errors: list[str] = []
        for attempt in range(1, self._CONNECT_RETRIES + 1):
            try:
                if self._playwright is None:
                    self._playwright = await async_playwright().start()

                self._browser = await asyncio.wait_for(
                    self._playwright.chromium.connect_over_cdp(cdp_url),
                    timeout=self._CONNECT_TIMEOUT_S,
                )
                self._context = (
                    self._browser.contexts[0]
                    if self._browser.contexts
                    else await self._browser.new_context()
                )
                log.info("browser_connected", attempt=attempt)
                return
            except Exception as exc:
                errors.append(f"attempt {attempt}: {exc}")
                log.warning("browser_connect_retry", attempt=attempt, error=str(exc))
                if attempt < self._CONNECT_RETRIES:
                    await asyncio.sleep(attempt)  # incremental backoff: 1s, 2s

        await self._cleanup_on_error()
        raise BrowserConnectionError(cdp_url=cdp_url, retries=self._CONNECT_RETRIES, errors=errors)

    async def shutdown(self) -> None:
        """Close all contexts, pages, and the browser.

        Force-kills the browser process after 10 seconds if unresponsive.
        """
        log = logger.bind(is_connected=self.is_connected)
        log.info("browser_shutting_down")

        try:
            if self._context:
                try:
                    await asyncio.wait_for(self._context.close(), timeout=self._SHUTDOWN_TIMEOUT_S)
                except Exception:
                    log.warning("browser_context_close_failed")
                self._context = None

            if self._browser:
                try:
                    await asyncio.wait_for(self._browser.close(), timeout=self._SHUTDOWN_TIMEOUT_S)
                except Exception:
                    log.warning("browser_close_failed_force_kill")
                self._browser = None

            if self._playwright:
                await self._playwright.stop()
                self._playwright = None

            log.info("browser_shutdown_complete")
        except Exception as exc:
            log.error("browser_shutdown_error", error=str(exc))
            # Best-effort cleanup
            self._browser = None
            self._context = None
            if self._playwright:
                with contextlib.suppress(Exception):
                    await self._playwright.stop()
                self._playwright = None

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> BrowserEngine:
        await self.launch()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.shutdown()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _cleanup_on_error(self) -> None:
        """Best-effort cleanup after a failed launch/connect."""
        if self._context:
            with contextlib.suppress(Exception):
                await self._context.close()
            self._context = None
        if self._browser:
            with contextlib.suppress(Exception):
                await self._browser.close()
            self._browser = None
        if self._playwright:
            with contextlib.suppress(Exception):
                await self._playwright.stop()
            self._playwright = None
