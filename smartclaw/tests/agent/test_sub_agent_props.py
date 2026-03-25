"""Property-based tests for SubAgent module.

Uses hypothesis with @settings(max_examples=100).
Tests Properties 17, 18, 19 from the design document.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from smartclaw.agent.sub_agent import (
    ConcurrencyTimeoutError,
    DepthLimitExceededError,
    EphemeralStore,
    SubAgentConfig,
    spawn_sub_agent,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_task = st.text(min_size=1, max_size=100).filter(lambda s: s.strip())
_model = st.just("openai/gpt-4o")
_max_depth = st.integers(min_value=1, max_value=10)
_parent_depth = st.integers(min_value=0, max_value=20)
_max_size = st.integers(min_value=1, max_value=50)
_content = st.text(min_size=0, max_size=100)


def _message_strategy() -> st.SearchStrategy[BaseMessage]:
    """Strategy generating HumanMessage or AIMessage."""
    human = _content.map(lambda c: HumanMessage(content=c))
    ai = _content.map(lambda c: AIMessage(content=c))
    return st.one_of(human, ai)


_message = _message_strategy()
_message_list = st.lists(_message, min_size=1, max_size=100)


# ---------------------------------------------------------------------------
# Property 17: Sub-Agent Depth Limit
# ---------------------------------------------------------------------------


# Feature: smartclaw-p1-enhanced-capabilities, Property 17: Sub-Agent Depth Limit
@given(data=st.data())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
async def test_depth_limit_raises_error(data):
    """For any spawn request where parent_depth >= max_depth,
    spawn_sub_agent should raise DepthLimitExceededError without
    spawning the sub-agent.

    **Validates: Requirements 9.6, 9.7**
    """
    max_depth = data.draw(_max_depth)
    # parent_depth >= max_depth
    parent_depth = data.draw(st.integers(min_value=max_depth, max_value=max_depth + 10))
    task = data.draw(_task)

    config = SubAgentConfig(
        task=task,
        model="openai/gpt-4o",
        max_depth=max_depth,
    )

    with pytest.raises(DepthLimitExceededError):
        await spawn_sub_agent(config, parent_depth=parent_depth)


# ---------------------------------------------------------------------------
# Property 18: Ephemeral Store Auto-Truncation
# ---------------------------------------------------------------------------


# Feature: smartclaw-p1-enhanced-capabilities, Property 18: Ephemeral Store Auto-Truncation
@given(data=st.data())
@settings(max_examples=100, deadline=None)
def test_ephemeral_store_never_exceeds_max_size(data):
    """For any sequence of messages added to an EphemeralStore with max_size=M,
    the store should never contain more than M messages, and when the limit
    is exceeded, only the most recent M messages should be retained.

    **Validates: Requirements 9.13**
    """
    max_size = data.draw(_max_size)
    messages = data.draw(st.lists(_message, min_size=1, max_size=max_size * 3))

    store = EphemeralStore(max_size=max_size)

    for msg in messages:
        store.add_message(msg)
        # Invariant: never exceeds max_size
        assert len(store.get_history()) <= max_size

    # Final state: contains at most max_size messages
    history = store.get_history()
    assert len(history) <= max_size

    # If we added more than max_size, the history should be the last max_size messages
    if len(messages) > max_size:
        expected = messages[-max_size:]
        assert len(history) == max_size
        for h, e in zip(history, expected):
            assert h.content == e.content


# Feature: smartclaw-p1-enhanced-capabilities, Property 18: Ephemeral Store Auto-Truncation (set_history)
@given(data=st.data())
@settings(max_examples=100, deadline=None)
def test_ephemeral_store_set_history_truncates(data):
    """set_history also auto-truncates to max_size.

    **Validates: Requirements 9.13**
    """
    max_size = data.draw(_max_size)
    messages = data.draw(st.lists(_message, min_size=1, max_size=max_size * 3))

    store = EphemeralStore(max_size=max_size)
    store.set_history(messages)

    history = store.get_history()
    assert len(history) <= max_size

    if len(messages) > max_size:
        expected = messages[-max_size:]
        assert len(history) == max_size
        for h, e in zip(history, expected):
            assert h.content == e.content


# ---------------------------------------------------------------------------
# Property 19: Sub-Agent Concurrency Limit
# ---------------------------------------------------------------------------



# Feature: smartclaw-p1-enhanced-capabilities, Property 19: Sub-Agent Concurrency Limit
@given(data=st.data())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
async def test_concurrency_limited_by_semaphore(data):
    """For any number of concurrent spawn_sub_agent calls exceeding
    max_concurrent, at most max_concurrent sub-agents should be
    executing simultaneously, with excess requests waiting for a slot.

    **Validates: Requirements 10.1, 10.2**
    """
    max_concurrent = data.draw(st.integers(min_value=1, max_value=3))
    num_tasks = data.draw(st.integers(min_value=max_concurrent + 1, max_value=max_concurrent + 5))

    semaphore = asyncio.Semaphore(max_concurrent)
    active_count = 0
    max_observed = 0
    lock = asyncio.Lock()

    # Mock build_graph and invoke to track concurrency
    mock_graph = MagicMock()

    async def mock_invoke(graph, msg, **kwargs):
        nonlocal active_count, max_observed
        async with lock:
            active_count += 1
            if active_count > max_observed:
                max_observed = active_count
        # Simulate some work
        await asyncio.sleep(0.01)
        async with lock:
            active_count -= 1
        return {"final_answer": f"Done: {msg[:20]}", "messages": [], "iteration": 1}

    with (
        patch("smartclaw.agent.graph.build_graph", return_value=mock_graph),
        patch("smartclaw.agent.graph.invoke", side_effect=mock_invoke),
    ):
        configs = [
            SubAgentConfig(task=f"Task {i}", model="openai/gpt-4o", max_depth=5)
            for i in range(num_tasks)
        ]

        tasks = [
            spawn_sub_agent(
                cfg,
                parent_depth=0,
                semaphore=semaphore,
                concurrency_timeout=10.0,
            )
            for cfg in configs
        ]

        results = await asyncio.gather(*tasks)

    # All tasks should complete
    assert len(results) == num_tasks
    # Max observed concurrency should not exceed max_concurrent
    assert max_observed <= max_concurrent
