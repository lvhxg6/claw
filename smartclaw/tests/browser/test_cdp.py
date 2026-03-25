"""Unit tests for CDPClient.

Covers Requirements 2.1–2.7: CDPSession creation, command execution,
timeout errors, JS evaluation, CDP screenshot, session detach, execute API.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from smartclaw.browser.cdp import CDPClient
from smartclaw.browser.exceptions import CDPEvaluateError, CDPSessionError, CDPTimeoutError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_page(url: str = "https://example.com") -> AsyncMock:
    """Return a mock Playwright Page with a mock context."""
    mock_session = AsyncMock()
    mock_session.send = AsyncMock(return_value={"result": "ok"})
    mock_session.detach = AsyncMock()

    mock_context = AsyncMock()
    mock_context.new_cdp_session = AsyncMock(return_value=mock_session)

    mock_page = AsyncMock()
    mock_page.url = url
    mock_page.context = mock_context

    return mock_page, mock_session, mock_context


# ---------------------------------------------------------------------------
# CDPSession creation (Requirement 2.1)
# ---------------------------------------------------------------------------


async def test_create_session_success():
    """create_session() creates a CDPSession via page.context.new_cdp_session."""
    mock_page, mock_session, mock_context = _make_mock_page()

    client = CDPClient(mock_page)
    await client.create_session()

    assert client.session is mock_session
    mock_context.new_cdp_session.assert_awaited_once_with(mock_page)


async def test_create_session_failure_raises_cdp_session_error():
    """create_session() raises CDPSessionError when creation fails."""
    mock_page, _, mock_context = _make_mock_page()
    mock_context.new_cdp_session = AsyncMock(side_effect=Exception("connection refused"))

    client = CDPClient(mock_page)
    with pytest.raises(CDPSessionError) as exc_info:
        await client.create_session()

    assert "connection refused" in str(exc_info.value)
    assert exc_info.value.page_url == "https://example.com"


# ---------------------------------------------------------------------------
# Command execution (Requirement 2.2, 2.7)
# ---------------------------------------------------------------------------


async def test_execute_sends_command():
    """execute() sends a CDP command and returns the result."""
    mock_page, mock_session, _ = _make_mock_page()
    mock_session.send = AsyncMock(return_value={"frameId": "abc123"})

    client = CDPClient(mock_page)
    await client.create_session()

    result = await client.execute("Page.navigate", {"url": "https://example.com"})

    assert result == {"frameId": "abc123"}
    mock_session.send.assert_awaited_once_with("Page.navigate", {"url": "https://example.com"})


async def test_execute_without_params():
    """execute() sends command with empty params when none provided."""
    mock_page, mock_session, _ = _make_mock_page()
    mock_session.send = AsyncMock(return_value={"data": "base64..."})

    client = CDPClient(mock_page)
    await client.create_session()

    result = await client.execute("Page.captureScreenshot")

    mock_session.send.assert_awaited_once_with("Page.captureScreenshot", {})
    assert result == {"data": "base64..."}


async def test_execute_without_session_raises_error():
    """execute() raises CDPSessionError when no session exists."""
    mock_page, _, _ = _make_mock_page()

    client = CDPClient(mock_page)
    with pytest.raises(CDPSessionError) as exc_info:
        await client.execute("Page.navigate")

    assert "No active CDPSession" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Timeout error (Requirement 2.3)
# ---------------------------------------------------------------------------


async def test_execute_timeout_raises_cdp_timeout_error():
    """execute() raises CDPTimeoutError when command exceeds timeout."""
    mock_page, mock_session, _ = _make_mock_page()

    async def _slow_send(method: str, params: dict) -> dict:  # type: ignore[type-arg]
        await asyncio.sleep(10)
        return {}

    mock_session.send = _slow_send

    client = CDPClient(mock_page)
    await client.create_session()

    with pytest.raises(CDPTimeoutError) as exc_info:
        await client.execute("Network.enable", timeout=0.01)

    assert exc_info.value.method == "Network.enable"


# ---------------------------------------------------------------------------
# JS evaluation (Requirement 2.4)
# ---------------------------------------------------------------------------


async def test_evaluate_js_success():
    """evaluate_js() returns the evaluated value."""
    mock_page, mock_session, _ = _make_mock_page()
    mock_session.send = AsyncMock(
        return_value={"result": {"type": "number", "value": 42}}
    )

    client = CDPClient(mock_page)
    await client.create_session()

    result = await client.evaluate_js("1 + 41")

    assert result == 42
    mock_session.send.assert_awaited_once_with(
        "Runtime.evaluate",
        {"expression": "1 + 41", "returnByValue": True},
    )


async def test_evaluate_js_exception_details_raises_error():
    """evaluate_js() raises CDPEvaluateError when exceptionDetails present."""
    mock_page, mock_session, _ = _make_mock_page()
    mock_session.send = AsyncMock(
        return_value={
            "exceptionDetails": {"text": "ReferenceError: x is not defined"},
            "result": {"type": "undefined"},
        }
    )

    client = CDPClient(mock_page)
    await client.create_session()

    with pytest.raises(CDPEvaluateError) as exc_info:
        await client.evaluate_js("x")

    assert "ReferenceError" in str(exc_info.value)


async def test_evaluate_js_send_failure_raises_error():
    """evaluate_js() raises CDPEvaluateError when send() throws."""
    mock_page, mock_session, _ = _make_mock_page()
    mock_session.send = AsyncMock(side_effect=Exception("protocol error"))

    client = CDPClient(mock_page)
    await client.create_session()

    with pytest.raises(CDPEvaluateError) as exc_info:
        await client.evaluate_js("document.title")

    assert "protocol error" in str(exc_info.value)


async def test_evaluate_js_without_session_raises_error():
    """evaluate_js() raises CDPSessionError when no session exists."""
    mock_page, _, _ = _make_mock_page()

    client = CDPClient(mock_page)
    with pytest.raises(CDPSessionError):
        await client.evaluate_js("1 + 1")


# ---------------------------------------------------------------------------
# CDP screenshot (Requirement 2.5)
# ---------------------------------------------------------------------------


async def test_capture_screenshot():
    """capture_screenshot() returns base64 data from Page.captureScreenshot."""
    mock_page, mock_session, _ = _make_mock_page()
    mock_session.send = AsyncMock(return_value={"data": "iVBORw0KGgo="})

    client = CDPClient(mock_page)
    await client.create_session()

    result = await client.capture_screenshot()

    assert result == "iVBORw0KGgo="


# ---------------------------------------------------------------------------
# Session detach (Requirement 2.6)
# ---------------------------------------------------------------------------


async def test_detach_session():
    """detach() calls session.detach() and clears the session."""
    mock_page, mock_session, _ = _make_mock_page()

    client = CDPClient(mock_page)
    await client.create_session()
    assert client.session is not None

    await client.detach()

    assert client.session is None
    mock_session.detach.assert_awaited_once()


async def test_detach_when_no_session():
    """detach() is a no-op when no session exists."""
    mock_page, _, _ = _make_mock_page()

    client = CDPClient(mock_page)
    await client.detach()  # Should not raise

    assert client.session is None


async def test_detach_handles_exception():
    """detach() handles exceptions from session.detach() gracefully."""
    mock_page, mock_session, _ = _make_mock_page()
    mock_session.detach = AsyncMock(side_effect=Exception("already detached"))

    client = CDPClient(mock_page)
    await client.create_session()

    await client.detach()  # Should not raise

    assert client.session is None
