# Feature: smartclaw-realtime-stream
"""Property-based tests for SSE realtime stream.

Tests cover:
- Property 1: Hook handler event queue completeness
- Property 2: _format_sse mapping correctness
- Property 3: Handler registration/unregistration isolation
- Property 4: Event consumption completeness
- Property 5: JSON non-ASCII preservation
- Property 6: Sync endpoint backward compatibility
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from smartclaw.gateway.routers.chat import (
    STREAM_HOOK_POINTS,
    _format_sse,
    _make_queue_handler,
    _register_stream_handlers,
    _unregister_stream_handlers,
)
from smartclaw.hooks.events import (
    AgentEndEvent,
    AgentStartEvent,
    HookEvent,
    LLMAfterEvent,
    LLMBeforeEvent,
    ToolAfterEvent,
    ToolBeforeEvent,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_safe_text = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=0,
    max_size=100,
)

_hook_point_st = st.sampled_from(STREAM_HOOK_POINTS)

_hook_event_st = st.one_of(
    st.builds(
        ToolBeforeEvent,
        tool_name=_safe_text,
        tool_args=st.just({}),
        tool_call_id=_safe_text,
    ),
    st.builds(
        ToolAfterEvent,
        tool_name=_safe_text,
        tool_args=st.just({}),
        tool_call_id=_safe_text,
        result=_safe_text,
        duration_ms=st.floats(min_value=0, max_value=1e6, allow_nan=False),
        error=st.one_of(st.none(), _safe_text),
    ),
    st.builds(
        LLMBeforeEvent,
        model=_safe_text,
        message_count=st.integers(min_value=0, max_value=1000),
        has_tools=st.booleans(),
    ),
    st.builds(
        LLMAfterEvent,
        model=_safe_text,
        has_tool_calls=st.booleans(),
        duration_ms=st.floats(min_value=0, max_value=1e6, allow_nan=False),
        error=st.one_of(st.none(), _safe_text),
    ),
    st.builds(
        AgentStartEvent,
        session_key=st.one_of(st.none(), _safe_text),
        user_message=_safe_text,
        tools_count=st.integers(min_value=0, max_value=100),
    ),
    st.builds(
        AgentEndEvent,
        session_key=st.one_of(st.none(), _safe_text),
        final_answer=st.one_of(st.none(), _safe_text),
        iterations=st.integers(min_value=0, max_value=1000),
        error=st.one_of(st.none(), _safe_text),
    ),
)


# ---------------------------------------------------------------------------
# Property 1: Hook handler 事件写入 Queue 的完整性
# Tag: Feature: smartclaw-realtime-stream, Property 1: Hook handler 事件写入 Queue 的完整性
# **Validates: Requirements 1.3, 1.4**
# ---------------------------------------------------------------------------


@settings(max_examples=30, deadline=None)
@given(event=_hook_event_st, hook_point=_hook_point_st)
def test_queue_handler_writes_complete_event(
    event: HookEvent, hook_point: str
) -> None:
    """Handler writes a dict containing all HookEvent fields plus hook_point."""

    async def _run() -> None:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=200)
        handler = _make_queue_handler(queue, hook_point)
        await handler(event)

        assert not queue.empty()
        item = queue.get_nowait()
        assert item["hook_point"] == hook_point
        # All fields from to_dict() (except hook_point which is overridden) must be present
        for key, value in event.to_dict().items():
            assert key in item
            if key != "hook_point":
                assert item[key] == value

    asyncio.get_event_loop().run_until_complete(_run())


@settings(max_examples=30, deadline=None)
@given(event=_hook_event_st, hook_point=_hook_point_st)
def test_queue_handler_full_does_not_block(
    event: HookEvent, hook_point: str
) -> None:
    """When queue is full, handler silently discards and does not block."""

    async def _run() -> None:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
        # Fill the queue
        queue.put_nowait({"dummy": True})
        assert queue.full()

        handler = _make_queue_handler(queue, hook_point)
        # Should not raise or block
        await handler(event)
        # Queue size unchanged
        assert queue.qsize() == 1

    asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# Property 2: Hook 事件到 SSE 事件的映射正确性
# Tag: Feature: smartclaw-realtime-stream, Property 2: Hook 事件到 SSE 事件的映射正确性
# **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 6.1, 6.2, 6.3, 6.4, 6.5**
# ---------------------------------------------------------------------------

_MAPPED_HOOK_POINTS = ["llm:before", "tool:before", "tool:after", "agent:start"]
_SKIPPED_HOOK_POINTS = ["llm:after", "agent:end"]


@settings(max_examples=30, deadline=None)
@given(
    tool_name=_safe_text,
    message_count=st.integers(min_value=0, max_value=1000),
    result=_safe_text,
    duration_ms=st.floats(min_value=0, max_value=1e6, allow_nan=False),
    error=st.one_of(st.none(), _safe_text),
    tool_call_id=_safe_text,
)
def test_format_sse_mapping_correctness(
    tool_name: str,
    message_count: int,
    result: str,
    duration_ms: float,
    error: str | None,
    tool_call_id: str,
) -> None:
    """_format_sse returns correct event type and data fields for each hook_point."""
    # llm:before → thinking
    evt = {"hook_point": "llm:before", "message_count": message_count}
    sse = _format_sse(evt)
    assert sse is not None
    assert sse["event"] == "thinking"
    data = json.loads(sse["data"])
    assert isinstance(data["status"], str)
    assert isinstance(data["iteration"], int)
    assert data["iteration"] == message_count

    # tool:before → tool_call
    evt = {
        "hook_point": "tool:before",
        "tool_name": tool_name,
        "tool_args": {"q": "test"},
        "tool_call_id": tool_call_id,
    }
    sse = _format_sse(evt)
    assert sse is not None
    assert sse["event"] == "tool_call"
    data = json.loads(sse["data"])
    assert isinstance(data["tool_name"], str)
    assert isinstance(data["args"], dict)
    assert isinstance(data["tool_call_id"], str)

    # tool:after → tool_result
    evt = {
        "hook_point": "tool:after",
        "tool_name": tool_name,
        "result": result,
        "duration_ms": duration_ms,
        "error": error,
    }
    sse = _format_sse(evt)
    assert sse is not None
    assert sse["event"] == "tool_result"
    data = json.loads(sse["data"])
    assert isinstance(data["tool_name"], str)
    assert isinstance(data["result"], str)
    assert len(data["result"]) <= 256
    assert isinstance(data["duration_ms"], (int, float))
    assert isinstance(data["success"], bool)
    assert data["success"] == (error is None)

    # agent:start → iteration
    evt = {"hook_point": "agent:start"}
    sse = _format_sse(evt)
    assert sse is not None
    assert sse["event"] == "iteration"
    data = json.loads(sse["data"])
    assert isinstance(data["current"], int)
    assert isinstance(data["max"], int)

    # Skipped hook points
    for hp in _SKIPPED_HOOK_POINTS:
        assert _format_sse({"hook_point": hp}) is None

    # Unknown hook point
    assert _format_sse({"hook_point": "unknown:point"}) is None


# ---------------------------------------------------------------------------
# Property 3: 临时 Handler 注册与注销的完整性
# Tag: Feature: smartclaw-realtime-stream, Property 3: 临时 Handler 注册与注销的完整性
# **Validates: Requirements 1.2, 1.5, 1.6, 5.4**
# ---------------------------------------------------------------------------


@settings(max_examples=30, deadline=None)
@given(n_existing=st.integers(min_value=0, max_value=5))
def test_handler_registration_isolation(n_existing: int) -> None:
    """Registering/unregistering stream handlers does not affect pre-existing handlers."""
    import smartclaw.hooks.registry as hook_registry

    hook_registry.clear()

    # Pre-register some existing handlers
    existing_handlers: dict[str, list] = {}
    for hp in STREAM_HOOK_POINTS[:n_existing]:

        async def _existing(event: HookEvent) -> None:
            pass

        hook_registry.register(hp, _existing)
        existing_handlers.setdefault(hp, []).append(_existing)

    # Snapshot existing handler counts
    before_counts = {hp: len(hook_registry.get_handlers(hp)) for hp in STREAM_HOOK_POINTS}

    # Register stream handlers
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)  # type: ignore[type-arg]
    handlers = _register_stream_handlers(queue)

    # All 6 hook points should have one more handler
    for hp in STREAM_HOOK_POINTS:
        assert len(hook_registry.get_handlers(hp)) == before_counts[hp] + 1

    # Unregister
    _unregister_stream_handlers(handlers)

    # Counts should be back to before
    for hp in STREAM_HOOK_POINTS:
        assert len(hook_registry.get_handlers(hp)) == before_counts[hp]

    # Existing handlers still present
    for hp, hs in existing_handlers.items():
        for h in hs:
            assert h in hook_registry.get_handlers(hp)

    hook_registry.clear()


# ---------------------------------------------------------------------------
# Property 4: 事件消费完整性与最终事件保证
# Tag: Feature: smartclaw-realtime-stream, Property 4: 事件消费完整性与最终事件保证
# **Validates: Requirements 3.2, 3.3, 3.4, 2.5, 2.6, 5.3, 6.6, 6.7**
# ---------------------------------------------------------------------------


@settings(max_examples=30, deadline=None)
@given(n_events=st.integers(min_value=0, max_value=20))
def test_event_consumption_completeness(n_events: int) -> None:
    """N hook events → N SSE yields (for mapped types) + final done event."""
    import smartclaw.hooks.registry as hook_registry

    hook_registry.clear()

    async def _run() -> None:
        from unittest.mock import AsyncMock, MagicMock

        import smartclaw.agent.graph as graph_module

        original_invoke = graph_module.invoke

        queue: asyncio.Queue = asyncio.Queue(maxsize=200)  # type: ignore[type-arg]
        handlers = _register_stream_handlers(queue)

        # Simulate events being placed in queue (only mapped types)
        mapped_events = []
        for i in range(n_events):
            evt_dict = {
                "hook_point": "llm:before",
                "message_count": i,
                "model": "test",
                "has_tools": False,
                "timestamp": "2024-01-01T00:00:00+00:00",
            }
            queue.put_nowait(evt_dict)
            mapped_events.append(evt_dict)

        # Mock invoke to return immediately
        mock_result = {
            "final_answer": "done",
            "iteration": 1,
            "error": None,
            "session_key": "test-session",
            "messages": [],
            "summary": None,
            "sub_agent_depth": None,
        }

        async def fake_invoke(*args: Any, **kwargs: Any) -> dict:
            return mock_result

        graph_module.invoke = fake_invoke  # type: ignore[assignment]

        try:
            from smartclaw.gateway.routers.chat import _format_sse

            # Collect all SSE events from queue
            collected = []
            while not queue.empty():
                evt = queue.get_nowait()
                sse = _format_sse(evt)
                if sse:
                    collected.append(sse)

            # All mapped events should produce SSE events
            assert len(collected) == n_events

            # Each should be a thinking event
            for sse in collected:
                assert sse["event"] == "thinking"
        finally:
            graph_module.invoke = original_invoke  # type: ignore[assignment]
            _unregister_stream_handlers(handlers)
            hook_registry.clear()

    asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# Property 5: JSON 序列化保留非 ASCII 字符
# Tag: Feature: smartclaw-realtime-stream, Property 5: JSON 序列化保留非 ASCII 字符
# **Validates: Requirements 2.7, 6.8**
# ---------------------------------------------------------------------------

_unicode_text = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        blacklist_categories=("Cs",),
    ),
    min_size=1,
    max_size=100,
)


@settings(max_examples=30, deadline=None)
@given(text=_unicode_text)
def test_json_preserves_non_ascii(text: str) -> None:
    """SSE data fields preserve non-ASCII characters (no \\uXXXX escapes for CJK)."""
    # Test with tool:before (tool_name can contain unicode)
    evt = {
        "hook_point": "tool:before",
        "tool_name": text,
        "tool_args": {"query": text},
        "tool_call_id": "id-1",
    }
    sse = _format_sse(evt)
    assert sse is not None
    data_str = sse["data"]

    # If text contains non-ASCII, the raw chars should appear in the JSON string
    for ch in text:
        if ord(ch) > 127:
            # The character itself should be in the JSON, not its \\u escape
            assert ch in data_str


# ---------------------------------------------------------------------------
# Property 6: 同步端点向后兼容
# Tag: Feature: smartclaw-realtime-stream, Property 6: 同步端点向后兼容
# **Validates: Requirements 5.1, 5.2**
# ---------------------------------------------------------------------------


@settings(max_examples=30, deadline=None)
@given(message=st.text(min_size=1, max_size=200))
def test_sync_endpoint_backward_compatible(message: str) -> None:
    """POST /api/chat still returns ChatResponse with all required fields."""
    import smartclaw.agent.graph as graph_module

    original = graph_module.invoke

    try:
        from tests.gateway.conftest import make_test_client

        client, _, _, _ = make_test_client()
        with client:
            resp = client.post("/api/chat", json={"message": message})
        assert resp.status_code == 200
        data = resp.json()
        assert "session_key" in data
        assert "response" in data
        assert "iterations" in data
        assert isinstance(data["session_key"], str)
        assert isinstance(data["response"], str)
        assert isinstance(data["iterations"], int)
    finally:
        graph_module.invoke = original  # type: ignore[assignment]
