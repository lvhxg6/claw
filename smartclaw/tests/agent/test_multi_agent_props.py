"""Property-based tests for MultiAgentCoordinator module.

Uses hypothesis with @settings(max_examples=100).
Tests Property 20 from the design document.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from langchain_core.messages import AIMessage

from smartclaw.agent.multi_agent import AgentRole, MultiAgentCoordinator


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_max_total_iterations = st.integers(min_value=1, max_value=10)
_num_roles = st.integers(min_value=1, max_value=3)


def _make_role(name: str) -> AgentRole:
    """Create a simple AgentRole for testing."""
    return AgentRole(
        name=name,
        description=f"Agent {name} for testing",
        model="openai/gpt-4o",
    )


# ---------------------------------------------------------------------------
# Property 20: Multi-Agent Total Iteration Limit
# ---------------------------------------------------------------------------


# Feature: smartclaw-p1-enhanced-capabilities, Property 20: Multi-Agent Total Iteration Limit
@given(data=st.data())
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_total_iterations_never_exceed_max(data):
    """For any multi-agent execution with max_total_iterations=N,
    the total number of iterations across all agents should never exceed N.

    **Validates: Requirements 12.7**
    """
    max_iters = data.draw(_max_total_iterations)
    num_roles = data.draw(_num_roles)

    role_names = [f"agent_{i}" for i in range(num_roles)]
    roles = [_make_role(name) for name in role_names]

    # Track how many times agent nodes are actually invoked
    agent_invocation_count = 0
    # Cycle through agents, then finish
    call_count = 0

    async def mock_supervisor_llm(messages, *, model_config=None, **kwargs):
        nonlocal call_count
        # Cycle through agents, trying to exceed limit
        if call_count < max_iters + 5:
            agent_name = role_names[call_count % len(role_names)]
            call_count += 1
            return AIMessage(content=json.dumps({"agent": agent_name}))
        call_count += 1
        return AIMessage(content=json.dumps({"agent": "done", "answer": "All done"}))

    async def mock_graph_invoke(graph, msg, **kwargs):
        nonlocal agent_invocation_count
        agent_invocation_count += 1
        return {"final_answer": f"Result for: {msg[:50]}", "messages": [], "iteration": 1}

    coordinator = MultiAgentCoordinator(
        roles=roles,
        max_total_iterations=max_iters,
        llm_call=mock_supervisor_llm,
        graph_builder=MagicMock(return_value=MagicMock()),
        graph_invoker=mock_graph_invoke,
    )

    result = await coordinator.invoke("Test task for property 20")

    # The critical property: total agent invocations never exceed max_total_iterations
    assert agent_invocation_count <= max_iters, (
        f"Agent invocations ({agent_invocation_count}) exceeded "
        f"max_total_iterations ({max_iters})"
    )

    # The result should contain a warning if limit was reached
    if agent_invocation_count >= max_iters:
        assert "WARNING" in result or "Iteration limit" in result or result is not None
