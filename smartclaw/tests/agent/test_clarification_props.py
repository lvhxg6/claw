"""Property-based tests for the clarification mechanism.

Feature: deerflow-advantages-absorption
"""

from __future__ import annotations

from typing import Any

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
        "session_key": None,
        "summary": None,
        "sub_agent_depth": None,
        "token_stats": None,
        "clarification_request": None,
    }
    defaults.update(overrides)
    return defaults  # type: ignore[return-value]


# Strategies ----------------------------------------------------------------

# Generate non-empty question strings (action_node extracts via .get("question", ""))
_question_st = st.text(min_size=1, max_size=200)

# Generate options: either None or a list of 1-10 non-empty strings
_options_st = st.one_of(
    st.none(),
    st.lists(st.text(min_size=1, max_size=50), min_size=1, max_size=10),
)


# ---------------------------------------------------------------------------
# Feature: deerflow-advantages-absorption, Property 1: ask_clarification 拦截不变性
# ---------------------------------------------------------------------------


class TestAskClarificationInterceptionInvariance:
    """**Validates: Requirements 3.2**

    For any AIMessage containing an ask_clarification tool call (any question
    string and any options list), when action_node processes it, the returned
    state dict's clarification_request field should contain matching question
    and options, and the tool's _arun method should NOT be actually executed.
    """

    @given(question=_question_st, options=_options_st)
    @settings(max_examples=100)
    async def test_clarification_request_matches_tool_args(
        self, question: str, options: list[str] | None
    ) -> None:
        """action_node sets clarification_request matching the tool call args."""
        tool_args: dict[str, Any] = {"question": question}
        if options is not None:
            tool_args["options"] = options

        ai_msg = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "ask_clarification",
                    "args": tool_args,
                    "id": "tc_prop1",
                }
            ],
        )
        state = _make_state(messages=[HumanMessage(content="hi"), ai_msg])

        result = await action_node(state, tools_by_name={})

        # clarification_request must be present and match
        assert "clarification_request" in result
        cr = result["clarification_request"]
        assert cr["question"] == question
        assert cr["options"] == options

        # A ToolMessage placeholder is produced (not actual _arun execution)
        msgs = result["messages"]
        assert len(msgs) == 1
        assert isinstance(msgs[0], ToolMessage)
        assert msgs[0].content == f"Clarification requested: {question}"
        assert msgs[0].tool_call_id == "tc_prop1"


# ---------------------------------------------------------------------------
# Feature: deerflow-advantages-absorption, Property 2: clarification_request 路由终止
# ---------------------------------------------------------------------------


class TestClarificationRequestRoutingTermination:
    """**Validates: Requirements 3.4**

    For any AgentState where clarification_request is non-None,
    should_continue should return "end", regardless of whether the last
    message has tool_calls.
    """

    @given(question=_question_st, options=_options_st)
    @settings(max_examples=100)
    def test_routes_to_end_with_clarification_and_tool_calls(
        self, question: str, options: list[str] | None
    ) -> None:
        """should_continue returns 'end' even when last message has tool_calls."""
        cr = {"question": question, "options": options}
        # Last message IS an AIMessage with tool_calls — should still end
        ai_msg = AIMessage(
            content="",
            tool_calls=[{"name": "some_tool", "args": {}, "id": "tc_x"}],
        )
        state = _make_state(
            messages=[HumanMessage(content="hi"), ai_msg],
            clarification_request=cr,
        )

        assert should_continue(state) == "end"

    @given(question=_question_st, options=_options_st)
    @settings(max_examples=100)
    def test_routes_to_end_with_clarification_no_tool_calls(
        self, question: str, options: list[str] | None
    ) -> None:
        """should_continue returns 'end' when last message has no tool_calls."""
        cr = {"question": question, "options": options}
        ai_msg = AIMessage(content="some response")
        state = _make_state(
            messages=[HumanMessage(content="hi"), ai_msg],
            clarification_request=cr,
        )

        assert should_continue(state) == "end"
