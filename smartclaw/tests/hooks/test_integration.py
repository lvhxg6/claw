"""Integration tests for Agent Graph Hook and Diagnostic Bus integration.

Tests verify that hook handlers and diagnostic bus subscribers are called
correctly when invoke(), action_node(), and reasoning_node() run.

Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 19.1, 19.3, 19.4
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import smartclaw.hooks.registry as registry
from smartclaw.observability import diagnostic_bus
from smartclaw.agent.nodes import action_node, reasoning_node
from smartclaw.agent.state import AgentState
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
# Helpers
# ---------------------------------------------------------------------------


def _make_state(**kwargs: Any) -> AgentState:
    defaults: AgentState = {
        "messages": [HumanMessage(content="hello")],
        "iteration": 0,
        "max_iterations": 50,
        "final_answer": None,
        "error": None,
        "session_key": None,
        "summary": None,
        "sub_agent_depth": None,
    }
    defaults.update(kwargs)  # type: ignore[typeddict-item]
    return defaults


def setup_function() -> None:
    registry.clear()
    diagnostic_bus.clear()


def teardown_function() -> None:
    registry.clear()
    diagnostic_bus.clear()


# ---------------------------------------------------------------------------
# Helpers: build a minimal compiled graph for invoke() tests
# ---------------------------------------------------------------------------


def _build_mock_graph(final_answer: str = "done") -> Any:
    """Return a mock CompiledStateGraph that returns a fixed final state."""
    mock_graph = AsyncMock()
    mock_graph.ainvoke = AsyncMock(return_value={
        "messages": [AIMessage(content=final_answer)],
        "iteration": 1,
        "max_iterations": 50,
        "final_answer": final_answer,
        "error": None,
        "session_key": None,
        "summary": None,
        "sub_agent_depth": None,
    })
    return mock_graph


# ---------------------------------------------------------------------------
# Task 13.3 Test 1 & 2: invoke() triggers agent:start and agent:end hooks
# ---------------------------------------------------------------------------


async def test_invoke_triggers_agent_start_and_end_hooks() -> None:
    """invoke() triggers agent:start and agent:end hooks. (Req 11.1, 11.2)"""
    from smartclaw.agent.graph import invoke

    received: list[HookEvent] = []

    async def handler(event: HookEvent) -> None:
        received.append(event)

    registry.register("agent:start", handler)
    registry.register("agent:end", handler)

    mock_graph = _build_mock_graph("hello world")
    await invoke(mock_graph, "test message")

    hook_points = [e.hook_point for e in received]
    assert "agent:start" in hook_points, "agent:start hook not triggered"
    assert "agent:end" in hook_points, "agent:end hook not triggered"

    start_events = [e for e in received if isinstance(e, AgentStartEvent)]
    end_events = [e for e in received if isinstance(e, AgentEndEvent)]
    assert len(start_events) == 1
    assert len(end_events) == 1
    assert start_events[0].user_message == "test message"
    assert end_events[0].final_answer == "hello world"


async def test_invoke_agent_start_event_fields() -> None:
    """AgentStartEvent carries correct session_key and user_message. (Req 11.1)"""
    from smartclaw.agent.graph import invoke

    received: list[AgentStartEvent] = []

    async def handler(event: HookEvent) -> None:
        if isinstance(event, AgentStartEvent):
            received.append(event)

    registry.register("agent:start", handler)

    mock_graph = _build_mock_graph()
    await invoke(mock_graph, "my query", session_key="sess-123")

    assert len(received) == 1
    assert received[0].session_key == "sess-123"
    assert received[0].user_message == "my query"


async def test_invoke_agent_end_event_fields() -> None:
    """AgentEndEvent carries correct iterations and final_answer. (Req 11.2)"""
    from smartclaw.agent.graph import invoke

    received: list[AgentEndEvent] = []

    async def handler(event: HookEvent) -> None:
        if isinstance(event, AgentEndEvent):
            received.append(event)

    registry.register("agent:end", handler)

    mock_graph = _build_mock_graph("final answer text")
    await invoke(mock_graph, "query")

    assert len(received) == 1
    assert received[0].final_answer == "final answer text"
    assert received[0].iterations == 1


# ---------------------------------------------------------------------------
# Task 13.3 Test 3: tool:before and tool:after hooks triggered in action_node
# ---------------------------------------------------------------------------


async def test_action_node_triggers_tool_before_and_after_hooks() -> None:
    """action_node triggers tool:before and tool:after hooks. (Req 11.3, 11.4)"""
    before_events: list[ToolBeforeEvent] = []
    after_events: list[ToolAfterEvent] = []

    async def before_handler(event: HookEvent) -> None:
        if isinstance(event, ToolBeforeEvent):
            before_events.append(event)

    async def after_handler(event: HookEvent) -> None:
        if isinstance(event, ToolAfterEvent):
            after_events.append(event)

    registry.register("tool:before", before_handler)
    registry.register("tool:after", after_handler)

    # Build a mock tool
    mock_tool = AsyncMock()
    mock_tool.ainvoke = AsyncMock(return_value="tool result")

    tool_call = {"name": "my_tool", "id": "call-1", "args": {"x": 1}}
    state = _make_state(
        messages=[
            HumanMessage(content="hi"),
            AIMessage(content="", tool_calls=[tool_call]),
        ]
    )

    await action_node(state, tools_by_name={"my_tool": mock_tool})

    assert len(before_events) == 1
    assert before_events[0].tool_name == "my_tool"
    assert before_events[0].tool_call_id == "call-1"

    assert len(after_events) == 1
    assert after_events[0].tool_name == "my_tool"
    assert after_events[0].error is None
    assert after_events[0].duration_ms >= 0.0


async def test_action_node_triggers_tool_after_hook_on_error() -> None:
    """action_node triggers tool:after with error when tool raises. (Req 11.4)"""
    after_events: list[ToolAfterEvent] = []

    async def after_handler(event: HookEvent) -> None:
        if isinstance(event, ToolAfterEvent):
            after_events.append(event)

    registry.register("tool:after", after_handler)

    mock_tool = AsyncMock()
    mock_tool.ainvoke = AsyncMock(side_effect=RuntimeError("tool failed"))

    tool_call = {"name": "bad_tool", "id": "call-err", "args": {}}
    state = _make_state(
        messages=[
            HumanMessage(content="hi"),
            AIMessage(content="", tool_calls=[tool_call]),
        ]
    )

    result = await action_node(state, tools_by_name={"bad_tool": mock_tool})

    # Action node should still return a ToolMessage (error message)
    assert len(result["messages"]) == 1
    assert "Error" in result["messages"][0].content

    assert len(after_events) == 1
    assert after_events[0].error == "tool failed"


# ---------------------------------------------------------------------------
# Task 13.3 Test 4: llm:before and llm:after hooks triggered in reasoning_node
# ---------------------------------------------------------------------------


async def test_reasoning_node_triggers_llm_before_and_after_hooks() -> None:
    """reasoning_node triggers llm:before and llm:after hooks. (Req 11.5, 11.6)"""
    before_events: list[LLMBeforeEvent] = []
    after_events: list[LLMAfterEvent] = []

    async def before_handler(event: HookEvent) -> None:
        if isinstance(event, LLMBeforeEvent):
            before_events.append(event)

    async def after_handler(event: HookEvent) -> None:
        if isinstance(event, LLMAfterEvent):
            after_events.append(event)

    registry.register("llm:before", before_handler)
    registry.register("llm:after", after_handler)

    mock_llm_call = AsyncMock(return_value=AIMessage(content="LLM response"))
    state = _make_state()

    await reasoning_node(state, llm_call=mock_llm_call)

    assert len(before_events) == 1
    assert before_events[0].message_count == 1  # one HumanMessage in state

    assert len(after_events) == 1
    assert after_events[0].error is None
    assert after_events[0].has_tool_calls is False


async def test_reasoning_node_triggers_llm_after_hook_on_error() -> None:
    """reasoning_node triggers llm:after with error when LLM raises. (Req 11.6)"""
    after_events: list[LLMAfterEvent] = []

    async def after_handler(event: HookEvent) -> None:
        if isinstance(event, LLMAfterEvent):
            after_events.append(event)

    registry.register("llm:after", after_handler)

    mock_llm_call = AsyncMock(side_effect=RuntimeError("LLM failed"))
    state = _make_state()

    result = await reasoning_node(state, llm_call=mock_llm_call)

    # reasoning_node should still return a result (error state)
    assert result["error"] == "LLM failed"

    assert len(after_events) == 1
    assert after_events[0].error == "LLM failed"


# ---------------------------------------------------------------------------
# Task 13.3 Test 5: hook handler that raises does NOT affect Agent execution
# ---------------------------------------------------------------------------


async def test_raising_hook_handler_does_not_affect_agent_execution() -> None:
    """A hook handler that raises does NOT affect Agent execution. (Req 11.7)"""
    from smartclaw.agent.graph import invoke

    async def bad_start_handler(event: HookEvent) -> None:
        raise RuntimeError("hook exploded!")

    async def bad_end_handler(event: HookEvent) -> None:
        raise ValueError("end hook exploded!")

    registry.register("agent:start", bad_start_handler)
    registry.register("agent:end", bad_end_handler)

    mock_graph = _build_mock_graph("result despite bad hooks")

    # Should not raise even though hooks raise
    result = await invoke(mock_graph, "test")
    assert result["final_answer"] == "result despite bad hooks"


async def test_raising_tool_hook_does_not_affect_action_node() -> None:
    """Raising tool hook handlers do not affect action_node execution. (Req 11.7)"""
    async def bad_before(event: HookEvent) -> None:
        raise RuntimeError("before hook boom")

    async def bad_after(event: HookEvent) -> None:
        raise RuntimeError("after hook boom")

    registry.register("tool:before", bad_before)
    registry.register("tool:after", bad_after)

    mock_tool = AsyncMock()
    mock_tool.ainvoke = AsyncMock(return_value="ok result")

    tool_call = {"name": "t", "id": "c1", "args": {}}
    state = _make_state(
        messages=[
            HumanMessage(content="hi"),
            AIMessage(content="", tool_calls=[tool_call]),
        ]
    )

    result = await action_node(state, tools_by_name={"t": mock_tool})
    assert result["messages"][0].content == "ok result"


async def test_raising_llm_hook_does_not_affect_reasoning_node() -> None:
    """Raising LLM hook handlers do not affect reasoning_node execution. (Req 11.7)"""
    async def bad_before(event: HookEvent) -> None:
        raise RuntimeError("llm before boom")

    async def bad_after(event: HookEvent) -> None:
        raise RuntimeError("llm after boom")

    registry.register("llm:before", bad_before)
    registry.register("llm:after", bad_after)

    mock_llm_call = AsyncMock(return_value=AIMessage(content="answer"))
    state = _make_state()

    result = await reasoning_node(state, llm_call=mock_llm_call)
    assert result["final_answer"] == "answer"


# ---------------------------------------------------------------------------
# Task 13.3 Test 6: diagnostic events emitted alongside hooks
# ---------------------------------------------------------------------------


async def test_invoke_emits_agent_run_diagnostic_events() -> None:
    """invoke() emits agent.run diagnostic events for start and end. (Req 19.1)"""
    from smartclaw.agent.graph import invoke

    received: list[dict] = []

    async def subscriber(event_type: str, payload: dict) -> None:
        received.append({"event_type": event_type, "payload": payload})

    diagnostic_bus.on("agent.run", subscriber)

    mock_graph = _build_mock_graph("done")
    await invoke(mock_graph, "hello", session_key="s1")

    phases = [r["payload"]["phase"] for r in received]
    assert "start" in phases, "agent.run start event not emitted"
    assert "end" in phases, "agent.run end event not emitted"

    start_payload = next(r["payload"] for r in received if r["payload"]["phase"] == "start")
    assert start_payload["session_key"] == "s1"
    assert start_payload["user_message"] == "hello"


async def test_action_node_emits_tool_executed_diagnostic_event() -> None:
    """action_node emits tool.executed diagnostic event. (Req 19.3)"""
    received: list[dict] = []

    async def subscriber(event_type: str, payload: dict) -> None:
        received.append({"event_type": event_type, "payload": payload})

    diagnostic_bus.on("tool.executed", subscriber)

    mock_tool = AsyncMock()
    mock_tool.ainvoke = AsyncMock(return_value="result")

    tool_call = {"name": "search", "id": "c42", "args": {"q": "test"}}
    state = _make_state(
        messages=[
            HumanMessage(content="hi"),
            AIMessage(content="", tool_calls=[tool_call]),
        ]
    )

    await action_node(state, tools_by_name={"search": mock_tool})

    assert len(received) == 1
    assert received[0]["event_type"] == "tool.executed"
    assert received[0]["payload"]["tool_name"] == "search"
    assert received[0]["payload"]["error"] is None


async def test_hooks_and_diagnostics_triggered_together() -> None:
    """Hook triggers and diagnostic emits happen together for tool calls. (Req 19.4)"""
    hook_calls: list[str] = []
    diag_calls: list[str] = []

    async def tool_before_handler(event: HookEvent) -> None:
        hook_calls.append("tool:before")

    async def tool_after_handler(event: HookEvent) -> None:
        hook_calls.append("tool:after")

    async def diag_subscriber(event_type: str, payload: dict) -> None:
        diag_calls.append(event_type)

    registry.register("tool:before", tool_before_handler)
    registry.register("tool:after", tool_after_handler)
    diagnostic_bus.on("tool.executed", diag_subscriber)

    mock_tool = AsyncMock()
    mock_tool.ainvoke = AsyncMock(return_value="ok")

    tool_call = {"name": "calc", "id": "c99", "args": {}}
    state = _make_state(
        messages=[
            HumanMessage(content="hi"),
            AIMessage(content="", tool_calls=[tool_call]),
        ]
    )

    await action_node(state, tools_by_name={"calc": mock_tool})

    assert "tool:before" in hook_calls
    assert "tool:after" in hook_calls
    assert "tool.executed" in diag_calls


async def test_diagnostic_events_emitted_without_otel() -> None:
    """Diagnostic events work fine without OTEL configured. (Req 19.5)"""
    from smartclaw.agent.graph import invoke

    received: list[str] = []

    async def subscriber(event_type: str, payload: dict) -> None:
        received.append(event_type)

    diagnostic_bus.on("agent.run", subscriber)

    mock_graph = _build_mock_graph("ok")
    # Should not raise even without OTEL
    result = await invoke(mock_graph, "test")
    assert result is not None
    assert "agent.run" in received
