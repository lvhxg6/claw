"""Property-based tests for ScreenshotCapturer.

Covers Property 10 from the design document.
"""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from smartclaw.browser.screenshot import ScreenshotCapturer, ScreenshotResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# A tiny valid 1x1 PNG (67 bytes)
_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
    b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _make_mock_page(fmt: str = "png") -> AsyncMock:
    """Return a mock page that returns a tiny image on screenshot()."""
    raw = _TINY_PNG
    mock_page = AsyncMock()
    mock_page.screenshot = AsyncMock(return_value=raw)
    mock_page.viewport_size = {"width": 1280, "height": 720}
    return mock_page


# ---------------------------------------------------------------------------
# Feature: smartclaw-browser-engine, Property 10: Screenshot result completeness
# ---------------------------------------------------------------------------
# **Validates: Requirements 5.4, 5.6**


@settings(max_examples=100)
@given(
    fmt=st.sampled_from(["png", "jpeg"]),
    quality=st.integers(0, 100),
)
@pytest.mark.asyncio
async def test_screenshot_result_completeness(fmt: str, quality: int) -> None:
    """For any successful capture, the result has non-empty base64 data,
    valid mime_type, and positive width/height. JPEG quality is clamped to [0, 100].
    """
    mock_page = _make_mock_page(fmt)
    capturer = ScreenshotCapturer()

    result = await capturer.capture_viewport(mock_page, format=fmt, jpeg_quality=quality)

    # (a) non-empty base64 data
    assert len(result.data) > 0
    # Verify it's valid base64
    decoded = base64.b64decode(result.data)
    assert len(decoded) > 0

    # (b) mime_type is valid
    assert result.mime_type in ("image/png", "image/jpeg")

    # (c) width and height are positive
    assert result.width > 0
    assert result.height > 0


@settings(max_examples=100)
@given(
    fmt=st.sampled_from(["png", "jpeg"]),
    quality=st.integers(0, 100),
)
@pytest.mark.asyncio
async def test_full_page_screenshot_result_completeness(fmt: str, quality: int) -> None:
    """Full-page capture also produces complete results."""
    mock_page = _make_mock_page(fmt)
    capturer = ScreenshotCapturer()

    result = await capturer.capture_full_page(mock_page, format=fmt, jpeg_quality=quality)

    assert len(result.data) > 0
    assert result.mime_type in ("image/png", "image/jpeg")
    assert result.width > 0
    assert result.height > 0
