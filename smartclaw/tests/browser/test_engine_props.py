"""Property-based tests for BrowserConfig and BrowserEngine.

# Feature: smartclaw-browser-engine, Property 1: BrowserConfig accepts all valid configurations
# Feature: smartclaw-browser-engine, Property 2: Browser connection state round-trip
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import hypothesis.strategies as st
from hypothesis import given, settings

from smartclaw.browser.engine import BrowserConfig, BrowserEngine

# ---------------------------------------------------------------------------
# Property 1: BrowserConfig accepts all valid configurations
# ---------------------------------------------------------------------------


@given(
    headless=st.booleans(),
    viewport_width=st.integers(min_value=1, max_value=4096),
    viewport_height=st.integers(min_value=1, max_value=4096),
    proxy=st.one_of(st.none(), st.text(min_size=1, max_size=50)),
    user_agent=st.one_of(st.none(), st.text(min_size=1, max_size=50)),
    launch_args=st.lists(st.text(min_size=0, max_size=20), max_size=5),
    max_pages=st.integers(min_value=1, max_value=100),
)
@settings(max_examples=100)
def test_browser_config_accepts_valid_configurations(
    headless: bool,
    viewport_width: int,
    viewport_height: int,
    proxy: str | None,
    user_agent: str | None,
    launch_args: list[str],
    max_pages: int,
) -> None:
    """**Validates: Requirements 1.7**

    For any valid combination of fields, BrowserConfig constructs
    successfully and preserves all field values.
    """
    config = BrowserConfig(
        headless=headless,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
        proxy=proxy,
        user_agent=user_agent,
        launch_args=launch_args,
        max_pages=max_pages,
    )

    assert config.headless == headless
    assert config.viewport_width == viewport_width
    assert config.viewport_height == viewport_height
    assert config.proxy == proxy
    assert config.user_agent == user_agent
    assert config.launch_args == launch_args
    assert config.max_pages == max_pages


# ---------------------------------------------------------------------------
# Property 2: Browser connection state round-trip
# ---------------------------------------------------------------------------


def _make_mock_playwright(headless: bool) -> tuple[AsyncMock, AsyncMock, AsyncMock]:
    """Create mock Playwright, Browser, and BrowserContext objects."""
    mock_context = AsyncMock()
    mock_context.close = AsyncMock()

    mock_browser = AsyncMock()
    mock_browser.is_connected = MagicMock(return_value=True)
    mock_browser.close = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    mock_pw = AsyncMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_pw.stop = AsyncMock()

    return mock_pw, mock_browser, mock_context


@given(headless=st.booleans())
@settings(max_examples=100)
def test_browser_connection_state_round_trip(headless: bool) -> None:
    """**Validates: Requirements 1.8**

    After launch(), is_connected is True.
    After shutdown(), is_connected is False.
    """
    mock_pw, mock_browser, mock_context = _make_mock_playwright(headless)

    async def _run() -> None:
        with patch(
            "smartclaw.browser.engine.async_playwright"
        ) as mock_async_pw:
            mock_cm = AsyncMock()
            mock_cm.start = AsyncMock(return_value=mock_pw)
            mock_async_pw.return_value = mock_cm

            config = BrowserConfig(headless=headless)
            engine = BrowserEngine(config=config)

            assert not engine.is_connected

            await engine.launch()
            assert engine.is_connected

            # Simulate disconnected state after shutdown
            mock_browser.is_connected = MagicMock(return_value=False)
            await engine.shutdown()
            assert not engine.is_connected

    asyncio.run(_run())
