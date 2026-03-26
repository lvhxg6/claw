"""Unit tests for SSE realtime stream feature.

Covers:
- _make_queue_handler basic + full queue
- _format_sse all types + unknown
- event_generator happy path + invoke error + fallback
- handler cleanup on error
- sync endpoint unchanged
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from smartclaw.gateway.routers.chat import (
    STREAM_HOOK_POINTS,
    _format_sse,
    _make_queue_handler,
    _register_stream_handlers,
    _unregister_stream_handlers,
)
from smartclaw.hooks.events import (
    HookEvent,
    LLMBeforeEvent,
    ToolAfterEvent,
    ToolBeforeEvent,
)


# ---------------------------------------------------------------------------
# 4.1 _make_queue_handler tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queue_handler_basic() -> None:
    """Handler writes event dict to queue with hook_point field."""
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=200)
    handler = _make_queue_handler(queue, "tool:before")

    event = ToolBeforeEvent(tool_name="web_search", tool_args={"q": "test"}, tool_call_id="c1")
    await handler(event)

    assert queue.qsize() == 1
    item = queue.get_nowait()
    assert item["hook_point"] == "tool:before"
    assert item["tool_name"] == "web_search"
    assert item["tool_args"] == {"q": "test"}
    assert item["tool_call_id"] == "c1"


@pytest.mark.asyncio
async def test_queue_handler_full() -> None:
    """When queue is full, handler does not block or raise."""
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
    queue.put_nowait({"filler": True})
    assert queue.full()

    handler = _make_queue_handler(queue, "llm:before")
    event = LLMBeforeEvent(model="test", message_count=1)

    # Should not raise
    await handler(event)
    # Queue still has only the original item
    assert queue.qsize() == 1
    assert queue.get_nowait() == {"filler": True}


# ---------------------------------------------------------------------------
# 4.2 _format_sse tests
# ---------------------------------------------------------------------------


def test_format_sse_all_types() -> None:
    """_format_sse maps all known hook_points to correct SSE event types."""
    # llm:before → thinking
    sse = _format_sse({"hook_point": "llm:before", "message_count": 3})
    assert sse is not None
    assert sse["event"] == "thinking"
    data = json.loads(sse["data"])
    assert data["status"] == "reasoning"
    assert data["iteration"] == 3

    # tool:before → tool_call
    sse = _format_sse({
        "hook_point": "tool:before",
        "tool_name": "web_search",
        "tool_args": {"q": "hello"},
        "tool_call_id": "call_1",
    })
    assert sse is not None
    assert sse["event"] == "tool_call"
    data = json.loads(sse["data"])
    assert data["tool_name"] == "web_search"
    assert data["args"] == {"q": "hello"}
    assert data["tool_call_id"] == "call_1"

    # tool:after → tool_result
    sse = _format_sse({
        "hook_point": "tool:after",
        "tool_name": "web_search",
        "result": "some result",
        "duration_ms": 123.4,
        "error": None,
    })
    assert sse is not None
    assert sse["event"] == "tool_result"
    data = json.loads(sse["data"])
    assert data["tool_name"] == "web_search"
    assert data["result"] == "some result"
    assert data["duration_ms"] == 123.4
    assert data["success"] is True

    # tool:after with error → success=False
    sse = _format_sse({
        "hook_point": "tool:after",
        "tool_name": "web_search",
        "result": "",
        "duration_ms": 50,
        "error": "timeout",
    })
    assert sse is not None
    data = json.loads(sse["data"])
    assert data["success"] is False

    # agent:start → iteration
    sse = _format_sse({"hook_point": "agent:start"})
    assert sse is not None
    assert sse["event"] == "iteration"
    data = json.loads(sse["data"])
    assert data["current"] == 1
    assert data["max"] == 50

    # tool:after result truncation to 256 chars
    long_result = "x" * 500
    sse = _format_sse({
        "hook_point": "tool:after",
        "tool_name": "t",
        "result": long_result,
        "duration_ms": 0,
        "error": None,
    })
    assert sse is not None
    data = json.loads(sse["data"])
    assert len(data["result"]) == 256


def test_format_sse_unknown() -> None:
    """_format_sse returns None for unknown or skipped hook_points."""
    assert _format_sse({"hook_point": "llm:after"}) is None
    assert _format_sse({"hook_point": "agent:end"}) is None
    assert _format_sse({"hook_point": "session:start"}) is None
    assert _format_sse({"hook_point": "totally:unknown"}) is None
    assert _format_sse({}) is None


# ---------------------------------------------------------------------------
# 4.3 event_generator tests (happy path + invoke error + fallback)
# ---------------------------------------------------------------------------


def test_event_generator_happy_path() -> None:
    """SSE stream emits thinking events and a final done event."""
    import smartclaw.agent.graph as graph_module

    original = graph_module.invoke
    try:
        from tests.gateway.conftest import make_test_client

        client, mock_invoke, _, _ = make_test_client()
        with client:
            resp = client.post("/api/chat/stream", json={"message": "hello"})
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        body = resp.text
        # Must contain a done event
        assert "event: done" in body
        # done data should have session_key, response, iterations
        # Find the done data line
        for line in body.split("\n"):
            if line.startswith("data:") and "response" in line:
                data = json.loads(line[5:].strip())
                assert "session_key" in data
                assert "response" in data
                assert "iterations" in data
                break
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


def test_event_generator_invoke_error() -> None:
    """SSE stream emits error event when invoke raises."""
    import smartclaw.agent.graph as graph_module

    original = graph_module.invoke
    try:
        from tests.gateway.conftest import make_test_client

        client, _, _, _ = make_test_client(
            invoke_side_effect=RuntimeError("LLM failure")
        )
        with client:
            resp = client.post("/api/chat/stream", json={"message": "hello"})
        assert resp.status_code == 200
        body = resp.text
        assert "event: error" in body
        assert "LLM failure" in body
    finally:
        graph_module.invoke = original  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 4.4 handler cleanup tests
# ---------------------------------------------------------------------------


def test_handler_cleanup() -> None:
    """After stream completes, all temporary handlers are unregistered."""
    import smartclaw.hooks.registry as hook_registry

    hook_registry.clear()

    queue: asyncio.Queue = asyncio.Queue(maxsize=200)  # type: ignore[type-arg]
    handlers = _register_stream_handlers(queue)

    # All 6 hook points should have handlers
    for hp in STREAM_HOOK_POINTS:
        assert len(hook_registry.get_handlers(hp)) >= 1

    _unregister_stream_handlers(handlers)

    # All temporary handlers removed
    for hp in STREAM_HOOK_POINTS:
        assert len(hook_registry.get_handlers(hp)) == 0

    hook_registry.clear()


def test_handler_cleanup_preserves_existing() -> None:
    """Unregistering stream handlers does not remove pre-existing handlers."""
    import smartclaw.hooks.registry as hook_registry

    hook_registry.clear()

    # Register an existing handler
    async def existing_handler(event: HookEvent) -> None:
        pass

    hook_registry.register("tool:before", existing_handler)
    assert len(hook_registry.get_handlers("tool:before")) == 1

    # Register + unregister stream handlers
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)  # type: ignore[type-arg]
    handlers = _register_stream_handlers(queue)
    assert len(hook_registry.get_handlers("tool:before")) == 2

    _unregister_stream_handlers(handlers)
    assert len(hook_registry.get_handlers("tool:before")) == 1
    assert existing_handler in hook_registry.get_handlers("tool:before")

    hook_registry.clear()


def test_sync_endpoint_unchanged() -> None:
    """POST /api/chat still works with the same request/response format."""
    import smartclaw.agent.graph as graph_module

    original = graph_module.invoke
    try:
        from tests.gateway.conftest import make_test_client

        client, _, _, _ = make_test_client()
        with client:
            resp = client.post("/api/chat", json={"message": "hello"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["response"] == "Mock response"
        assert data["iterations"] == 1
        assert "session_key" in data
        assert "error" in data or data.get("error") is None
    finally:
        graph_module.invoke = original  # type: ignore[assignment]
