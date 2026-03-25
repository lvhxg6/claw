"""Unit tests for ScreenshotCapturer.

Covers Requirements 5.1, 5.2, 5.3, 5.5.
"""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock

import pytest

from smartclaw.browser.exceptions import ElementNotVisibleError, ScreenshotTooLargeError
from smartclaw.browser.page_parser import RoleRef
from smartclaw.browser.screenshot import ScreenshotCapturer, ScreenshotResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
    b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _make_mock_page() -> AsyncMock:
    mock_page = AsyncMock()
    mock_page.screenshot = AsyncMock(return_value=_TINY_PNG)
    mock_page.viewport_size = {"width": 1280, "height": 720}
    return mock_page


# ---------------------------------------------------------------------------
# Viewport screenshot (Requirement 5.1)
# ---------------------------------------------------------------------------


async def test_capture_viewport():
    """capture_viewport returns a valid ScreenshotResult."""
    page = _make_mock_page()
    capturer = ScreenshotCapturer()

    result = await capturer.capture_viewport(page)

    assert isinstance(result, ScreenshotResult)
    assert result.mime_type == "image/png"
    assert result.width == 1280
    assert result.height == 720
    assert len(result.data) > 0
    page.screenshot.assert_awaited_once()


# ---------------------------------------------------------------------------
# Full-page screenshot (Requirement 5.2)
# ---------------------------------------------------------------------------


async def test_capture_full_page():
    """capture_full_page returns a valid ScreenshotResult."""
    page = _make_mock_page()
    capturer = ScreenshotCapturer()

    result = await capturer.capture_full_page(page)

    assert isinstance(result, ScreenshotResult)
    assert result.mime_type == "image/png"
    call_kwargs = page.screenshot.call_args[1]
    assert call_kwargs["full_page"] is True


# ---------------------------------------------------------------------------
# Element screenshot (Requirement 5.3)
# ---------------------------------------------------------------------------


async def test_capture_element():
    """capture_element captures a specific element by ref."""
    mock_locator = AsyncMock()
    mock_locator.screenshot = AsyncMock(return_value=_TINY_PNG)
    mock_locator.bounding_box = AsyncMock(return_value={"x": 0, "y": 0, "width": 200, "height": 50})
    mock_locator.nth = MagicMock(return_value=mock_locator)

    page = _make_mock_page()
    page.get_by_role = MagicMock(return_value=mock_locator)

    ref_map = {"e1": RoleRef(role="button", name="Submit")}
    capturer = ScreenshotCapturer()

    result = await capturer.capture_element(page, "e1", ref_map)

    assert isinstance(result, ScreenshotResult)
    assert result.width == 200
    assert result.height == 50
    mock_locator.screenshot.assert_awaited_once()


# ---------------------------------------------------------------------------
# Progressive quality reduction (Requirement 5.5)
# ---------------------------------------------------------------------------


async def test_progressive_quality_reduction():
    """When screenshot exceeds max_bytes, capturer reduces quality."""
    large_data = b"x" * 1000  # 1000 bytes
    small_data = b"y" * 50  # 50 bytes

    page = _make_mock_page()
    # First call returns large, subsequent calls return small
    page.screenshot = AsyncMock(side_effect=[large_data, small_data])
    page.viewport_size = {"width": 800, "height": 600}

    capturer = ScreenshotCapturer(max_bytes=100)

    result = await capturer.capture_viewport(page, format="jpeg", jpeg_quality=85)

    assert len(base64.b64decode(result.data)) <= 100
    assert page.screenshot.await_count >= 2
