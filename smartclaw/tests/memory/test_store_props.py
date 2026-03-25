"""Property-based tests for MemoryStore.

Uses hypothesis with @settings(max_examples=100).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)

from smartclaw.memory.store import MemoryStore

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_session_key = st.text(min_size=1, max_size=30, alphabet=st.characters(whitelist_categories=("L", "N")))
_role = st.sampled_from(["human", "ai"])
_content = st.text(min_size=0, max_size=200)
_non_empty_content = st.text(min_size=1, max_size=200).filter(lambda s: s.strip())
_message_pair = st.tuples(_role, _content)
_message_pairs = st.lists(_message_pair, min_size=1, max_size=10)

# Strategy for tool_call dicts (matching LangChain format)
_tool_call = st.fixed_dictionaries({
    "name": st.from_regex(r"[a-z_]{1,20}", fullmatch=True),
    "args": st.fixed_dictionaries({"arg": st.text(min_size=0, max_size=20)}),
    "id": st.from_regex(r"call_[a-zA-Z0-9]{5,10}", fullmatch=True),
    "type": st.just("tool_call"),
})

_tool_call_id = st.from_regex(r"call_[a-zA-Z0-9]{5,10}", fullmatch=True)


def _base_message_strategy() -> st.SearchStrategy[BaseMessage]:
    """Strategy generating HumanMessage, AIMessage (with optional tool_calls), or ToolMessage."""
    human = _content.map(lambda c: HumanMessage(content=c))
    ai_plain = _content.map(lambda c: AIMessage(content=c))
    ai_with_tools = st.builds(
        lambda content, calls: AIMessage(content=content, tool_calls=calls),
        content=_content,
        calls=st.lists(_tool_call, min_size=1, max_size=2),
    )
    tool_msg = st.builds(
        lambda content, tcid: ToolMessage(content=content, tool_call_id=tcid),
        content=_content,
        tcid=_tool_call_id,
    )
    return st.one_of(human, ai_plain, ai_with_tools, tool_msg)


_base_message = _base_message_strategy()
_base_message_list = st.lists(_base_message, min_size=1, max_size=8)

# Counter for unique db files within a single tmp dir per test run
_counter = 0


def _next_db_path(tmp_dir: str) -> str:
    global _counter
    _counter += 1
    return str(Path(tmp_dir) / f"test_{_counter}.db")


# ---------------------------------------------------------------------------
# Property 1: Message Storage Round-Trip
# ---------------------------------------------------------------------------


# Feature: smartclaw-p1-enhanced-capabilities, Property 1: Message Storage Round-Trip
@given(data=st.data())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
async def test_message_storage_round_trip(tmp_path, data):
    """For any session_key and sequence of (role, content) pairs,
    add_message then get_history returns same order and content.

    Validates: Requirements 1.1, 1.2
    """
    session_key = data.draw(_session_key)
    pairs = data.draw(_message_pairs)

    db_path = _next_db_path(str(tmp_path))
    store = MemoryStore(db_path=db_path)
    await store.initialize()
    try:
        for role, content in pairs:
            await store.add_message(session_key, role, content)

        history = await store.get_history(session_key)

        assert len(history) == len(pairs)
        for msg, (role, content) in zip(history, pairs):
            assert msg.content == content
            if role in ("human", "user"):
                assert isinstance(msg, HumanMessage)
            else:
                assert isinstance(msg, AIMessage)
    finally:
        await store.close()


# ---------------------------------------------------------------------------
# Property 2: Full Message Serialization Round-Trip
# ---------------------------------------------------------------------------


# Feature: smartclaw-p1-enhanced-capabilities, Property 2: Full Message Serialization Round-Trip
@given(data=st.data())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
async def test_full_message_serialization_round_trip(tmp_path, data):
    """For any BaseMessage (HumanMessage, AIMessage with tool_calls,
    ToolMessage with tool_call_id), add_full_message then get_history
    returns equivalent message.

    Validates: Requirements 1.9, 1.15
    """
    session_key = data.draw(_session_key)
    message = data.draw(_base_message)

    db_path = _next_db_path(str(tmp_path))
    store = MemoryStore(db_path=db_path)
    await store.initialize()
    try:
        await store.add_full_message(session_key, message)
        history = await store.get_history(session_key)

        assert len(history) == 1
        retrieved = history[0]

        # Same type
        assert type(retrieved) is type(message)
        # Same content
        assert retrieved.content == message.content

        # Check tool_calls for AIMessage
        if isinstance(message, AIMessage) and message.tool_calls:
            assert len(retrieved.tool_calls) == len(message.tool_calls)
            for orig_tc, ret_tc in zip(message.tool_calls, retrieved.tool_calls):
                assert orig_tc["name"] == ret_tc["name"]
                assert orig_tc["args"] == ret_tc["args"]
                assert orig_tc["id"] == ret_tc["id"]

        # Check tool_call_id for ToolMessage
        if isinstance(message, ToolMessage):
            assert retrieved.tool_call_id == message.tool_call_id
    finally:
        await store.close()


# ---------------------------------------------------------------------------
# Property 3: Summary Round-Trip
# ---------------------------------------------------------------------------


# Feature: smartclaw-p1-enhanced-capabilities, Property 3: Summary Round-Trip
@given(data=st.data())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
async def test_summary_round_trip(tmp_path, data):
    """For any session_key and non-empty summary string,
    set_summary then get_summary returns exact same string.

    Validates: Requirements 1.4, 1.6
    """
    session_key = data.draw(_session_key)
    summary = data.draw(_non_empty_content)

    db_path = _next_db_path(str(tmp_path))
    store = MemoryStore(db_path=db_path)
    await store.initialize()
    try:
        await store.set_summary(session_key, summary)
        result = await store.get_summary(session_key)
        assert result == summary
    finally:
        await store.close()


# ---------------------------------------------------------------------------
# Property 4: Truncate Preserves Recent Messages
# ---------------------------------------------------------------------------


# Feature: smartclaw-p1-enhanced-capabilities, Property 4: Truncate Preserves Recent Messages
@given(data=st.data())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
async def test_truncate_preserves_recent_messages(tmp_path, data):
    """For any N messages and keep_last (1 <= keep_last < N),
    truncate_history then get_history returns exactly the last
    keep_last messages.

    Validates: Requirements 1.7
    """
    pairs = data.draw(st.lists(_message_pair, min_size=2, max_size=10))
    n = len(pairs)
    keep_last = data.draw(st.integers(min_value=1, max_value=n - 1))
    session_key = data.draw(_session_key)

    db_path = _next_db_path(str(tmp_path))
    store = MemoryStore(db_path=db_path)
    await store.initialize()
    try:
        for role, content in pairs:
            await store.add_message(session_key, role, content)

        await store.truncate_history(session_key, keep_last)
        history = await store.get_history(session_key)

        assert len(history) == keep_last
        expected_pairs = pairs[-keep_last:]
        for msg, (role, content) in zip(history, expected_pairs):
            assert msg.content == content
    finally:
        await store.close()


# ---------------------------------------------------------------------------
# Property 5: Set History Round-Trip
# ---------------------------------------------------------------------------


# Feature: smartclaw-p1-enhanced-capabilities, Property 5: Set History Round-Trip
@given(data=st.data())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
async def test_set_history_round_trip(tmp_path, data):
    """For any session_key and list of BaseMessage objects,
    set_history then get_history returns equivalent list.

    Validates: Requirements 1.10
    """
    session_key = data.draw(_session_key)
    messages = data.draw(_base_message_list)

    db_path = _next_db_path(str(tmp_path))
    store = MemoryStore(db_path=db_path)
    await store.initialize()
    try:
        await store.set_history(session_key, messages)
        history = await store.get_history(session_key)

        assert len(history) == len(messages)
        for orig, retrieved in zip(messages, history):
            assert type(retrieved) is type(orig)
            assert retrieved.content == orig.content

            if isinstance(orig, AIMessage) and orig.tool_calls:
                assert len(retrieved.tool_calls) == len(orig.tool_calls)
                for orig_tc, ret_tc in zip(orig.tool_calls, retrieved.tool_calls):
                    assert orig_tc["name"] == ret_tc["name"]
                    assert orig_tc["args"] == ret_tc["args"]
                    assert orig_tc["id"] == ret_tc["id"]

            if isinstance(orig, ToolMessage):
                assert retrieved.tool_call_id == orig.tool_call_id
    finally:
        await store.close()
