"""Property-based tests for agent nodes.

Feature: smartclaw-llm-agent-core
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from smartclaw.agent.nodes import action_node, should_continue
from smartclaw.agent.state import AgentState


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
# Feature: smartclaw-llm-agent-core, Property 10: Agent routing determined by tool_calls presence
# ---------------------------------------------------------------------------


class TestRoutingByToolCalls:
    """**Validates: Requirements 6.3, 6.4**

    For any AIMessage returned by the LLM, should_continue returns "action"
    if the message contains one or more tool_calls, and "end" if zero.
    """

    @given(
        num_tool_calls=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=100)
    def test_routes_to_action_with_tool_calls(self, num_tool_calls: int) -> None:
        """When AIMessage has tool_calls, should_continue returns 'action'."""
        tool_calls = [
            {"name": f"tool_{i}", "args": {}, "id": f"tc_{i}"}
            for i in range(num_tool_calls)
        ]
        ai_msg = AIMessage(content="", tool_calls=tool_calls)
        state = _make_state(messages=[ai_msg])

        assert should_continue(state) == "action"

    @given(
        content=st.text(min_size=0, max_size=200),
    )
    @settings(max_examples=100)
    def test_routes_to_end_without_tool_calls(self, content: str) -> None:
        """When AIMessage has no tool_calls, should_continue returns 'end'."""
        ai_msg = AIMessage(content=content)
        state = _make_state(messages=[ai_msg])

        assert should_continue(state) == "end"


# ---------------------------------------------------------------------------
# Feature: smartclaw-llm-agent-core, Property 11: Action node produces matching ToolMessages
# ---------------------------------------------------------------------------


class TestActionNodeToolMessages:
    """**Validates: Requirements 6.5**

    For any AgentState containing an AIMessage with N tool_calls (N >= 1),
    action_node appends exactly N ToolMessage objects, one per tool_call_id.
    """

    @given(
        tool_call_ids=st.lists(
            st.text(
                alphabet=st.characters(whitelist_categories=("L", "N", "P")),
                min_size=1,
                max_size=20,
            ),
            min_size=1,
            max_size=5,
            unique=True,
        ),
    )
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_produces_one_tool_message_per_call(self, tool_call_ids: list[str]) -> None:
        """action_node produces exactly N ToolMessages matching N tool_call_ids."""
        # Create a simple mock tool that returns a fixed string
        mock_tool = AsyncMock()
        mock_tool.ainvoke = AsyncMock(return_value="result")

        tool_calls = [
            {"name": "mock_tool", "args": {}, "id": tc_id}
            for tc_id in tool_call_ids
        ]
        ai_msg = AIMessage(content="", tool_calls=tool_calls)
        state = _make_state(messages=[HumanMessage(content="test"), ai_msg])

        result = await action_node(state, tools_by_name={"mock_tool": mock_tool})

        messages = result["messages"]
        assert len(messages) == len(tool_call_ids)
        assert all(isinstance(m, ToolMessage) for m in messages)

        result_ids = {m.tool_call_id for m in messages}
        assert result_ids == set(tool_call_ids)
