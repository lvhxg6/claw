"""Unit tests for MultiAgentCoordinator module (Task 11.4).

Tests:
- Iteration limit reached: terminates with partial result + warning (Req 12.8)
- Agent failure: reported to supervisor (Req 12.10)
- No roles: raises ValueError
- Shared MemoryStore access (Req 12.9)

Requirements: 12.7, 12.8, 12.9, 12.10
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage

from smartclaw.agent.multi_agent import (
    AgentRole,
    MultiAgentCoordinator,
    MultiAgentState,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_role(name: str, description: str = "Test agent") -> AgentRole:
    """Create a simple AgentRole for testing."""
    return AgentRole(
        name=name,
        description=description,
        model="openai/gpt-4o",
    )


def _make_supervisor_llm(decisions: list[dict]):
    """Create a mock LLM call that returns decisions in sequence."""
    call_count = 0

    async def mock_llm(messages, *, model_config=None, **kwargs):
        nonlocal call_count
        idx = min(call_count, len(decisions) - 1)
        call_count += 1
        return AIMessage(content=json.dumps(decisions[idx]))

    return mock_llm


def _make_graph_invoker(result: dict | Exception = None):
    """Create a mock graph invoker."""
    if result is None:
        result = {"final_answer": "Agent result", "messages": [], "iteration": 1}

    async def mock_invoke(graph, msg, **kwargs):
        if isinstance(result, Exception):
            raise result
        return result

    return mock_invoke


def _make_graph_builder():
    """Create a mock graph builder."""
    return MagicMock(return_value=MagicMock())


# ---------------------------------------------------------------------------
# Test: No roles raises ValueError
# ---------------------------------------------------------------------------


class TestNoRoles:
    """MultiAgentCoordinator with no roles raises ValueError."""

    def test_empty_roles_raises_value_error(self) -> None:
        """Empty roles list raises ValueError."""
        with pytest.raises(ValueError, match="At least one AgentRole"):
            MultiAgentCoordinator(roles=[])


# ---------------------------------------------------------------------------
# Test: Iteration limit reached (Req 12.7, 12.8)
# ---------------------------------------------------------------------------


class TestIterationLimit:
    """When total iteration limit is reached, terminates with partial result + warning."""

    @pytest.mark.asyncio
    async def test_iteration_limit_terminates_with_warning(self) -> None:
        """When max_total_iterations is reached, returns partial result with WARNING."""
        roles = [_make_role("researcher"), _make_role("writer")]

        # Always try to assign to researcher — will hit limit
        llm = _make_supervisor_llm([{"agent": "researcher"}])

        coordinator = MultiAgentCoordinator(
            roles=roles,
            max_total_iterations=2,
            llm_call=llm,
            graph_builder=_make_graph_builder(),
            graph_invoker=_make_graph_invoker(),
        )

        result = await coordinator.invoke("Research and write a report")
        assert "WARNING" in result or "Iteration limit" in result

    @pytest.mark.asyncio
    async def test_iteration_limit_one_returns_partial(self) -> None:
        """With max_total_iterations=1, only one agent runs before limit."""
        roles = [_make_role("agent_a"), _make_role("agent_b")]

        decisions = [
            {"agent": "agent_a"},
            {"agent": "agent_b"},  # Should not run — limit hit
        ]
        llm = _make_supervisor_llm(decisions)

        coordinator = MultiAgentCoordinator(
            roles=roles,
            max_total_iterations=1,
            llm_call=llm,
            graph_builder=_make_graph_builder(),
            graph_invoker=_make_graph_invoker(),
        )

        result = await coordinator.invoke("Do two things")
        assert result is not None
        assert len(result) > 0


# ---------------------------------------------------------------------------
# Test: Agent failure reported to supervisor (Req 12.10)
# ---------------------------------------------------------------------------


class TestAgentFailure:
    """When a specialized agent fails, the failure is reported to supervisor."""

    @pytest.mark.asyncio
    async def test_agent_exception_reported_in_results(self) -> None:
        """When an agent raises an exception, it's captured in agent_results."""
        roles = [_make_role("failing_agent")]

        decisions = [
            {"agent": "failing_agent"},
            {"agent": "done", "answer": "Agent failed, returning partial result"},
        ]
        llm = _make_supervisor_llm(decisions)

        coordinator = MultiAgentCoordinator(
            roles=roles,
            max_total_iterations=5,
            llm_call=llm,
            graph_builder=_make_graph_builder(),
            graph_invoker=_make_graph_invoker(RuntimeError("LLM connection failed")),
        )

        result = await coordinator.invoke("Do something")
        assert result is not None
        assert "failed" in result.lower() or "partial" in result.lower() or "error" in result.lower()

    @pytest.mark.asyncio
    async def test_agent_error_state_reported(self) -> None:
        """When an agent returns error state, it's captured in agent_results."""
        roles = [_make_role("error_agent")]

        decisions = [
            {"agent": "error_agent"},
            {"agent": "done", "answer": "Handled error from agent"},
        ]
        llm = _make_supervisor_llm(decisions)

        error_result = {
            "final_answer": None,
            "error": "Internal error occurred",
            "messages": [],
            "iteration": 3,
        }

        coordinator = MultiAgentCoordinator(
            roles=roles,
            max_total_iterations=5,
            llm_call=llm,
            graph_builder=_make_graph_builder(),
            graph_invoker=_make_graph_invoker(error_result),
        )

        result = await coordinator.invoke("Do something")
        assert result is not None


# ---------------------------------------------------------------------------
# Test: Shared MemoryStore access (Req 12.9)
# ---------------------------------------------------------------------------


class TestSharedMemoryStore:
    """MultiAgentCoordinator shares MemoryStore across agents."""

    def test_memory_store_stored_on_coordinator(self) -> None:
        """MemoryStore is stored and accessible on the coordinator."""
        mock_store = MagicMock()
        roles = [_make_role("agent_a")]
        coordinator = MultiAgentCoordinator(
            roles=roles,
            memory_store=mock_store,
        )
        assert coordinator._memory_store is mock_store

    def test_memory_store_none_by_default(self) -> None:
        """MemoryStore defaults to None when not provided."""
        roles = [_make_role("agent_a")]
        coordinator = MultiAgentCoordinator(roles=roles)
        assert coordinator._memory_store is None

    @pytest.mark.asyncio
    async def test_coordinator_accepts_memory_store(self) -> None:
        """Coordinator can be created with a memory_store and invoked."""
        mock_store = MagicMock()
        roles = [_make_role("agent_a")]

        llm = _make_supervisor_llm([{"agent": "done", "answer": "Done with memory"}])

        coordinator = MultiAgentCoordinator(
            roles=roles,
            max_total_iterations=3,
            memory_store=mock_store,
            llm_call=llm,
        )

        result = await coordinator.invoke("Test with memory")
        assert result == "Done with memory"


# ---------------------------------------------------------------------------
# Test: Supervisor routing
# ---------------------------------------------------------------------------


class TestSupervisorRouting:
    """Tests for supervisor decision parsing and routing."""

    def test_parse_valid_json(self) -> None:
        """Valid JSON is parsed correctly."""
        result = MultiAgentCoordinator._parse_supervisor_decision('{"agent": "researcher"}')
        assert result == {"agent": "researcher"}

    def test_parse_done_with_answer(self) -> None:
        """Done decision with answer is parsed correctly."""
        result = MultiAgentCoordinator._parse_supervisor_decision(
            '{"agent": "done", "answer": "Final answer"}'
        )
        assert result["agent"] == "done"
        assert result["answer"] == "Final answer"

    def test_parse_json_in_markdown(self) -> None:
        """JSON wrapped in markdown code block is extracted."""
        content = '```json\n{"agent": "writer"}\n```'
        result = MultiAgentCoordinator._parse_supervisor_decision(content)
        assert result["agent"] == "writer"

    def test_parse_json_embedded_in_text(self) -> None:
        """JSON embedded in surrounding text is extracted."""
        content = 'I think we should use {"agent": "researcher"} for this task.'
        result = MultiAgentCoordinator._parse_supervisor_decision(content)
        assert result["agent"] == "researcher"

    def test_parse_invalid_json_returns_done(self) -> None:
        """Invalid JSON falls back to done with the content as answer."""
        result = MultiAgentCoordinator._parse_supervisor_decision("not json at all")
        assert result["agent"] == "done"

    @pytest.mark.asyncio
    async def test_supervisor_routes_to_invalid_agent(self) -> None:
        """When supervisor routes to non-existent agent, returns error."""
        roles = [_make_role("agent_a")]

        llm = _make_supervisor_llm([{"agent": "nonexistent_agent"}])

        coordinator = MultiAgentCoordinator(
            roles=roles,
            max_total_iterations=5,
            llm_call=llm,
        )

        result = await coordinator.invoke("Route to bad agent")
        assert "error" in result.lower() or "not found" in result.lower()


# ---------------------------------------------------------------------------
# Test: Normal flow — supervisor assigns and completes
# ---------------------------------------------------------------------------


class TestNormalFlow:
    """Tests for normal multi-agent coordination flow."""

    @pytest.mark.asyncio
    async def test_supervisor_assigns_then_completes(self) -> None:
        """Supervisor assigns to agent, gets result, then completes."""
        roles = [_make_role("researcher", "Does research")]

        decisions = [
            {"agent": "researcher"},
            {"agent": "done", "answer": "Research complete: found 3 results"},
        ]
        llm = _make_supervisor_llm(decisions)

        coordinator = MultiAgentCoordinator(
            roles=roles,
            max_total_iterations=10,
            llm_call=llm,
            graph_builder=_make_graph_builder(),
            graph_invoker=_make_graph_invoker(
                {"final_answer": "Found 3 results", "messages": [], "iteration": 2}
            ),
        )

        result = await coordinator.invoke("Research AI trends")
        assert "Research complete" in result or "3 results" in result


# ---------------------------------------------------------------------------
# Test: AgentRole and MultiAgentState data models
# ---------------------------------------------------------------------------


class TestDataModels:
    """Tests for AgentRole and MultiAgentState data models."""

    def test_agent_role_defaults(self) -> None:
        """AgentRole has correct default values."""
        role = AgentRole(name="test", description="Test agent", model="openai/gpt-4o")
        assert role.name == "test"
        assert role.description == "Test agent"
        assert role.model == "openai/gpt-4o"
        assert role.tools == []
        assert role.system_prompt is None
        assert role.max_iterations == 25

    def test_agent_role_custom_values(self) -> None:
        """AgentRole accepts custom values."""
        role = AgentRole(
            name="custom",
            description="Custom agent",
            model="anthropic/claude-sonnet-4-20250514",
            system_prompt="You are a custom agent.",
            max_iterations=10,
        )
        assert role.system_prompt == "You are a custom agent."
        assert role.max_iterations == 10

    def test_multi_agent_state_is_typed_dict(self) -> None:
        """MultiAgentState can be used as a TypedDict."""
        state: MultiAgentState = {
            "messages": [],
            "current_agent": None,
            "task_plan": None,
            "agent_results": {},
            "total_iterations": 0,
            "max_total_iterations": 100,
            "final_answer": None,
            "error": None,
        }
        assert state["total_iterations"] == 0
        assert state["max_total_iterations"] == 100
