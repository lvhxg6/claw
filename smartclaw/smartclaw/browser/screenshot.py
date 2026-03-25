"""Screenshot Capturer — Viewport, full-page, and element screenshot capture.

Provides ``ScreenshotResult`` and ``ScreenshotCapturer`` with progressive
quality reduction when screenshots exceed the configured size limit.

Reference: OpenClaw ``normalizeBrowserScreenshot``.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from smartclaw.browser.exceptions import ElementNotFoundError, ElementNotVisibleError, ScreenshotTooLargeError
from smartclaw.browser.page_parser import RoleRefMap

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = structlog.get_logger(component="browser.screenshot")

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class ScreenshotResult:
    """Screenshot result."""

    data: str  # base64-encoded image data
    mime_type: str  # "image/png" or "image/jpeg"
    width: int
    height: int


# ---------------------------------------------------------------------------
# ScreenshotCapturer
# ---------------------------------------------------------------------------

_JPEG_QUALITY_STEPS = [85, 60, 40, 20]


class ScreenshotCapturer:
    """Screenshot capture with progressive quality reduction.

    Supports viewport, full-page, and element capture modes.
    When a screenshot exceeds *max_bytes*, the capturer progressively
    reduces JPEG quality until the image fits.
    """

    def __init__(self, max_bytes: int = 5 * 1024 * 1024) -> None:
        self._max_bytes = max_bytes

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def capture_viewport(
        self,
        page: Page,
        *,
        format: str = "png",
        jpeg_quality: int = 85,
    ) -> ScreenshotResult:
        """Capture the current viewport."""
        jpeg_quality = max(0, min(100, jpeg_quality))
        raw = await self._take_screenshot(page, full_page=False, format=format, jpeg_quality=jpeg_quality)
        return await self._build_result(page, raw, format=format, jpeg_quality=jpeg_quality, full_page=False)

    async def capture_full_page(
        self,
        page: Page,
        *,
        format: str = "png",
        jpeg_quality: int = 85,
    ) -> ScreenshotResult:
        """Capture the entire scrollable page."""
        jpeg_quality = max(0, min(100, jpeg_quality))
        raw = await self._take_screenshot(page, full_page=True, format=format, jpeg_quality=jpeg_quality)
        return await self._build_result(page, raw, format=format, jpeg_quality=jpeg_quality, full_page=True)

    async def capture_element(
        self,
        page: Page,
        ref: str,
        ref_map: RoleRefMap,
        *,
        format: str = "png",
        jpeg_quality: int = 85,
    ) -> ScreenshotResult:
        """Capture a specific element identified by *ref*."""
        from smartclaw.browser.actions import ActionExecutor

        jpeg_quality = max(0, min(100, jpeg_quality))
        role_ref = ref_map.get(ref)
        if role_ref is None:
            raise ElementNotFoundError(ref=ref, cause="ref not in current snapshot")

        executor = ActionExecutor(ref_map=ref_map)
        locator = executor._resolve_locator(page, ref)

        try:
            kwargs: dict[str, object] = {"type": format}
            if format == "jpeg":
                kwargs["quality"] = jpeg_quality
            raw = await locator.screenshot(**kwargs)  # type: ignore[arg-type]
        except Exception as exc:
            raise ElementNotVisibleError(ref=ref) from exc

        b64 = base64.b64encode(raw).decode("ascii")
        mime = "image/jpeg" if format == "jpeg" else "image/png"
        # Element screenshots: use bounding box for dimensions
        box = await locator.bounding_box()
        w = int(box["width"]) if box else 0
        h = int(box["height"]) if box else 0
        return ScreenshotResult(data=b64, mime_type=mime, width=w, height=h)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _take_screenshot(
        self,
        page: Page,
        *,
        full_page: bool,
        format: str,
        jpeg_quality: int,
    ) -> bytes:
        """Take a raw screenshot from the page."""
        if format == "jpeg":
            result: bytes = await page.screenshot(
                full_page=full_page, type="jpeg", quality=jpeg_quality,
            )
        else:
            result = await page.screenshot(full_page=full_page, type="png")
        return result

    async def _build_result(
        self,
        page: Page,
        raw: bytes,
        *,
        format: str,
        jpeg_quality: int,
        full_page: bool,
    ) -> ScreenshotResult:
        """Build a ScreenshotResult, applying progressive quality reduction if needed."""
        # Check size and progressively reduce quality if needed
        if len(raw) > self._max_bytes and format == "jpeg":
            for q in _JPEG_QUALITY_STEPS:
                if q >= jpeg_quality:
                    continue
                raw = await self._take_screenshot(page, full_page=full_page, format="jpeg", jpeg_quality=q)
                if len(raw) <= self._max_bytes:
                    break

        if len(raw) > self._max_bytes and format == "png":
            # Try JPEG conversion as last resort
            for q in _JPEG_QUALITY_STEPS:
                raw = await self._take_screenshot(page, full_page=full_page, format="jpeg", jpeg_quality=q)
                format = "jpeg"
                if len(raw) <= self._max_bytes:
                    break

        if len(raw) > self._max_bytes:
            raise ScreenshotTooLargeError(actual_bytes=len(raw), max_bytes=self._max_bytes)

        b64 = base64.b64encode(raw).decode("ascii")
        mime = "image/jpeg" if format == "jpeg" else "image/png"
        viewport = page.viewport_size or {"width": 1280, "height": 720}
        w = viewport["width"]
        h = viewport["height"]
        return ScreenshotResult(data=b64, mime_type=mime, width=w, height=h)
