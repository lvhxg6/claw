"""Agent state definition for LangGraph StateGraph.

Defines the ``AgentState`` TypedDict used as the state schema for the
SmartClaw ReAct agent graph.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class ClarificationRequest(TypedDict):
    """Clarification request data structure.

    Attributes:
        question: The clarification question to ask the user.
        options: Optional predefined options for the user to choose from.
    """

    question: str
    options: list[str] | None


class TokenStats(TypedDict):
    """Token usage statistics accumulated across LLM calls."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class AgentState(TypedDict):
    """LangGraph StateGraph state schema.

    Attributes:
        messages: Full conversation history (LangGraph ``add_messages`` reducer).
        iteration: Current think-act-observe loop count.
        max_iterations: Upper bound for loop iterations.
        final_answer: Final text response when the loop completes.
        error: Error information when the loop terminates abnormally.
        session_key: P1 session identifier for memory persistence (default None).
        summary: P1 current conversation summary text (default None).
        sub_agent_depth: P1 sub-agent nesting depth counter (default None).
        mode: Resolved execution mode for the current turn (default None).
        plan: Orchestrator plan object (default None).
        todos: Orchestrator todo list (default None).
        current_phase: Current orchestrator phase (default None).
        phase_status: Current orchestrator phase status (default None).
        phase_index: Current orchestrator phase counter (default None).
        capability_pack: Active capability pack name (default None).
        capability_policy: Active capability governance policy (default None).
        dispatch_batches: Planned execution batches (default None).
        task_results: Aggregated orchestrator task results (default None).
        structured_result: Parsed structured result from schema-aware synthesis (default None).
        schema_validation: Schema validation outcome (default None).
        token_stats: Accumulated token usage statistics (default None).
        clarification_request: Clarification request when agent needs user input (default None).
    """

    messages: Annotated[list[BaseMessage], add_messages]
    iteration: int
    max_iterations: int
    final_answer: str | None
    error: str | None
    # P1 optional fields — backward compatible (default None)
    session_key: str | None
    summary: str | None
    sub_agent_depth: int | None
    mode: Literal["classic", "orchestrator"] | None
    plan: dict | None  # type: ignore[type-arg]
    todos: list[dict] | None  # type: ignore[type-arg]
    current_phase: str | None
    phase_status: str | None
    phase_index: int | None
    capability_pack: str | None
    capability_policy: dict | None  # type: ignore[type-arg]
    dispatch_batches: list[dict] | None  # type: ignore[type-arg]
    task_results: list[dict] | None  # type: ignore[type-arg]
    structured_result: dict | list | None  # type: ignore[type-arg]
    schema_validation: dict | None  # type: ignore[type-arg]
    # Token statistics
    token_stats: TokenStats | None
    # Clarification mechanism
    clarification_request: ClarificationRequest | None
