# Feature: llm-decision-observability, Property 4: LLM 调用决策捕获正确性
# Feature: llm-decision-observability, Property 9: 字段长度截断不变量
"""Property-based tests for decision capture in reasoning_node.

Uses hypothesis with @settings(max_examples=100, deadline=None).

Property 4: For any successful LLM response (AIMessage), if it has tool_calls
            then the captured DecisionRecord should have decision_type=tool_call
            and tool_calls populated; if no tool_calls then decision_type=final_answer.
            reasoning comes from AIMessage.content, input_summary from the last message.

Property 9: For any DecisionRecord created by the capture logic,
            input_summary <= 512 chars and reasoning <= 2048 chars.

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 10.3**
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from langchain_core.messages import AIMessage, HumanMessage

from smartclaw.agent.nodes import reasoning_node
from smartclaw.observability import decision_collector, diagnostic_bus
from smartclaw.observability.decision_record import DecisionType


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_tool_call_st = st.fixed_dictionaries(
    {
        "name": st.text(min_size=1, max_size=32, alphabet=st.characters(categories=("L", "N", "Pd"))),
        "id": st.text(min_size=1, max_size=16, alphabet=st.characters(categories=("L", "N"))),
        "args": st.fixed_dictionaries({}),
    }
)

# Generate AIMessage content — allow strings longer than 2048 to test truncation
_ai_content_st = st.text(min_size=0, max_size=4096)

# Generate the last user message content — allow strings longer than 512 to test truncation
_last_message_content_st = st.text(min_size=0, max_size=1024)


@st.composite
def ai_message_with_tool_calls_st(draw: st.DrawFn) -> tuple[AIMessage, str]:
    """Generate an AIMessage WITH tool_calls and a last-message content string."""
    content = draw(_ai_content_st)
    tool_calls = draw(st.lists(_tool_call_st, min_size=1, max_size=5))
    last_msg_content = draw(_last_message_content_st)
    return AIMessage(content=content, tool_calls=tool_calls), last_msg_content


@st.composite
def ai_message_without_tool_calls_st(draw: st.DrawFn) -> tuple[AIMessage, str]:
    """Generate an AIMessage WITHOUT tool_calls and a last-message content string."""
    content = draw(_ai_content_st)
    last_msg_content = draw(_last_message_content_st)
    return AIMessage(content=content), last_msg_content


# ---------------------------------------------------------------------------
# Autouse fixture — clean collector and diagnostic_bus before/after each test
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_state():
    """Ensure a clean collector and diagnostic_bus state for every test."""
    decision_collector.clear()
    diagnostic_bus.clear()
    yield
    decision_collector.clear()
    diagnostic_bus.clear()


# ---------------------------------------------------------------------------
# Property 4: LLM 调用决策捕获正确性
# ---------------------------------------------------------------------------


# Feature: llm-decision-observability, Property 4: LLM 调用决策捕获正确性
@given(data=ai_message_with_tool_calls_st())
@settings(max_examples=100, deadline=None)
def test_tool_call_decision_captured_correctly(
    data: tuple[AIMessage, str],
) -> None:
    """When LLM returns tool_calls, captured DecisionRecord has decision_type=tool_call,
    tool_calls populated, reasoning from AIMessage.content, input_summary from last message.

    **Validates: Requirements 2.1, 2.3, 2.4, 2.5**
    """
    decision_collector.clear()
    diagnostic_bus.clear()

    ai_message, last_msg_content = data
    import uuid as _uuid
    session_key = f"__test_prop4_tc_{_uuid.uuid4().hex[:8]}__"

    # Build state with a HumanMessage as the last message
    messages = [HumanMessage(content=last_msg_content)]
    state: dict[str, Any] = {
        "messages": messages,
        "iteration": 0,
        "max_iterations": 50,
        "session_key": session_key,
    }

    # Mock llm_call to return the generated AIMessage
    mock_llm_call = AsyncMock(return_value=ai_message)

    asyncio.run(
        reasoning_node(state, llm_call=mock_llm_call, session_key=session_key)
    )

    decisions = decision_collector.get_decisions(session_key)
    assert len(decisions) >= 1, f"Expected at least 1 decision, got {len(decisions)}"

    record = decisions[-1]

    # decision_type must be tool_call
    assert record.decision_type == DecisionType.TOOL_CALL, (
        f"Expected decision_type=tool_call, got {record.decision_type}"
    )

    # tool_calls must be populated with correct tool names
    expected_tool_names = [tc["name"] for tc in ai_message.tool_calls]
    actual_tool_names = [tc["tool_name"] for tc in record.tool_calls]
    assert actual_tool_names == expected_tool_names, (
        f"Expected tool names {expected_tool_names}, got {actual_tool_names}"
    )

    # reasoning comes from AIMessage.content (truncated to 2048)
    expected_reasoning = (ai_message.content or "")[:2048]
    assert record.reasoning == expected_reasoning, (
        f"reasoning mismatch: expected {expected_reasoning!r:.80}, got {record.reasoning!r:.80}"
    )

    # input_summary comes from the last message content (truncated to 512)
    expected_input_summary = last_msg_content[:512]
    assert record.input_summary == expected_input_summary, (
        f"input_summary mismatch: expected {expected_input_summary!r:.80}, "
        f"got {record.input_summary!r:.80}"
    )


# Feature: llm-decision-observability, Property 4: LLM 调用决策捕获正确性
@given(data=ai_message_without_tool_calls_st())
@settings(max_examples=100, deadline=None)
def test_final_answer_decision_captured_correctly(
    data: tuple[AIMessage, str],
) -> None:
    """When LLM returns no tool_calls, captured DecisionRecord has decision_type=final_answer.
    reasoning from AIMessage.content, input_summary from last message.

    **Validates: Requirements 2.2, 2.3, 2.4**
    """
    decision_collector.clear()
    diagnostic_bus.clear()

    ai_message, last_msg_content = data
    import uuid as _uuid
    session_key = f"__test_prop4_fa_{_uuid.uuid4().hex[:8]}__"

    messages = [HumanMessage(content=last_msg_content)]
    state: dict[str, Any] = {
        "messages": messages,
        "iteration": 0,
        "max_iterations": 50,
        "session_key": session_key,
    }

    mock_llm_call = AsyncMock(return_value=ai_message)

    asyncio.run(
        reasoning_node(state, llm_call=mock_llm_call, session_key=session_key)
    )

    decisions = decision_collector.get_decisions(session_key)
    assert len(decisions) >= 1, f"Expected at least 1 decision, got {len(decisions)}"

    record = decisions[-1]

    # decision_type must be final_answer
    assert record.decision_type == DecisionType.FINAL_ANSWER, (
        f"Expected decision_type=final_answer, got {record.decision_type}"
    )

    # tool_calls must be empty
    assert record.tool_calls == [], (
        f"Expected empty tool_calls, got {record.tool_calls}"
    )

    # reasoning comes from AIMessage.content (truncated to 2048)
    expected_reasoning = (ai_message.content if isinstance(ai_message.content, str) else "")[:2048]
    assert record.reasoning == expected_reasoning

    # input_summary comes from the last message content (truncated to 512)
    expected_input_summary = last_msg_content[:512]
    assert record.input_summary == expected_input_summary


# ---------------------------------------------------------------------------
# Property 9: 字段长度截断不变量
# ---------------------------------------------------------------------------


# Feature: llm-decision-observability, Property 9: 字段长度截断不变量
@given(
    content=st.text(min_size=0, max_size=5000),
    last_msg=st.text(min_size=0, max_size=2000),
    has_tool_calls=st.booleans(),
)
@settings(max_examples=100, deadline=None)
def test_field_length_truncation_invariant(
    content: str,
    last_msg: str,
    has_tool_calls: bool,
) -> None:
    """For any DecisionRecord created by reasoning_node capture logic,
    input_summary <= 512 chars and reasoning <= 2048 chars.

    **Validates: Requirements 10.3**
    """
    decision_collector.clear()
    diagnostic_bus.clear()

    session_key = f"__test_prop9_{__import__('uuid').uuid4().hex[:8]}__"

    # Build AIMessage with or without tool_calls
    if has_tool_calls:
        ai_message = AIMessage(
            content=content,
            tool_calls=[{"name": "test_tool", "id": "tc1", "args": {}}],
        )
    else:
        ai_message = AIMessage(content=content)

    messages = [HumanMessage(content=last_msg)]
    state: dict[str, Any] = {
        "messages": messages,
        "iteration": 0,
        "max_iterations": 50,
        "session_key": session_key,
    }

    mock_llm_call = AsyncMock(return_value=ai_message)

    asyncio.run(
        reasoning_node(state, llm_call=mock_llm_call, session_key=session_key)
    )

    decisions = decision_collector.get_decisions(session_key)
    assert len(decisions) >= 1, f"Expected at least 1 decision, got {len(decisions)}"

    record = decisions[-1]

    assert len(record.input_summary) <= 512, (
        f"input_summary length {len(record.input_summary)} exceeds 512"
    )
    assert len(record.reasoning) <= 2048, (
        f"reasoning length {len(record.reasoning)} exceeds 2048"
    )


# ---------------------------------------------------------------------------
# Property 5: Supervisor 路由决策捕获正确性
# ---------------------------------------------------------------------------

# Feature: llm-decision-observability, Property 5: Supervisor 路由决策捕获正确性
"""
Property 5: For any supervisor decision, if routing to a specific agent then
            decision_type=supervisor_route and target_agent is set; if routing
            to "done" then decision_type=final_answer.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**
"""

from smartclaw.agent.multi_agent import AgentRole, MultiAgentCoordinator


# Strategy: generate a valid agent name from the role list (excluding "done")
_agent_name_st = st.text(
    min_size=1,
    max_size=20,
    alphabet=st.characters(categories=("L", "N", "Pd")),
).filter(lambda s: s.lower() != "done")


import json as _json_mod  # noqa: E402


@st.composite
def supervisor_route_to_agent_st(draw: st.DrawFn) -> tuple[str, str, str]:
    """Generate (agent_name, llm_response_content, last_user_message) for routing to an agent."""
    agent_name = draw(_agent_name_st)
    # The supervisor LLM returns JSON like {"agent": "<name>"}
    raw_content = _json_mod.dumps({"agent": agent_name})
    last_msg = draw(_last_message_content_st)
    return agent_name, raw_content, last_msg


@st.composite
def supervisor_route_to_done_st(draw: st.DrawFn) -> tuple[str, str]:
    """Generate (llm_response_content, last_user_message) for routing to done."""
    answer = draw(st.text(min_size=0, max_size=200))
    raw_content = _json_mod.dumps({"agent": "done", "answer": answer})
    last_msg = draw(_last_message_content_st)
    return raw_content, last_msg


def _build_coordinator_and_state(
    agent_name: str,
    llm_content: str,
    last_msg_content: str,
) -> tuple[MultiAgentCoordinator, dict[str, Any]]:
    """Helper: build a MultiAgentCoordinator with a mock llm_call and a state dict."""
    role = AgentRole(
        name=agent_name,
        description=f"Test agent {agent_name}",
        model="test/model",
    )
    mock_response = AIMessage(content=llm_content)
    mock_llm_call = AsyncMock(return_value=mock_response)
    coordinator = MultiAgentCoordinator(
        roles=[role],
        llm_call=mock_llm_call,
    )
    state: dict[str, Any] = {
        "messages": [HumanMessage(content=last_msg_content)],
        "current_agent": None,
        "task_plan": None,
        "agent_results": {},
        "total_iterations": 0,
        "max_total_iterations": 100,
        "final_answer": None,
        "error": None,
    }
    return coordinator, state


# Feature: llm-decision-observability, Property 5: Supervisor 路由决策捕获正确性
@given(data=supervisor_route_to_agent_st())
@settings(max_examples=100, deadline=None)
def test_supervisor_route_to_agent_captured_correctly(
    data: tuple[str, str, str],
) -> None:
    """When supervisor routes to a specific agent, captured DecisionRecord has
    decision_type=supervisor_route and target_agent set to the agent name.
    reasoning contains the raw LLM response content.

    **Validates: Requirements 3.1, 3.2, 3.3**
    """
    decision_collector.clear()
    diagnostic_bus.clear()

    agent_name, llm_content, last_msg_content = data

    coordinator, state = _build_coordinator_and_state(
        agent_name, llm_content, last_msg_content,
    )

    asyncio.run(coordinator._supervisor_node(state))

    # The collector uses __default__ key since session_key=None
    decisions = decision_collector.get_decisions("__default__")
    assert len(decisions) >= 1, f"Expected at least 1 decision, got {len(decisions)}"

    record = decisions[-1]

    # decision_type must be supervisor_route
    assert record.decision_type == DecisionType.SUPERVISOR_ROUTE, (
        f"Expected decision_type=supervisor_route, got {record.decision_type}"
    )

    # target_agent must be the agent name
    assert record.target_agent == agent_name, (
        f"Expected target_agent={agent_name!r}, got {record.target_agent!r}"
    )

    # reasoning comes from the raw LLM content (truncated to 2048)
    # The supervisor extracts content from response.content
    expected_reasoning = llm_content[:2048]
    assert record.reasoning == expected_reasoning, (
        f"reasoning mismatch: expected {expected_reasoning!r:.80}, got {record.reasoning!r:.80}"
    )

    # session_key is None for multi-agent
    assert record.session_key is None, (
        f"Expected session_key=None, got {record.session_key!r}"
    )

    # input_summary from last message (truncated to 512)
    expected_input_summary = last_msg_content[:512]
    assert record.input_summary == expected_input_summary, (
        f"input_summary mismatch: expected {expected_input_summary!r:.80}, "
        f"got {record.input_summary!r:.80}"
    )


# Feature: llm-decision-observability, Property 5: Supervisor 路由决策捕获正确性
@given(data=supervisor_route_to_done_st())
@settings(max_examples=100, deadline=None)
def test_supervisor_route_to_done_captured_correctly(
    data: tuple[str, str],
) -> None:
    """When supervisor routes to 'done', captured DecisionRecord has
    decision_type=final_answer and target_agent is None.

    **Validates: Requirements 3.4**
    """
    decision_collector.clear()
    diagnostic_bus.clear()

    llm_content, last_msg_content = data

    # We still need a valid agent role for the coordinator
    coordinator, state = _build_coordinator_and_state(
        "helper", llm_content, last_msg_content,
    )

    asyncio.run(coordinator._supervisor_node(state))

    decisions = decision_collector.get_decisions("__default__")
    assert len(decisions) >= 1, f"Expected at least 1 decision, got {len(decisions)}"

    record = decisions[-1]

    # decision_type must be final_answer
    assert record.decision_type == DecisionType.FINAL_ANSWER, (
        f"Expected decision_type=final_answer, got {record.decision_type}"
    )

    # target_agent must be None
    assert record.target_agent is None, (
        f"Expected target_agent=None, got {record.target_agent!r}"
    )

    # reasoning comes from the raw LLM content (truncated to 2048)
    expected_reasoning = llm_content[:2048]
    assert record.reasoning == expected_reasoning

    # session_key is None for multi-agent
    assert record.session_key is None
