"""Unit tests for AgentState TypedDict."""

from typing import get_type_hints

from langchain_core.messages import AIMessage, HumanMessage

from smartclaw.agent.state import AgentState


class TestAgentStateFields:
    """Test AgentState field existence and types (Requirements 5.1-5.6)."""

    def test_has_messages_field(self) -> None:
        hints = get_type_hints(AgentState, include_extras=True)
        assert "messages" in hints

    def test_has_iteration_field(self) -> None:
        hints = get_type_hints(AgentState, include_extras=True)
        assert "iteration" in hints

    def test_has_max_iterations_field(self) -> None:
        hints = get_type_hints(AgentState, include_extras=True)
        assert "max_iterations" in hints

    def test_has_final_answer_field(self) -> None:
        hints = get_type_hints(AgentState, include_extras=True)
        assert "final_answer" in hints

    def test_has_error_field(self) -> None:
        hints = get_type_hints(AgentState, include_extras=True)
        assert "error" in hints


class TestAgentStateTypedDictCompatibility:
    """Test TypedDict compatibility with LangGraph."""

    def test_can_create_instance(self) -> None:
        state: AgentState = {
            "messages": [HumanMessage(content="hello")],
            "iteration": 0,
            "max_iterations": 50,
            "final_answer": None,
            "error": None,
        }
        assert state["iteration"] == 0
        assert state["max_iterations"] == 50
        assert state["final_answer"] is None
        assert state["error"] is None
        assert len(state["messages"]) == 1

    def test_messages_accepts_various_message_types(self) -> None:
        state: AgentState = {
            "messages": [
                HumanMessage(content="hello"),
                AIMessage(content="world"),
            ],
            "iteration": 1,
            "max_iterations": 50,
            "final_answer": None,
            "error": None,
        }
        assert len(state["messages"]) == 2

    def test_final_answer_can_be_string(self) -> None:
        state: AgentState = {
            "messages": [],
            "iteration": 3,
            "max_iterations": 50,
            "final_answer": "The answer is 42",
            "error": None,
        }
        assert state["final_answer"] == "The answer is 42"

    def test_error_can_be_string(self) -> None:
        state: AgentState = {
            "messages": [],
            "iteration": 1,
            "max_iterations": 50,
            "final_answer": None,
            "error": "Something went wrong",
        }
        assert state["error"] == "Something went wrong"

    def test_messages_field_has_add_messages_annotation(self) -> None:
        """Verify the messages field uses the add_messages reducer annotation."""
        hints = get_type_hints(AgentState, include_extras=True)
        messages_hint = hints["messages"]
        # Annotated types have __metadata__
        assert hasattr(messages_hint, "__metadata__"), "messages should be Annotated"
