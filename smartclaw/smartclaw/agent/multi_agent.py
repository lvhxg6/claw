"""Multi-Agent Coordinator — Supervisor pattern multi-agent orchestration.

Provides:

- ``AgentRole`` — dataclass defining a specialized agent's role and capabilities.
- ``MultiAgentState`` — TypedDict state schema for the multi-agent graph.
- ``MultiAgentCoordinator`` — orchestrator using LangGraph StateGraph with
  conditional routing and a supervisor node.

Reference: PicoClaw multi-agent patterns, LangGraph supervisor architecture.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

import structlog
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph

logger = structlog.get_logger(component="agent.multi_agent")


# ---------------------------------------------------------------------------
# Data models (Task 11.1)
# ---------------------------------------------------------------------------


@dataclass
class AgentRole:
    """Agent role definition for multi-agent coordination.

    Attributes:
        name: Unique identifier for this agent role.
        description: Capability description for the supervisor to understand.
        model: LLM model reference in 'provider/model' format.
        tools: Tools available to this agent.
        system_prompt: Optional role-specific system prompt.
        max_iterations: Per-agent iteration limit (default 25).
    """

    name: str
    description: str
    model: str
    tools: list[BaseTool] = field(default_factory=list)
    system_prompt: str | None = None
    max_iterations: int = 25


class MultiAgentState(TypedDict):
    """LangGraph StateGraph state schema for multi-agent orchestration.

    Attributes:
        messages: Full conversation history (LangGraph add_messages reducer).
        current_agent: Name of the currently executing agent (or None).
        task_plan: Supervisor's decomposed task plan (list of dicts).
        agent_results: Results from each agent keyed by agent name.
        total_iterations: Global iteration counter across all agents.
        max_total_iterations: Global iteration upper bound.
        final_answer: Final synthesized response.
        error: Error information when execution terminates abnormally.
    """

    messages: Annotated[list[BaseMessage], add_messages]
    current_agent: str | None
    task_plan: list[dict] | None
    agent_results: dict[str, str]
    total_iterations: int
    max_total_iterations: int
    final_answer: str | None
    error: str | None



# ---------------------------------------------------------------------------
# MultiAgentCoordinator (Task 11.2)
# ---------------------------------------------------------------------------

_SUPERVISOR_SYSTEM_PROMPT = """\
You are a supervisor coordinating multiple specialized agents.
Available agents:
{agent_descriptions}

Your job:
1. Analyze the user's request.
2. Decide which agent should handle the next step, OR if the task is complete.
3. Respond with ONLY a JSON object (no markdown, no extra text):
   - To assign work: {{"agent": "<agent_name>"}}
   - To finish: {{"agent": "done", "answer": "<final synthesized answer>"}}

## Decision Tree

Follow this decision tree to choose the right action:

1. Single-agent task — the request maps to exactly one agent's expertise:
   → Assign directly: {{"agent": "<name>"}}
2. Multi-step sequential task — steps depend on each other:
   → Assign the FIRST step now; after it completes, assign the next.
3. Parallel independent tasks — multiple sub-tasks with NO dependencies:
   → Assign one agent at a time in rapid succession. Prefer the agent whose
     skill best matches each sub-task.
4. Result synthesis — all sub-tasks are done:
   → Combine agent results into a coherent answer and finish:
     {{"agent": "done", "answer": "<synthesized answer>"}}

## Batch Planning Guidance

When the user's request contains multiple independent sub-tasks that can be
handled by different agents without waiting for each other, plan a batch:
- Identify each independent sub-task.
- Map each sub-task to the best-fit agent.
- Assign them one by one (each response is a single JSON object).
- After all agents report back, synthesize the final answer.

## Examples

### Good Examples

Example 1 — Single agent, clear match:
  User: "Summarize the Q3 sales report."
  Response: {{"agent": "researcher"}}
  Why: The task is a single research/summarization job; assign directly.

Example 2 — Synthesis after agents finish:
  User: "Compare product A and product B."
  (After researcher returns results for both products)
  Response: {{"agent": "done", "answer": "Product A excels in X, while B leads in Y..."}}
  Why: Both sub-results are available; synthesize and finish.

### Bad Examples

Example 1 — Wrong: finishing without agent work:
  User: "Analyze our competitor's pricing strategy."
  Wrong response: {{"agent": "done", "answer": "I think prices are high."}}
  Why: No agent was used; the supervisor should NOT answer directly.

Example 2 — Wrong: assigning to a non-existent agent:
  User: "Translate this document to French."
  Wrong response: {{"agent": "translator"}}
  Why: Only assign to agents listed in "Available agents" above.

## Failure Handling

- Agent returns an error → Reassign the same sub-task to another capable agent.
  If no alternative agent exists, note the failure and continue with remaining tasks.
- Agent returns an incomplete result → Assign a follow-up task to the same or
  another agent to fill in the gaps.
- All agents fail → Synthesize whatever partial results are available, clearly
  state which parts failed and why, then finish:
  {{"agent": "done", "answer": "<partial results + failure explanation>"}}

Current agent results so far:
{agent_results}
"""


class MultiAgentCoordinator:
    """Multi-Agent orchestrator using the Supervisor pattern.

    The supervisor LLM receives the task, decides which specialized agent
    to route to (or "done" to finish), and each agent runs its own ReAct
    loop via ``build_graph``. A global iteration counter prevents runaway
    execution.
    """

    def __init__(
        self,
        roles: list[AgentRole],
        *,
        max_total_iterations: int = 100,
        memory_store: Any | None = None,
        llm_call: Any | None = None,
        graph_builder: Any | None = None,
        graph_invoker: Any | None = None,
    ) -> None:
        if not roles:
            raise ValueError("At least one AgentRole must be provided")

        self._roles = {r.name: r for r in roles}
        self._max_total_iterations = max_total_iterations
        self._memory_store = memory_store
        self._llm_call = llm_call
        self._graph_builder = graph_builder
        self._graph_invoker = graph_invoker

        logger.info(
            "multi_agent_coordinator_init",
            roles=[r.name for r in roles],
            max_total_iterations=max_total_iterations,
        )

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def create_multi_agent_graph(self) -> CompiledStateGraph:
        """Build a compiled LangGraph StateGraph for multi-agent orchestration.

        Graph structure:
            supervisor → conditional_edge → agent_X | done
            agent_X → supervisor
            done → END
        """
        graph = StateGraph(MultiAgentState)

        # Add supervisor node
        graph.add_node("supervisor", self._supervisor_node)

        # Add a node for each specialized agent
        for role_name in self._roles:
            graph.add_node(role_name, self._make_agent_node(role_name))

        # Add done node
        graph.add_node("done", self._done_node)

        # Entry point
        graph.set_entry_point("supervisor")

        # Conditional routing from supervisor
        valid_targets = {name: name for name in self._roles}
        valid_targets["done"] = "done"
        valid_targets["__end__"] = END

        graph.add_conditional_edges(
            "supervisor",
            self._route_supervisor,
            valid_targets,
        )

        # Each agent routes back to supervisor
        for role_name in self._roles:
            graph.add_edge(role_name, "supervisor")

        return graph.compile()

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    async def _supervisor_node(self, state: MultiAgentState) -> dict[str, Any]:
        """Supervisor node: use LLM to decide routing."""
        total_iters = state.get("total_iterations", 0)
        max_iters = state.get("max_total_iterations", self._max_total_iterations)

        # Check global iteration limit
        if total_iters >= max_iters:
            logger.warning(
                "iteration_limit_reached",
                total_iterations=total_iters,
                max_total_iterations=max_iters,
            )
            agent_results = state.get("agent_results", {})
            partial = self._synthesize_partial_result(agent_results)
            return {
                "final_answer": partial,
                "error": None,
            }

        # Build supervisor prompt
        agent_descriptions = "\n".join(
            f"- {name}: {role.description}" for name, role in self._roles.items()
        )
        agent_results = state.get("agent_results", {})
        results_str = (
            json.dumps(agent_results, ensure_ascii=False, indent=2)
            if agent_results
            else "(none yet)"
        )

        system_prompt = _SUPERVISOR_SYSTEM_PROMPT.format(
            agent_descriptions=agent_descriptions,
            agent_results=results_str,
        )

        messages = state.get("messages", [])
        supervisor_messages: list[BaseMessage] = [
            SystemMessage(content=system_prompt),
            *messages,
        ]

        try:
            llm_call_fn = self._llm_call
            if llm_call_fn is None:
                from smartclaw.agent.graph import _llm_call_with_fallback
                from smartclaw.providers.fallback import FallbackChain

                llm_call_fn = _llm_call_with_fallback
                _fallback_chain = FallbackChain()
            else:
                _fallback_chain = None

            from smartclaw.providers.config import ModelConfig

            # Use the first role's model for the supervisor
            first_role = next(iter(self._roles.values()))
            model_config = ModelConfig(
                primary=first_role.model,
                fallbacks=[],
                temperature=0.0,
            )

            if _fallback_chain is not None:
                response = await llm_call_fn(
                    supervisor_messages,
                    model_config=model_config,
                    fallback_chain=_fallback_chain,
                )
            else:
                response = await llm_call_fn(
                    supervisor_messages,
                    model_config=model_config,
                )

            content = response.content if isinstance(response.content, str) else str(response.content)

            # Parse supervisor decision
            decision = self._parse_supervisor_decision(content)
            current_agent = decision.get("agent", "done")

            # Decision capture: record the supervisor routing decision
            try:
                from smartclaw.observability.decision_record import (
                    DecisionRecord,
                    DecisionType,
                    _utc_now_iso,
                )
                from smartclaw.observability import decision_collector

                if current_agent == "done":
                    _dt = DecisionType.FINAL_ANSWER
                    _target = None
                else:
                    _dt = DecisionType.SUPERVISOR_ROUTE
                    _target = current_agent

                _input_summary = ""
                if messages:
                    _last_msg = messages[-1]
                    if hasattr(_last_msg, "content") and isinstance(_last_msg.content, str):
                        _input_summary = _last_msg.content[:512]

                _record = DecisionRecord(
                    timestamp=_utc_now_iso(),
                    iteration=total_iters,
                    decision_type=_dt,
                    input_summary=_input_summary,
                    reasoning=content[:2048],
                    target_agent=_target,
                    session_key=None,
                )
                await decision_collector.add(_record)
            except Exception:
                pass  # Silent failure — must not disrupt agent main flow

            if current_agent == "done":
                answer = decision.get("answer", "Task completed.")
                return {
                    "current_agent": "done",
                    "final_answer": answer,
                }

            # Validate agent name
            if current_agent not in self._roles:
                logger.error(
                    "supervisor_invalid_agent",
                    agent=current_agent,
                    available=list(self._roles.keys()),
                )
                return {
                    "current_agent": "done",
                    "final_answer": f"Routing error: agent '{current_agent}' not found.",
                    "error": f"Invalid agent: {current_agent}",
                }

            return {"current_agent": current_agent}

        except Exception as exc:
            logger.error("supervisor_node_error", error=str(exc), exc_info=True)
            return {
                "current_agent": "done",
                "error": str(exc),
                "final_answer": f"Supervisor error: {exc}",
            }

    def _make_agent_node(self, role_name: str) -> Any:
        """Create an agent node function for the given role."""

        async def agent_node(state: MultiAgentState) -> dict[str, Any]:
            total_iters = state.get("total_iterations", 0)
            max_iters = state.get("max_total_iterations", self._max_total_iterations)

            # Check global iteration limit before running
            if total_iters >= max_iters:
                logger.warning(
                    "agent_skipped_iteration_limit",
                    agent=role_name,
                    total_iterations=total_iters,
                )
                agent_results = dict(state.get("agent_results", {}))
                agent_results[role_name] = "Skipped: iteration limit reached"
                return {
                    "agent_results": agent_results,
                    "total_iterations": total_iters,
                }

            role = self._roles[role_name]

            try:
                from smartclaw.providers.config import ModelConfig

                _build = self._graph_builder
                _invoke = self._graph_invoker
                if _build is None:
                    from smartclaw.agent.graph import build_graph
                    _build = build_graph
                if _invoke is None:
                    from smartclaw.agent.graph import invoke as graph_invoke
                    _invoke = graph_invoke

                model_config = ModelConfig(
                    primary=role.model,
                    fallbacks=[],
                    temperature=0.0,
                )

                agent_graph = _build(model_config, role.tools)

                # Extract the latest user-facing message for the agent
                task_message = self._extract_task_for_agent(state)

                result = await _invoke(
                    agent_graph,
                    task_message,
                    max_iterations=role.max_iterations,
                    system_prompt=role.system_prompt,
                )

                answer = result.get("final_answer") or result.get("error") or "No result"

                agent_results = dict(state.get("agent_results", {}))
                agent_results[role_name] = answer

                new_total = total_iters + 1

                logger.info(
                    "agent_node_complete",
                    agent=role_name,
                    total_iterations=new_total,
                    answer_len=len(answer),
                )

                return {
                    "agent_results": agent_results,
                    "total_iterations": new_total,
                }

            except Exception as exc:
                logger.error(
                    "agent_node_error",
                    agent=role_name,
                    error=str(exc),
                    exc_info=True,
                )
                agent_results = dict(state.get("agent_results", {}))
                agent_results[role_name] = f"Error: {exc}"

                return {
                    "agent_results": agent_results,
                    "total_iterations": total_iters + 1,
                }

        return agent_node

    @staticmethod
    async def _done_node(state: MultiAgentState) -> dict[str, Any]:
        """Terminal node — no-op, just passes through."""
        return {}

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------

    @staticmethod
    def _route_supervisor(state: MultiAgentState) -> str:
        """Route based on supervisor's current_agent decision."""
        if state.get("final_answer") is not None:
            return "__end__"

        current = state.get("current_agent")
        if current == "done" or current is None:
            return "__end__"

        return current

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_supervisor_decision(content: str) -> dict[str, str]:
        """Parse supervisor LLM response as JSON."""
        # Try to extract JSON from the response
        content = content.strip()

        # Handle markdown code blocks
        if content.startswith("```"):
            lines = content.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```") and not in_block:
                    in_block = True
                    continue
                if line.startswith("```") and in_block:
                    break
                if in_block:
                    json_lines.append(line)
            content = "\n".join(json_lines).strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Try to find JSON object in the text
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(content[start : end + 1])
                except json.JSONDecodeError:
                    pass
            logger.warning("supervisor_parse_failed", content=content[:200])
            return {"agent": "done", "answer": content}

    @staticmethod
    def _extract_task_for_agent(state: MultiAgentState) -> str:
        """Extract the latest user message as the task for the agent."""
        messages = state.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                content = msg.content
                return content if isinstance(content, str) else str(content)
        return "No task provided."

    @staticmethod
    def _synthesize_partial_result(agent_results: dict[str, str]) -> str:
        """Synthesize a partial result from available agent results."""
        if not agent_results:
            return "WARNING: Iteration limit reached with no agent results."

        parts = ["WARNING: Iteration limit reached. Partial results:"]
        for agent_name, result in agent_results.items():
            parts.append(f"\n[{agent_name}]: {result}")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def invoke(
        self,
        user_message: str,
        *,
        session_key: str | None = None,
    ) -> str:
        """Execute multi-agent coordination and return the final result.

        Args:
            user_message: The user's task description.
            session_key: Optional session key for memory persistence.

        Returns:
            The final synthesized answer string.
        """
        graph = self.create_multi_agent_graph()

        initial_state: MultiAgentState = {
            "messages": [HumanMessage(content=user_message)],
            "current_agent": None,
            "task_plan": None,
            "agent_results": {},
            "total_iterations": 0,
            "max_total_iterations": self._max_total_iterations,
            "final_answer": None,
            "error": None,
        }

        logger.info(
            "multi_agent_invoke",
            user_message=user_message[:100],
            max_total_iterations=self._max_total_iterations,
        )

        result = await graph.ainvoke(initial_state)

        final_answer = result.get("final_answer")
        if final_answer:
            return final_answer

        error = result.get("error")
        if error:
            return f"Error: {error}"

        return "Multi-agent coordination completed without producing a final answer."
