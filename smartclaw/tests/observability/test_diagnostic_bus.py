"""Unit tests for the Diagnostic Event Bus.

Tests:
- emit with no subscribers returns immediately (Req 13.4)
- clear() removes all subscribers (Req 13.6)
- exception subscriber logs error (Req 13.5)
- all supported event types work (Req 14.1)
"""

from __future__ import annotations

import asyncio
import logging

import pytest

import smartclaw.observability.diagnostic_bus as bus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Setup / teardown
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_bus():
    """Ensure the bus is clean before and after every test."""
    bus.clear()
    yield
    bus.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_emit_no_subscribers_returns_immediately():
    """emit with no subscribers should complete without error (Req 13.4)."""
    # No subscribers registered — must not raise
    _run(bus.emit("tool.executed", {"tool_name": "search"}))
    assert bus.get_subscribers("tool.executed") == []


def test_clear_removes_all_subscribers():
    """clear() removes all subscribers across all event types (Req 13.6)."""
    async def sub_a(et: str, pl: dict) -> None:
        pass

    async def sub_b(et: str, pl: dict) -> None:
        pass

    bus.on("tool.executed", sub_a)
    bus.on("llm.called", sub_b)
    bus.on("agent.run", sub_a)

    assert len(bus.get_subscribers("tool.executed")) == 1
    assert len(bus.get_subscribers("llm.called")) == 1
    assert len(bus.get_subscribers("agent.run")) == 1

    bus.clear()

    assert bus.get_subscribers("tool.executed") == []
    assert bus.get_subscribers("llm.called") == []
    assert bus.get_subscribers("agent.run") == []


def test_exception_subscriber_logs_error():
    """A subscriber that raises should be logged via structlog (Req 13.5)."""
    from unittest.mock import patch, MagicMock

    async def bad_sub(et: str, pl: dict) -> None:
        raise ValueError("boom")

    bus.on("tool.executed", bad_sub)

    mock_logger = MagicMock()
    with patch.object(bus._log, "error", mock_logger):
        _run(bus.emit("tool.executed", {}))

    mock_logger.assert_called_once()
    call_kwargs = mock_logger.call_args
    # First positional arg is the log message
    assert "subscriber" in call_kwargs[0][0].lower() or "error" in call_kwargs[0][0].lower()


def test_exception_subscriber_does_not_prevent_other_subscribers():
    """Error isolation: other subscribers still run after one raises (Req 13.5)."""
    called: list[str] = []

    async def bad_sub(et: str, pl: dict) -> None:
        raise RuntimeError("fail")

    async def good_sub(et: str, pl: dict) -> None:
        called.append(et)

    bus.on("tool.executed", bad_sub)
    bus.on("tool.executed", good_sub)

    _run(bus.emit("tool.executed", {}))

    assert called == ["tool.executed"]


def test_all_supported_event_types_work():
    """All documented event types can be emitted and received (Req 14.1)."""
    supported = [
        "tool.executed",
        "llm.called",
        "agent.run",
        "session.started",
        "session.ended",
        "config.reloaded",
    ]
    received: list[str] = []

    async def collector(et: str, pl: dict) -> None:
        received.append(et)

    for event_type in supported:
        bus.on(event_type, collector)

    for event_type in supported:
        _run(bus.emit(event_type, {}))

    assert received == supported
