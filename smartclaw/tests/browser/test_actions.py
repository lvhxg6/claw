"""Unit tests for ActionExecutor.

Covers Requirements 4.1–4.10, 8.4.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from smartclaw.browser.actions import ActionExecutor, _clamp_timeout
from smartclaw.browser.exceptions import (
    ActionTimeoutError,
    ElementNotFoundError,
    NavigationError,
)
from smartclaw.browser.page_parser import RoleRef

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_page() -> AsyncMock:
    """Return a mock Playwright Page with common methods."""
    mock_locator = AsyncMock()
    mock_locator.click = AsyncMock()
    mock_locator.fill = AsyncMock()
    mock_locator.press = AsyncMock()
    mock_locator.scroll_into_view_if_needed = AsyncMock()
    mock_locator.select_option = AsyncMock()
    mock_locator.hover = AsyncMock()
    mock_locator.nth = MagicMock(return_value=mock_locator)
    mock_locator.wait_for = AsyncMock()

    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.go_back = AsyncMock()
    mock_page.go_forward = AsyncMock()
    mock_page.get_by_role = MagicMock(return_value=mock_locator)
    mock_page.get_by_text = MagicMock(return_value=mock_locator)
    mock_page.wait_for_selector = AsyncMock()
    mock_page.wait_for_url = AsyncMock()
    mock_page.wait_for_load_state = AsyncMock()

    mock_keyboard = AsyncMock()
    mock_keyboard.press = AsyncMock()
    mock_page.keyboard = mock_keyboard

    return mock_page, mock_locator


def _sample_ref_map() -> dict[str, RoleRef]:
    return {
        "e1": RoleRef(role="button", name="Submit"),
        "e2": RoleRef(role="textbox", name="Search"),
        "e3": RoleRef(role="link", name="Home"),
        "e4": RoleRef(role="button", name="Submit", nth=0),
        "e5": RoleRef(role="button", name="Submit", nth=1),
        "e6": RoleRef(role="combobox", name="Country"),
    }


# ---------------------------------------------------------------------------
# Navigate (Requirement 4.1)
# ---------------------------------------------------------------------------


async def test_navigate():
    """navigate() calls page.goto with URL and timeout."""
    page, _ = _make_mock_page()
    executor = ActionExecutor()

    await executor.navigate(page, "https://example.com")

    page.goto.assert_awaited_once()
    call_args = page.goto.call_args
    assert call_args[0][0] == "https://example.com"


async def test_navigate_failure_raises_navigation_error():
    """navigate() raises NavigationError on failure."""
    page, _ = _make_mock_page()
    page.goto = AsyncMock(side_effect=Exception("net::ERR_NAME_NOT_RESOLVED"))
    executor = ActionExecutor()

    with pytest.raises(NavigationError) as exc_info:
        await executor.navigate(page, "https://bad-url.invalid")

    assert "bad-url.invalid" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Click (Requirement 4.2)
# ---------------------------------------------------------------------------


async def test_click():
    """click() resolves ref and clicks the locator."""
    page, locator = _make_mock_page()
    executor = ActionExecutor(ref_map=_sample_ref_map())

    await executor.click(page, "e1")

    page.get_by_role.assert_called_once()
    locator.click.assert_awaited_once()


async def test_click_unknown_ref_raises_error():
    """click() raises ElementNotFoundError for unknown ref."""
    page, _ = _make_mock_page()
    executor = ActionExecutor(ref_map={})

    with pytest.raises(ElementNotFoundError):
        await executor.click(page, "e999")


# ---------------------------------------------------------------------------
# Type text (Requirement 4.3)
# ---------------------------------------------------------------------------


async def test_type_text():
    """type_text() fills text into the element."""
    page, locator = _make_mock_page()
    executor = ActionExecutor(ref_map=_sample_ref_map())

    await executor.type_text(page, "e2", "hello world")

    locator.fill.assert_awaited_once_with("hello world", timeout=_clamp_timeout(8000))


async def test_type_text_with_submit():
    """type_text() presses Enter when submit=True."""
    page, locator = _make_mock_page()
    executor = ActionExecutor(ref_map=_sample_ref_map())

    await executor.type_text(page, "e2", "query", submit=True)

    locator.fill.assert_awaited_once()
    locator.press.assert_awaited_once_with("Enter", timeout=_clamp_timeout(8000))


# ---------------------------------------------------------------------------
# Scroll (Requirement 4.4)
# ---------------------------------------------------------------------------


async def test_scroll():
    """scroll() calls scroll_into_view_if_needed."""
    page, locator = _make_mock_page()
    executor = ActionExecutor(ref_map=_sample_ref_map())

    await executor.scroll(page, "e1")

    locator.scroll_into_view_if_needed.assert_awaited_once()


# ---------------------------------------------------------------------------
# Select (Requirement 4.5)
# ---------------------------------------------------------------------------


async def test_select():
    """select() calls select_option with values."""
    page, locator = _make_mock_page()
    executor = ActionExecutor(ref_map=_sample_ref_map())

    await executor.select(page, "e6", ["US", "UK"])

    locator.select_option.assert_awaited_once()


# ---------------------------------------------------------------------------
# Go back / forward (Requirements 4.6, 4.7)
# ---------------------------------------------------------------------------


async def test_go_back():
    """go_back() calls page.go_back()."""
    page, _ = _make_mock_page()
    executor = ActionExecutor()

    await executor.go_back(page)

    page.go_back.assert_awaited_once()


async def test_go_forward():
    """go_forward() calls page.go_forward()."""
    page, _ = _make_mock_page()
    executor = ActionExecutor()

    await executor.go_forward(page)

    page.go_forward.assert_awaited_once()


# ---------------------------------------------------------------------------
# Wait conditions (Requirement 4.8)
# ---------------------------------------------------------------------------


async def test_wait_time():
    """wait(time_ms=...) sleeps for the specified duration."""
    page, _ = _make_mock_page()
    executor = ActionExecutor()

    await executor.wait(page, time_ms=100)
    # No assertion needed — just verifying it doesn't raise


async def test_wait_text():
    """wait(text=...) waits for text to appear."""
    page, locator = _make_mock_page()
    executor = ActionExecutor()

    await executor.wait(page, text="Loading complete")

    page.get_by_text.assert_called_once_with("Loading complete")
    locator.wait_for.assert_awaited_once()


async def test_wait_text_gone():
    """wait(text_gone=...) waits for text to disappear."""
    page, locator = _make_mock_page()
    executor = ActionExecutor()

    await executor.wait(page, text_gone="Loading...")

    page.get_by_text.assert_called_once_with("Loading...")
    locator.wait_for.assert_awaited_once()
    call_kwargs = locator.wait_for.call_args[1]
    assert call_kwargs["state"] == "hidden"


async def test_wait_selector():
    """wait(selector=...) waits for CSS selector."""
    page, _ = _make_mock_page()
    executor = ActionExecutor()

    await executor.wait(page, selector="#content")

    page.wait_for_selector.assert_awaited_once()


async def test_wait_url():
    """wait(url=...) waits for URL match."""
    page, _ = _make_mock_page()
    executor = ActionExecutor()

    await executor.wait(page, url="/dashboard")

    page.wait_for_url.assert_awaited_once()


async def test_wait_load_state():
    """wait(load_state=...) waits for page load state."""
    page, _ = _make_mock_page()
    executor = ActionExecutor()

    await executor.wait(page, load_state="networkidle")

    page.wait_for_load_state.assert_awaited_once()


# ---------------------------------------------------------------------------
# Press key (Requirement 4.9)
# ---------------------------------------------------------------------------


async def test_press_key():
    """press_key() presses the specified key."""
    page, _ = _make_mock_page()
    executor = ActionExecutor()

    await executor.press_key(page, "Enter")

    page.keyboard.press.assert_awaited_once_with("Enter")


# ---------------------------------------------------------------------------
# Hover (Requirement 4.10)
# ---------------------------------------------------------------------------


async def test_hover():
    """hover() hovers over the element."""
    page, locator = _make_mock_page()
    executor = ActionExecutor(ref_map=_sample_ref_map())

    await executor.hover(page, "e1")

    locator.hover.assert_awaited_once()


# ---------------------------------------------------------------------------
# Page unresponsive timeout (Requirement 8.4)
# ---------------------------------------------------------------------------


async def test_click_timeout_raises_action_timeout_error():
    """click() raises ActionTimeoutError when locator.click times out."""
    page, locator = _make_mock_page()
    locator.click = AsyncMock(side_effect=Exception("Timeout 8000ms exceeded"))
    executor = ActionExecutor(ref_map=_sample_ref_map())

    with pytest.raises(ActionTimeoutError) as exc_info:
        await executor.click(page, "e1")

    assert "e1" in str(exc_info.value)


# ---------------------------------------------------------------------------
# set_ref_map
# ---------------------------------------------------------------------------


async def test_set_ref_map():
    """set_ref_map updates the internal ref mapping."""
    page, locator = _make_mock_page()
    executor = ActionExecutor()

    with pytest.raises(ElementNotFoundError):
        await executor.click(page, "e1")

    executor.set_ref_map(_sample_ref_map())
    await executor.click(page, "e1")
    locator.click.assert_awaited_once()


# ---------------------------------------------------------------------------
# Resolve locator with nth
# ---------------------------------------------------------------------------


async def test_resolve_locator_with_nth():
    """_resolve_locator uses nth() for duplicate role+name refs."""
    page, locator = _make_mock_page()
    executor = ActionExecutor(ref_map=_sample_ref_map())

    await executor.click(page, "e5")

    locator.nth.assert_called_once_with(1)
