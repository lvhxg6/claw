"""Unit tests for agent nodes (reasoning_node, action_node, should_continue)."""

from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from smartclaw.agent.nodes import action_node, reasoning_node, should_continue
from smartclaw.agent.state import AgentState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@tool
def add_numbers(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


@tool
def failing_tool(x: str) -> str:
    """A tool that always fails."""
    msg = "Tool failure"
    raise RuntimeError(msg)


def _make_state(**overrides: object) -> AgentState:
    defaults: dict = {
        "messages": [],
        "iteration": 0,
        "max_iterations": 50,
        "final_answer": None,
        "error": None,
    }
    defaults.update(overrides)
    return defaults  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# reasoning_node tests
# ---------------------------------------------------------------------------


class TestReasoningNode:
    """Test reasoning_node with mock LLM (Requirement 6.2)."""

    @pytest.mark.asyncio
    async def test_returns_ai_message(self) -> None:
        ai_msg = AIMessage(content="Hello!")
        mock_llm = AsyncMock(return_value=ai_msg)
        state = _make_state(messages=[HumanMessage(content="Hi")])

        result = await reasoning_node(state, llm_call=mock_llm)

        assert len(result["messages"]) == 1
        assert result["messages"][0].content == "Hello!"
        assert result["iteration"] == 1

    @pytest.mark.asyncio
    async def test_sets_final_answer_when_no_tool_calls(self) -> None:
        ai_msg = AIMessage(content="The answer is 42")
        mock_llm = AsyncMock(return_value=ai_msg)
        state = _make_state(messages=[HumanMessage(content="What is the answer?")])

        result = await reasoning_node(state, llm_call=mock_llm)

        assert result["final_answer"] == "The answer is 42"

    @pytest.mark.asyncio
    async def test_no_final_answer_when_tool_calls_present(self) -> None:
        ai_msg = AIMessage(
            content="",
            tool_calls=[{"name": "add_numbers", "args": {"a": 1, "b": 2}, "id": "tc1"}],
        )
        mock_llm = AsyncMock(return_value=ai_msg)
        state = _make_state(messages=[HumanMessage(content="Add 1+2")])

        result = await reasoning_node(state, llm_call=mock_llm)

        assert "final_answer" not in result

    @pytest.mark.asyncio
    async def test_increments_iteration(self) -> None:
        ai_msg = AIMessage(content="ok")
        mock_llm = AsyncMock(return_value=ai_msg)
        state = _make_state(messages=[HumanMessage(content="Hi")], iteration=3)

        result = await reasoning_node(state, llm_call=mock_llm)

        assert result["iteration"] == 4

    @pytest.mark.asyncio
    async def test_max_iterations_forces_end(self) -> None:
        mock_llm = AsyncMock()
        state = _make_state(
            messages=[HumanMessage(content="Hi")],
            iteration=50,
            max_iterations=50,
        )

        result = await reasoning_node(state, llm_call=mock_llm)

        assert result.get("final_answer") is not None
        mock_llm.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_exception_stores_error(self) -> None:
        mock_llm = AsyncMock(side_effect=RuntimeError("LLM down"))
        state = _make_state(messages=[HumanMessage(content="Hi")])

        result = await reasoning_node(state, llm_call=mock_llm)

        assert result.get("error") == "LLM down"


# ---------------------------------------------------------------------------
# action_node tests
# ---------------------------------------------------------------------------


class TestActionNode:
    """Test action_node tool execution (Requirement 6.5)."""

    @pytest.mark.asyncio
    async def test_executes_tool_calls(self) -> None:
        ai_msg = AIMessage(
            content="",
            tool_calls=[{"name": "add_numbers", "args": {"a": 2, "b": 3}, "id": "tc1"}],
        )
        state = _make_state(messages=[HumanMessage(content="Add"), ai_msg])

        result = await action_node(state, tools_by_name={"add_numbers": add_numbers})

        assert len(result["messages"]) == 1
        assert isinstance(result["messages"][0], ToolMessage)
        assert result["messages"][0].tool_call_id == "tc1"
        assert "5" in result["messages"][0].content

    @pytest.mark.asyncio
    async def test_multiple_tool_calls(self) -> None:
        ai_msg = AIMessage(
            content="",
            tool_calls=[
                {"name": "add_numbers", "args": {"a": 1, "b": 2}, "id": "tc1"},
                {"name": "add_numbers", "args": {"a": 3, "b": 4}, "id": "tc2"},
            ],
        )
        state = _make_state(messages=[ai_msg])

        result = await action_node(state, tools_by_name={"add_numbers": add_numbers})

        assert len(result["messages"]) == 2
        ids = {m.tool_call_id for m in result["messages"]}
        assert ids == {"tc1", "tc2"}

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error_message(self) -> None:
        ai_msg = AIMessage(
            content="",
            tool_calls=[{"name": "unknown_tool", "args": {}, "id": "tc1"}],
        )
        state = _make_state(messages=[ai_msg])

        result = await action_node(state, tools_by_name={})

        assert len(result["messages"]) == 1
        assert "not found" in result["messages"][0].content.lower()

    @pytest.mark.asyncio
    async def test_tool_exception_returns_error_message(self) -> None:
        ai_msg = AIMessage(
            content="",
            tool_calls=[{"name": "failing_tool", "args": {"x": "test"}, "id": "tc1"}],
        )
        state = _make_state(messages=[ai_msg])

        result = await action_node(state, tools_by_name={"failing_tool": failing_tool})

        assert len(result["messages"]) == 1
        assert "error" in result["messages"][0].content.lower()

    @pytest.mark.asyncio
    async def test_no_ai_message_returns_empty(self) -> None:
        state = _make_state(messages=[HumanMessage(content="Hi")])

        result = await action_node(state, tools_by_name={})

        assert result["messages"] == []


# ---------------------------------------------------------------------------
# should_continue tests
# ---------------------------------------------------------------------------


class TestShouldContinue:
    """Test routing logic (Requirements 6.3, 6.4)."""

    def test_routes_to_action_when_tool_calls(self) -> None:
        ai_msg = AIMessage(
            content="",
            tool_calls=[{"name": "add_numbers", "args": {"a": 1, "b": 2}, "id": "tc1"}],
        )
        state = _make_state(messages=[ai_msg])

        assert should_continue(state) == "action"

    def test_routes_to_end_when_no_tool_calls(self) -> None:
        ai_msg = AIMessage(content="Final answer")
        state = _make_state(messages=[ai_msg])

        assert should_continue(state) == "end"

    def test_routes_to_end_when_error(self) -> None:
        state = _make_state(error="Something broke")

        assert should_continue(state) == "end"

    def test_routes_to_end_when_final_answer_set(self) -> None:
        state = _make_state(final_answer="Done")

        assert should_continue(state) == "end"

    def test_routes_to_end_when_empty_messages(self) -> None:
        state = _make_state(messages=[])

        assert should_continue(state) == "end"

    def test_routes_to_end_for_human_message(self) -> None:
        state = _make_state(messages=[HumanMessage(content="Hi")])

        assert should_continue(state) == "end"

    def test_routes_to_action_after_reasoning(self) -> None:
        """After reasoning_node returns AIMessage with tool_calls, route to action (6.6)."""
        ai_msg = AIMessage(
            content="Let me use a tool",
            tool_calls=[{"name": "add_numbers", "args": {"a": 1, "b": 2}, "id": "tc1"}],
        )
        state = _make_state(messages=[HumanMessage(content="Add 1+2"), ai_msg])

        assert should_continue(state) == "action"
