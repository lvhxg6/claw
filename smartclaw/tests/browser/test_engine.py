"""Unit tests for BrowserEngine lifecycle management."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from smartclaw.browser.engine import BrowserConfig, BrowserEngine
from smartclaw.browser.exceptions import BrowserConnectionError, BrowserLaunchError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_playwright_stack():
    """Return (mock_pw, mock_browser, mock_context) wired together."""
    mock_context = AsyncMock()
    mock_context.close = AsyncMock()

    mock_browser = AsyncMock()
    mock_browser.is_connected = MagicMock(return_value=True)
    mock_browser.close = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)
    mock_browser.contexts = []

    mock_pw = AsyncMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_pw.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
    mock_pw.stop = AsyncMock()

    return mock_pw, mock_browser, mock_context


def _patch_async_playwright(mock_pw):
    """Return a patch context for async_playwright."""
    mock_cm = AsyncMock()
    mock_cm.start = AsyncMock(return_value=mock_pw)
    return patch("smartclaw.browser.engine.async_playwright", return_value=mock_cm)


# ---------------------------------------------------------------------------
# Launch tests (Requirements 1.1, 1.2)
# ---------------------------------------------------------------------------


async def test_launch_headless():
    """Headless launch creates browser and context."""
    mock_pw, mock_browser, mock_context = _mock_playwright_stack()
    with _patch_async_playwright(mock_pw):
        engine = BrowserEngine(config=BrowserConfig(headless=True))
        await engine.launch()

        assert engine.is_connected
        assert engine.browser is mock_browser
        assert engine.context is mock_context
        mock_pw.chromium.launch.assert_awaited_once()
        call_kwargs = mock_pw.chromium.launch.call_args[1]
        assert call_kwargs["headless"] is True

        await engine.shutdown()


async def test_launch_headed():
    """Headed launch passes headless=False."""
    mock_pw, mock_browser, mock_context = _mock_playwright_stack()
    with _patch_async_playwright(mock_pw):
        engine = BrowserEngine(config=BrowserConfig(headless=False))
        await engine.launch()

        call_kwargs = mock_pw.chromium.launch.call_args[1]
        assert call_kwargs["headless"] is False
        await engine.shutdown()


# ---------------------------------------------------------------------------
# CDP connect tests (Requirements 1.3, 1.4)
# ---------------------------------------------------------------------------


async def test_connect_success():
    """CDP connect succeeds on first attempt."""
    mock_pw, mock_browser, mock_context = _mock_playwright_stack()
    with _patch_async_playwright(mock_pw):
        engine = BrowserEngine()
        await engine.connect("http://localhost:9222")

        assert engine.is_connected
        mock_pw.chromium.connect_over_cdp.assert_awaited_once_with("http://localhost:9222")
        await engine.shutdown()


async def test_connect_retries_on_failure():
    """CDP connect retries up to 3 times then raises BrowserConnectionError."""
    mock_pw, mock_browser, mock_context = _mock_playwright_stack()
    mock_pw.chromium.connect_over_cdp = AsyncMock(side_effect=Exception("refused"))

    with _patch_async_playwright(mock_pw):
        engine = BrowserEngine()
        with pytest.raises(BrowserConnectionError) as exc_info:
            await engine.connect("http://localhost:9222")

        assert exc_info.value.retries == 3
        assert len(exc_info.value.errors) == 3
        assert "refused" in exc_info.value.errors[0]


# ---------------------------------------------------------------------------
# Shutdown tests (Requirements 1.5, 1.6)
# ---------------------------------------------------------------------------


async def test_shutdown_cleans_up():
    """Shutdown closes context, browser, and stops playwright."""
    mock_pw, mock_browser, mock_context = _mock_playwright_stack()
    with _patch_async_playwright(mock_pw):
        engine = BrowserEngine()
        await engine.launch()
        await engine.shutdown()

        mock_context.close.assert_awaited_once()
        mock_browser.close.assert_awaited_once()
        mock_pw.stop.assert_awaited_once()
        assert engine.browser is None
        assert engine.context is None


async def test_shutdown_force_kill_on_timeout():
    """Shutdown handles unresponsive browser (context.close times out)."""
    mock_pw, mock_browser, mock_context = _mock_playwright_stack()
    mock_context.close = AsyncMock(side_effect=asyncio.TimeoutError)

    with _patch_async_playwright(mock_pw):
        engine = BrowserEngine()
        await engine.launch()
        # Should not raise — force-kill path
        await engine.shutdown()

        assert engine.browser is None


# ---------------------------------------------------------------------------
# Context manager tests (Requirements 8.1, 8.2)
# ---------------------------------------------------------------------------


async def test_context_manager():
    """async with BrowserEngine launches and shuts down."""
    mock_pw, mock_browser, mock_context = _mock_playwright_stack()
    with _patch_async_playwright(mock_pw):
        async with BrowserEngine() as engine:
            assert engine.is_connected

        mock_browser.close.assert_awaited_once()


async def test_context_manager_cleanup_on_exception():
    """Context manager cleans up even when body raises."""
    mock_pw, mock_browser, mock_context = _mock_playwright_stack()
    with _patch_async_playwright(mock_pw):
        with pytest.raises(ValueError, match="boom"):
            async with BrowserEngine() as engine:
                assert engine.is_connected
                raise ValueError("boom")

        mock_browser.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# Launch error tests (Requirements 8.5)
# ---------------------------------------------------------------------------


async def test_launch_timeout_raises_browser_launch_error():
    """Launch timeout raises BrowserLaunchError."""
    mock_pw, _, _ = _mock_playwright_stack()
    mock_pw.chromium.launch = AsyncMock(side_effect=asyncio.TimeoutError)

    with _patch_async_playwright(mock_pw):
        engine = BrowserEngine()
        with pytest.raises(BrowserLaunchError) as exc_info:
            await engine.launch()

        assert "headless" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------


def test_default_config():
    """BrowserEngine uses default BrowserConfig when none provided."""
    engine = BrowserEngine()
    assert engine.config.headless is True
    assert engine.config.viewport_width == 1280
    assert engine.config.viewport_height == 720
    assert engine.config.max_pages == 10
