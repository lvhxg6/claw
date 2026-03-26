"""Unit tests for HookEvent subclasses.

Tests cover:
- Each event type construction with specific values (Req 10.2–10.8)
- to_dict() returns correct keys
- from_dict() round-trip with specific examples (Req 12.1, 12.2)
- timestamp is auto-generated as ISO 8601

Requirements: 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 12.1, 12.2
"""

from __future__ import annotations

from datetime import datetime

import pytest

from smartclaw.hooks.events import (
    AgentEndEvent,
    AgentStartEvent,
    HookEvent,
    LLMAfterEvent,
    LLMBeforeEvent,
    SessionEndEvent,
    SessionStartEvent,
    ToolAfterEvent,
    ToolBeforeEvent,
)


def _is_valid_iso8601(ts: str) -> bool:
    try:
        datetime.fromisoformat(ts)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# ToolBeforeEvent
# ---------------------------------------------------------------------------


class TestToolBeforeEvent:
    def test_construction_with_values(self) -> None:
        e = ToolBeforeEvent(tool_name="search", tool_args={"q": "test"}, tool_call_id="abc")
        assert e.hook_point == "tool:before"
        assert e.tool_name == "search"
        assert e.tool_args == {"q": "test"}
        assert e.tool_call_id == "abc"

    def test_to_dict_keys(self) -> None:
        e = ToolBeforeEvent(tool_name="search", tool_args={}, tool_call_id="id1")
        d = e.to_dict()
        assert set(d.keys()) == {"hook_point", "timestamp", "tool_name", "tool_args", "tool_call_id"}

    def test_from_dict_roundtrip(self) -> None:
        e = ToolBeforeEvent(tool_name="calc", tool_args={"x": 1}, tool_call_id="c1")
        assert HookEvent.from_dict(e.to_dict()) == e

    def test_timestamp_is_iso8601(self) -> None:
        e = ToolBeforeEvent()
        assert _is_valid_iso8601(e.timestamp)


# ---------------------------------------------------------------------------
# ToolAfterEvent
# ---------------------------------------------------------------------------


class TestToolAfterEvent:
    def test_construction_with_values(self) -> None:
        e = ToolAfterEvent(
            tool_name="search",
            tool_args={"q": "test"},
            tool_call_id="abc",
            result="found",
            duration_ms=42.5,
            error=None,
        )
        assert e.hook_point == "tool:after"
        assert e.tool_name == "search"
        assert e.result == "found"
        assert e.duration_ms == 42.5
        assert e.error is None

    def test_to_dict_keys(self) -> None:
        e = ToolAfterEvent()
        d = e.to_dict()
        assert "result" in d
        assert "duration_ms" in d
        assert "error" in d

    def test_from_dict_roundtrip(self) -> None:
        e = ToolAfterEvent(tool_name="t", result="ok", duration_ms=1.0, error="oops")
        assert HookEvent.from_dict(e.to_dict()) == e

    def test_timestamp_is_iso8601(self) -> None:
        e = ToolAfterEvent()
        assert _is_valid_iso8601(e.timestamp)


# ---------------------------------------------------------------------------
# AgentStartEvent
# ---------------------------------------------------------------------------


class TestAgentStartEvent:
    def test_construction_with_values(self) -> None:
        e = AgentStartEvent(session_key="sess-1", user_message="hello", tools_count=3)
        assert e.hook_point == "agent:start"
        assert e.session_key == "sess-1"
        assert e.user_message == "hello"
        assert e.tools_count == 3

    def test_to_dict_keys(self) -> None:
        e = AgentStartEvent()
        d = e.to_dict()
        assert "session_key" in d
        assert "user_message" in d
        assert "tools_count" in d

    def test_from_dict_roundtrip(self) -> None:
        e = AgentStartEvent(session_key="s", user_message="hi", tools_count=2)
        assert HookEvent.from_dict(e.to_dict()) == e

    def test_timestamp_is_iso8601(self) -> None:
        e = AgentStartEvent()
        assert _is_valid_iso8601(e.timestamp)


# ---------------------------------------------------------------------------
# AgentEndEvent
# ---------------------------------------------------------------------------


class TestAgentEndEvent:
    def test_construction_with_values(self) -> None:
        e = AgentEndEvent(session_key="s1", final_answer="done", iterations=5, error=None)
        assert e.hook_point == "agent:end"
        assert e.final_answer == "done"
        assert e.iterations == 5

    def test_to_dict_keys(self) -> None:
        e = AgentEndEvent()
        d = e.to_dict()
        assert "final_answer" in d
        assert "iterations" in d
        assert "error" in d

    def test_from_dict_roundtrip(self) -> None:
        e = AgentEndEvent(session_key="s", final_answer="ans", iterations=3, error="err")
        assert HookEvent.from_dict(e.to_dict()) == e

    def test_timestamp_is_iso8601(self) -> None:
        e = AgentEndEvent()
        assert _is_valid_iso8601(e.timestamp)


# ---------------------------------------------------------------------------
# LLMBeforeEvent
# ---------------------------------------------------------------------------


class TestLLMBeforeEvent:
    def test_construction_with_values(self) -> None:
        e = LLMBeforeEvent(model="gpt-4", message_count=5, has_tools=True)
        assert e.hook_point == "llm:before"
        assert e.model == "gpt-4"
        assert e.message_count == 5
        assert e.has_tools is True

    def test_to_dict_keys(self) -> None:
        e = LLMBeforeEvent()
        d = e.to_dict()
        assert "model" in d
        assert "message_count" in d
        assert "has_tools" in d

    def test_from_dict_roundtrip(self) -> None:
        e = LLMBeforeEvent(model="claude", message_count=2, has_tools=False)
        assert HookEvent.from_dict(e.to_dict()) == e

    def test_timestamp_is_iso8601(self) -> None:
        e = LLMBeforeEvent()
        assert _is_valid_iso8601(e.timestamp)


# ---------------------------------------------------------------------------
# LLMAfterEvent
# ---------------------------------------------------------------------------


class TestLLMAfterEvent:
    def test_construction_with_values(self) -> None:
        e = LLMAfterEvent(model="gpt-4", has_tool_calls=True, duration_ms=200.0, error=None)
        assert e.hook_point == "llm:after"
        assert e.has_tool_calls is True
        assert e.duration_ms == 200.0

    def test_to_dict_keys(self) -> None:
        e = LLMAfterEvent()
        d = e.to_dict()
        assert "model" in d
        assert "has_tool_calls" in d
        assert "duration_ms" in d
        assert "error" in d

    def test_from_dict_roundtrip(self) -> None:
        e = LLMAfterEvent(model="m", has_tool_calls=False, duration_ms=10.0, error="timeout")
        assert HookEvent.from_dict(e.to_dict()) == e

    def test_timestamp_is_iso8601(self) -> None:
        e = LLMAfterEvent()
        assert _is_valid_iso8601(e.timestamp)


# ---------------------------------------------------------------------------
# SessionStartEvent
# ---------------------------------------------------------------------------


class TestSessionStartEvent:
    def test_construction_with_values(self) -> None:
        e = SessionStartEvent(session_key="sess-abc")
        assert e.hook_point == "session:start"
        assert e.session_key == "sess-abc"

    def test_to_dict_keys(self) -> None:
        e = SessionStartEvent(session_key="x")
        d = e.to_dict()
        assert "session_key" in d
        assert "hook_point" in d
        assert "timestamp" in d

    def test_from_dict_roundtrip(self) -> None:
        e = SessionStartEvent(session_key="my-session")
        assert HookEvent.from_dict(e.to_dict()) == e

    def test_timestamp_is_iso8601(self) -> None:
        e = SessionStartEvent()
        assert _is_valid_iso8601(e.timestamp)


# ---------------------------------------------------------------------------
# SessionEndEvent
# ---------------------------------------------------------------------------


class TestSessionEndEvent:
    def test_construction_with_values(self) -> None:
        e = SessionEndEvent(session_key="sess-xyz")
        assert e.hook_point == "session:end"
        assert e.session_key == "sess-xyz"

    def test_to_dict_keys(self) -> None:
        e = SessionEndEvent(session_key="y")
        d = e.to_dict()
        assert "session_key" in d
        assert "hook_point" in d
        assert "timestamp" in d

    def test_from_dict_roundtrip(self) -> None:
        e = SessionEndEvent(session_key="end-session")
        assert HookEvent.from_dict(e.to_dict()) == e

    def test_timestamp_is_iso8601(self) -> None:
        e = SessionEndEvent()
        assert _is_valid_iso8601(e.timestamp)


# ---------------------------------------------------------------------------
# from_dict: unknown hook_point raises ValueError
# ---------------------------------------------------------------------------


def test_from_dict_unknown_hook_point_raises() -> None:
    with pytest.raises(ValueError, match="Unknown hook_point"):
        HookEvent.from_dict({"hook_point": "invalid:point", "timestamp": "2024-01-01T00:00:00+00:00"})
