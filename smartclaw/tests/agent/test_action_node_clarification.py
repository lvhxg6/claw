"""Unit tests for action_node ask_clarification interception (Task 3.3)."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

from smartclaw.agent.nodes import action_node
from smartclaw.agent.state import AgentState


@tool
def add_numbers(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


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


class TestActionNodeClarificationInterception:
    """Tests for ask_clarification interception in action_node."""

    @pytest.mark.asyncio
    async def test_intercepts_ask_clarification(self) -> None:
        """ask_clarification tool call sets clarification_request in result."""
        ai_msg = AIMessage(
            content="",
            tool_calls=[{
                "name": "ask_clarification",
                "args": {"question": "Which file?", "options": ["a.txt", "b.txt"]},
                "id": "tc1",
            }],
        )
        state = _make_state(messages=[ai_msg])

        result = await action_node(state, tools_by_name={})

        assert "clarification_request" in result
        assert result["clarification_request"]["question"] == "Which file?"
        assert result["clarification_request"]["options"] == ["a.txt", "b.txt"]

    @pytest.mark.asyncio
    async def test_clarification_generates_tool_message(self) -> None:
        """Intercepted ask_clarification produces a ToolMessage with correct content."""
        ai_msg = AIMessage(
            content="",
            tool_calls=[{
                "name": "ask_clarification",
                "args": {"question": "What format?", "options": None},
                "id": "tc1",
            }],
        )
        state = _make_state(messages=[ai_msg])

        result = await action_node(state, tools_by_name={})

        assert len(result["messages"]) == 1
        msg = result["messages"][0]
        assert isinstance(msg, ToolMessage)
        assert msg.content == "Clarification requested: What format?"
        assert msg.tool_call_id == "tc1"

    @pytest.mark.asyncio
    async def test_clarification_skips_subsequent_tool_calls(self) -> None:
        """Tool calls after ask_clarification in the same batch are skipped."""
        ai_msg = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "ask_clarification",
                    "args": {"question": "Which one?", "options": ["x", "y"]},
                    "id": "tc1",
                },
                {
                    "name": "add_numbers",
                    "args": {"a": 1, "b": 2},
                    "id": "tc2",
                },
            ],
        )
        state = _make_state(messages=[ai_msg])

        result = await action_node(state, tools_by_name={"add_numbers": add_numbers})

        # Only the clarification ToolMessage, add_numbers was skipped
        assert len(result["messages"]) == 1
        assert result["messages"][0].tool_call_id == "tc1"
        assert "clarification_request" in result

    @pytest.mark.asyncio
    async def test_tools_before_clarification_still_execute(self) -> None:
        """Tool calls before ask_clarification in the batch are executed normally."""
        ai_msg = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "add_numbers",
                    "args": {"a": 1, "b": 2},
                    "id": "tc1",
                },
                {
                    "name": "ask_clarification",
                    "args": {"question": "Continue?", "options": None},
                    "id": "tc2",
                },
                {
                    "name": "add_numbers",
                    "args": {"a": 3, "b": 4},
                    "id": "tc3",
                },
            ],
        )
        state = _make_state(messages=[ai_msg])

        result = await action_node(state, tools_by_name={"add_numbers": add_numbers})

        # tc1 executed, tc2 is clarification, tc3 skipped
        assert len(result["messages"]) == 2
        assert result["messages"][0].tool_call_id == "tc1"
        assert "3" in result["messages"][0].content  # 1+2=3
        assert result["messages"][1].tool_call_id == "tc2"
        assert result["messages"][1].content == "Clarification requested: Continue?"
        assert result["clarification_request"]["question"] == "Continue?"

    @pytest.mark.asyncio
    async def test_clarification_without_options(self) -> None:
        """ask_clarification with no options sets options to None."""
        ai_msg = AIMessage(
            content="",
            tool_calls=[{
                "name": "ask_clarification",
                "args": {"question": "Please elaborate"},
                "id": "tc1",
            }],
        )
        state = _make_state(messages=[ai_msg])

        result = await action_node(state, tools_by_name={})

        assert result["clarification_request"]["question"] == "Please elaborate"
        assert result["clarification_request"]["options"] is None

    @pytest.mark.asyncio
    async def test_no_clarification_request_when_normal_tools(self) -> None:
        """Normal tool calls do not produce clarification_request."""
        ai_msg = AIMessage(
            content="",
            tool_calls=[{
                "name": "add_numbers",
                "args": {"a": 5, "b": 6},
                "id": "tc1",
            }],
        )
        state = _make_state(messages=[ai_msg])

        result = await action_node(state, tools_by_name={"add_numbers": add_numbers})

        assert "clarification_request" not in result
