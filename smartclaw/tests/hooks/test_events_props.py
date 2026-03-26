# Feature: smartclaw-p2a-production-services, Property 12: HookEvent 子类包含必需字段
# Feature: smartclaw-p2a-production-services, Property 13: HookEvent 序列化往返
"""Property-based tests for HookEvent subclasses.

Uses hypothesis with @settings(max_examples=100, deadline=None).

Property 12: For each HookEvent subclass, to_dict() contains all required fields
             and timestamp is valid ISO 8601.
Property 13: HookEvent.from_dict(event.to_dict()) produces equivalent object.

**Validates: Requirements 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 12.1, 12.2, 12.3**
"""

from __future__ import annotations

from datetime import datetime, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

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

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_text_st = st.text(min_size=0, max_size=50)
_nonempty_text_st = st.text(min_size=1, max_size=50)
_bool_st = st.booleans()
_float_st = st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False)
_int_st = st.integers(min_value=0, max_value=1000)
_opt_text_st = st.one_of(st.none(), _text_st)
_dict_st = st.fixed_dictionaries({})  # simple empty dict for tool_args


@st.composite
def tool_before_event_st(draw: st.DrawFn) -> ToolBeforeEvent:
    return ToolBeforeEvent(
        tool_name=draw(_text_st),
        tool_args=draw(st.fixed_dictionaries({})),
        tool_call_id=draw(_text_st),
    )


@st.composite
def tool_after_event_st(draw: st.DrawFn) -> ToolAfterEvent:
    return ToolAfterEvent(
        tool_name=draw(_text_st),
        tool_args=draw(st.fixed_dictionaries({})),
        tool_call_id=draw(_text_st),
        result=draw(_text_st),
        duration_ms=draw(_float_st),
        error=draw(_opt_text_st),
    )


@st.composite
def agent_start_event_st(draw: st.DrawFn) -> AgentStartEvent:
    return AgentStartEvent(
        session_key=draw(_opt_text_st),
        user_message=draw(_text_st),
        tools_count=draw(_int_st),
    )


@st.composite
def agent_end_event_st(draw: st.DrawFn) -> AgentEndEvent:
    return AgentEndEvent(
        session_key=draw(_opt_text_st),
        final_answer=draw(_opt_text_st),
        iterations=draw(_int_st),
        error=draw(_opt_text_st),
    )


@st.composite
def llm_before_event_st(draw: st.DrawFn) -> LLMBeforeEvent:
    return LLMBeforeEvent(
        model=draw(_text_st),
        message_count=draw(_int_st),
        has_tools=draw(_bool_st),
    )


@st.composite
def llm_after_event_st(draw: st.DrawFn) -> LLMAfterEvent:
    return LLMAfterEvent(
        model=draw(_text_st),
        has_tool_calls=draw(_bool_st),
        duration_ms=draw(_float_st),
        error=draw(_opt_text_st),
    )


@st.composite
def session_start_event_st(draw: st.DrawFn) -> SessionStartEvent:
    return SessionStartEvent(session_key=draw(_text_st))


@st.composite
def session_end_event_st(draw: st.DrawFn) -> SessionEndEvent:
    return SessionEndEvent(session_key=draw(_text_st))


def _is_valid_iso8601(ts: str) -> bool:
    """Return True if ts is a valid ISO 8601 datetime string."""
    try:
        datetime.fromisoformat(ts)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Property 12: HookEvent 子类包含必需字段
# ---------------------------------------------------------------------------


# Feature: smartclaw-p2a-production-services, Property 12: HookEvent 子类包含必需字段
@given(event=tool_before_event_st())
@settings(max_examples=100, deadline=None)
def test_tool_before_event_required_fields(event: ToolBeforeEvent) -> None:
    """ToolBeforeEvent.to_dict() contains all required fields with valid timestamp.

    **Validates: Requirements 10.2**
    """
    d = event.to_dict()
    assert "hook_point" in d
    assert "timestamp" in d
    assert "tool_name" in d
    assert "tool_args" in d
    assert "tool_call_id" in d
    assert d["hook_point"] == "tool:before"
    assert _is_valid_iso8601(d["timestamp"])


# Feature: smartclaw-p2a-production-services, Property 12: HookEvent 子类包含必需字段
@given(event=tool_after_event_st())
@settings(max_examples=100, deadline=None)
def test_tool_after_event_required_fields(event: ToolAfterEvent) -> None:
    """ToolAfterEvent.to_dict() contains all required fields with valid timestamp.

    **Validates: Requirements 10.3**
    """
    d = event.to_dict()
    assert "hook_point" in d
    assert "timestamp" in d
    assert "tool_name" in d
    assert "tool_args" in d
    assert "tool_call_id" in d
    assert "result" in d
    assert "duration_ms" in d
    assert "error" in d
    assert d["hook_point"] == "tool:after"
    assert _is_valid_iso8601(d["timestamp"])


# Feature: smartclaw-p2a-production-services, Property 12: HookEvent 子类包含必需字段
@given(event=agent_start_event_st())
@settings(max_examples=100, deadline=None)
def test_agent_start_event_required_fields(event: AgentStartEvent) -> None:
    """AgentStartEvent.to_dict() contains all required fields with valid timestamp.

    **Validates: Requirements 10.4**
    """
    d = event.to_dict()
    assert "hook_point" in d
    assert "timestamp" in d
    assert "session_key" in d
    assert "user_message" in d
    assert "tools_count" in d
    assert d["hook_point"] == "agent:start"
    assert _is_valid_iso8601(d["timestamp"])


# Feature: smartclaw-p2a-production-services, Property 12: HookEvent 子类包含必需字段
@given(event=agent_end_event_st())
@settings(max_examples=100, deadline=None)
def test_agent_end_event_required_fields(event: AgentEndEvent) -> None:
    """AgentEndEvent.to_dict() contains all required fields with valid timestamp.

    **Validates: Requirements 10.5**
    """
    d = event.to_dict()
    assert "hook_point" in d
    assert "timestamp" in d
    assert "session_key" in d
    assert "final_answer" in d
    assert "iterations" in d
    assert "error" in d
    assert d["hook_point"] == "agent:end"
    assert _is_valid_iso8601(d["timestamp"])


# Feature: smartclaw-p2a-production-services, Property 12: HookEvent 子类包含必需字段
@given(event=llm_before_event_st())
@settings(max_examples=100, deadline=None)
def test_llm_before_event_required_fields(event: LLMBeforeEvent) -> None:
    """LLMBeforeEvent.to_dict() contains all required fields with valid timestamp.

    **Validates: Requirements 10.6**
    """
    d = event.to_dict()
    assert "hook_point" in d
    assert "timestamp" in d
    assert "model" in d
    assert "message_count" in d
    assert "has_tools" in d
    assert d["hook_point"] == "llm:before"
    assert _is_valid_iso8601(d["timestamp"])


# Feature: smartclaw-p2a-production-services, Property 12: HookEvent 子类包含必需字段
@given(event=llm_after_event_st())
@settings(max_examples=100, deadline=None)
def test_llm_after_event_required_fields(event: LLMAfterEvent) -> None:
    """LLMAfterEvent.to_dict() contains all required fields with valid timestamp.

    **Validates: Requirements 10.7**
    """
    d = event.to_dict()
    assert "hook_point" in d
    assert "timestamp" in d
    assert "model" in d
    assert "has_tool_calls" in d
    assert "duration_ms" in d
    assert "error" in d
    assert d["hook_point"] == "llm:after"
    assert _is_valid_iso8601(d["timestamp"])


# Feature: smartclaw-p2a-production-services, Property 12: HookEvent 子类包含必需字段
@given(event=session_start_event_st())
@settings(max_examples=100, deadline=None)
def test_session_start_event_required_fields(event: SessionStartEvent) -> None:
    """SessionStartEvent.to_dict() contains all required fields with valid timestamp.

    **Validates: Requirements 10.8**
    """
    d = event.to_dict()
    assert "hook_point" in d
    assert "timestamp" in d
    assert "session_key" in d
    assert d["hook_point"] == "session:start"
    assert _is_valid_iso8601(d["timestamp"])


# Feature: smartclaw-p2a-production-services, Property 12: HookEvent 子类包含必需字段
@given(event=session_end_event_st())
@settings(max_examples=100, deadline=None)
def test_session_end_event_required_fields(event: SessionEndEvent) -> None:
    """SessionEndEvent.to_dict() contains all required fields with valid timestamp.

    **Validates: Requirements 10.8**
    """
    d = event.to_dict()
    assert "hook_point" in d
    assert "timestamp" in d
    assert "session_key" in d
    assert d["hook_point"] == "session:end"
    assert _is_valid_iso8601(d["timestamp"])


# ---------------------------------------------------------------------------
# Property 13: HookEvent 序列化往返
# ---------------------------------------------------------------------------


# Feature: smartclaw-p2a-production-services, Property 13: HookEvent 序列化往返
@given(event=tool_before_event_st())
@settings(max_examples=100, deadline=None)
def test_tool_before_event_roundtrip(event: ToolBeforeEvent) -> None:
    """ToolBeforeEvent round-trip: from_dict(to_dict()) == original.

    **Validates: Requirements 12.1, 12.2, 12.3**
    """
    restored = HookEvent.from_dict(event.to_dict())
    assert restored == event


# Feature: smartclaw-p2a-production-services, Property 13: HookEvent 序列化往返
@given(event=tool_after_event_st())
@settings(max_examples=100, deadline=None)
def test_tool_after_event_roundtrip(event: ToolAfterEvent) -> None:
    """ToolAfterEvent round-trip: from_dict(to_dict()) == original.

    **Validates: Requirements 12.1, 12.2, 12.3**
    """
    restored = HookEvent.from_dict(event.to_dict())
    assert restored == event


# Feature: smartclaw-p2a-production-services, Property 13: HookEvent 序列化往返
@given(event=agent_start_event_st())
@settings(max_examples=100, deadline=None)
def test_agent_start_event_roundtrip(event: AgentStartEvent) -> None:
    """AgentStartEvent round-trip: from_dict(to_dict()) == original.

    **Validates: Requirements 12.1, 12.2, 12.3**
    """
    restored = HookEvent.from_dict(event.to_dict())
    assert restored == event


# Feature: smartclaw-p2a-production-services, Property 13: HookEvent 序列化往返
@given(event=agent_end_event_st())
@settings(max_examples=100, deadline=None)
def test_agent_end_event_roundtrip(event: AgentEndEvent) -> None:
    """AgentEndEvent round-trip: from_dict(to_dict()) == original.

    **Validates: Requirements 12.1, 12.2, 12.3**
    """
    restored = HookEvent.from_dict(event.to_dict())
    assert restored == event


# Feature: smartclaw-p2a-production-services, Property 13: HookEvent 序列化往返
@given(event=llm_before_event_st())
@settings(max_examples=100, deadline=None)
def test_llm_before_event_roundtrip(event: LLMBeforeEvent) -> None:
    """LLMBeforeEvent round-trip: from_dict(to_dict()) == original.

    **Validates: Requirements 12.1, 12.2, 12.3**
    """
    restored = HookEvent.from_dict(event.to_dict())
    assert restored == event


# Feature: smartclaw-p2a-production-services, Property 13: HookEvent 序列化往返
@given(event=llm_after_event_st())
@settings(max_examples=100, deadline=None)
def test_llm_after_event_roundtrip(event: LLMAfterEvent) -> None:
    """LLMAfterEvent round-trip: from_dict(to_dict()) == original.

    **Validates: Requirements 12.1, 12.2, 12.3**
    """
    restored = HookEvent.from_dict(event.to_dict())
    assert restored == event


# Feature: smartclaw-p2a-production-services, Property 13: HookEvent 序列化往返
@given(event=session_start_event_st())
@settings(max_examples=100, deadline=None)
def test_session_start_event_roundtrip(event: SessionStartEvent) -> None:
    """SessionStartEvent round-trip: from_dict(to_dict()) == original.

    **Validates: Requirements 12.1, 12.2, 12.3**
    """
    restored = HookEvent.from_dict(event.to_dict())
    assert restored == event


# Feature: smartclaw-p2a-production-services, Property 13: HookEvent 序列化往返
@given(event=session_end_event_st())
@settings(max_examples=100, deadline=None)
def test_session_end_event_roundtrip(event: SessionEndEvent) -> None:
    """SessionEndEvent round-trip: from_dict(to_dict()) == original.

    **Validates: Requirements 12.1, 12.2, 12.3**
    """
    restored = HookEvent.from_dict(event.to_dict())
    assert restored == event
