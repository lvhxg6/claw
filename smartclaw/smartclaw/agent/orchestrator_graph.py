"""Orchestrator graph — staged planning and controlled worker dispatch."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph as _CompiledStateGraph

from smartclaw.agent.dispatch_policy import DispatchPolicy
from smartclaw.agent.dispatch_tasks import DispatchTasks
from smartclaw.agent.graph import build_graph
from smartclaw.agent.plan_manager import PlanManager
from smartclaw.agent.state import AgentState
from smartclaw.capabilities.governance import build_schema_retry_prompt, validate_structured_output
from smartclaw.providers.config import ModelConfig

type CompiledStateGraph = _CompiledStateGraph[Any, Any, Any, Any]


def build_orchestrator_graph(
    model_config: ModelConfig,
    tools: list[BaseTool],
    stream_callback: Callable[[str], None] | None = None,
    tool_result_guard: Any | None = None,
    session_pruner: Any | None = None,
    summarizer: Any | None = None,
    session_key: str | None = None,
    loop_detector: Any | None = None,
    *,
    max_batch_size: int = 4,
    max_concurrent_workers: int = 4,
    max_phases: int = 8,
) -> CompiledStateGraph:
    """Build an orchestrator graph that wraps the classic execution graph."""
    classic_graph = build_graph(
        model_config,
        tools,
        stream_callback,
        tool_result_guard=tool_result_guard,
        session_pruner=session_pruner,
        summarizer=summarizer,
        session_key=session_key,
        loop_detector=loop_detector,
    )
    plan_manager = PlanManager()
    dispatch_policy = DispatchPolicy(max_batch_size=max_batch_size)
    spawn_tool = next((tool for tool in tools if tool.name == "spawn_sub_agent"), None)
    dispatcher = DispatchTasks(
        spawn_tool=spawn_tool,
        max_concurrent_workers=max_concurrent_workers,
    )

    async def _plan(state: AgentState) -> dict[str, Any]:
        plan = plan_manager.create_initial_plan(state.get("messages", []))
        await _emit_diagnostic(
            "plan.created",
            {
                "objective": plan["objective"],
                "strategy": plan.get("strategy"),
                "todo_count": len(plan["todos"]),
                "todos": _serialize_todos(plan.get("todos", [])),
            },
        )
        return {
            "plan": plan,
            "todos": plan["todos"],
            "current_phase": "planning",
            "phase_status": "completed",
            "phase_index": 0,
            "dispatch_batches": [],
            "task_results": [],
        }

    async def _dispatch(state: AgentState) -> dict[str, Any]:
        plan = plan_manager.refresh_ready_todos(state.get("plan"))
        phase_index = state.get("phase_index") or 0
        ready_todos = plan_manager.get_ready_todos(plan)
        batches = dispatch_policy.build_batches(ready_todos) if dispatcher.enabled else []
        normalized_batches = [
            {
                "batch_id": f"phase-{phase_index + 1}-batch-{index + 1}",
                "todo_ids": batch["todo_ids"],
                "parallel": batch["parallel"],
            }
            for index, batch in enumerate(batches)
        ]
        if normalized_batches:
            todo_ids = [todo_id for batch in normalized_batches for todo_id in batch["todo_ids"]]
            plan = plan_manager.mark_todos_in_progress(plan, todo_ids)

        await _emit_diagnostic(
            "dispatch.created",
            {
                "phase_index": phase_index + 1,
                "batch_count": len(normalized_batches),
                "ready_todo_ids": [todo["id"] for todo in ready_todos],
                "ready_todos": _serialize_todos(ready_todos),
                "batches": _serialize_batches(normalized_batches, plan),
            },
        )
        return {
            "plan": plan,
            "todos": plan["todos"] if plan else state.get("todos"),
            "current_phase": "dispatch",
            "phase_status": "ready" if normalized_batches else "skipped",
            "dispatch_batches": normalized_batches,
        }

    async def _execute(state: AgentState) -> dict[str, Any]:
        phase_index = (state.get("phase_index") or 0) + 1
        dispatch_batches = state.get("dispatch_batches") or []
        plan = state.get("plan")
        task_results = list(state.get("task_results") or [])
        capability_policy = state.get("capability_policy") or {}
        dispatcher = DispatchTasks(
            spawn_tool=spawn_tool,
            max_concurrent_workers=max_concurrent_workers,
            max_task_retries=int(capability_policy.get("max_task_retries", 0) or 0),
            retry_on_error=bool(capability_policy.get("retry_on_error", True)),
            concurrency_limits=dict(capability_policy.get("concurrency_limits", {}) or {}),
        )

        await _emit_diagnostic(
            "phase.started",
            {
                "phase": "execute",
                "phase_index": phase_index,
                "batch_count": len(dispatch_batches),
            },
        )

        phase_results: list[dict[str, Any]] = []
        if isinstance(plan, dict) and dispatch_batches:
            phase_results = await dispatcher.run_batches(
                plan=plan,
                batches=dispatch_batches,
                phase_index=phase_index,
            )

        await _emit_diagnostic(
            "phase.ended",
            {
                "phase": "execute",
                "phase_index": phase_index,
                "result_count": len(phase_results),
            },
        )

        return {
            "current_phase": "execute",
            "phase_status": "completed" if phase_results or not dispatch_batches else "failed",
            "task_results": task_results + phase_results,
        }

    async def _review(state: AgentState) -> dict[str, Any]:
        phase_index = (state.get("phase_index") or 0) + 1
        updated_plan = plan_manager.apply_results(state.get("plan"), state.get("task_results"))
        ready_todos = plan_manager.get_ready_todos(updated_plan)
        if plan_manager.is_plan_completed(updated_plan):
            phase_status = "completed"
        elif ready_todos:
            phase_status = "ready"
        elif plan_manager.has_remaining_work(updated_plan):
            phase_status = "blocked"
        else:
            phase_status = "completed"

        await _emit_diagnostic(
            "plan.updated",
            {
                "phase_index": phase_index,
                "phase_status": phase_status,
                "ready_todo_ids": [todo["id"] for todo in ready_todos],
                "ready_todos": _serialize_todos(ready_todos),
                "todos": _serialize_todos(updated_plan.get("todos", [])) if updated_plan else [],
            },
        )
        return {
            "plan": updated_plan,
            "todos": updated_plan["todos"] if updated_plan else state.get("todos"),
            "current_phase": "review",
            "phase_status": phase_status,
            "phase_index": phase_index,
            "dispatch_batches": [],
        }

    async def _synthesize(state: AgentState) -> dict[str, Any]:
        plan = state.get("plan")
        task_results = list(state.get("task_results") or [])
        objective = plan.get("objective", "") if isinstance(plan, dict) else ""
        capability_policy = state.get("capability_policy") or {}
        messages = list(state.get("messages", []))
        messages.append(_build_synthesis_message(objective, plan, task_results, capability_policy))

        await _emit_diagnostic(
            "phase.started",
            {
                "phase": "synthesize",
                "phase_index": state.get("phase_index") or 0,
                "result_count": len(task_results),
            },
        )

        result = await classic_graph.ainvoke({**state, "messages": messages})
        final_answer = result.get("final_answer")
        structured_result, validation = validate_structured_output(final_answer, capability_policy)
        await _emit_diagnostic(
            "schema.validation",
            {
                "phase_index": state.get("phase_index") or 0,
                "valid": validation.get("valid", True),
                "reason": validation.get("reason"),
            },
        )

        retry_count = max(0, int(capability_policy.get("max_schema_retries", 0) or 0))
        while not validation.get("valid", True) and retry_count > 0:
            retry_messages = list(state.get("messages", []))
            retry_messages.append(_build_synthesis_message(objective, plan, task_results, capability_policy))
            retry_messages.append(
                HumanMessage(
                    content=build_schema_retry_prompt(objective, capability_policy, validation)
                )
            )
            result = await classic_graph.ainvoke({**state, "messages": retry_messages})
            final_answer = result.get("final_answer")
            structured_result, validation = validate_structured_output(final_answer, capability_policy)
            await _emit_diagnostic(
                "schema.validation",
                {
                    "phase_index": state.get("phase_index") or 0,
                    "valid": validation.get("valid", True),
                    "reason": validation.get("reason"),
                    "retry_remaining": retry_count - 1,
                },
            )
            retry_count -= 1

        merged_error = _merge_result_error(result.get("error"), validation)

        if plan_manager.is_plan_completed(plan):
            plan = plan_manager.mark_plan_completed(plan)

        await _emit_diagnostic(
            "phase.ended",
            {
                "phase": "synthesize",
                "phase_index": state.get("phase_index") or 0,
                "completed": merged_error is None,
            },
        )

        return {
            "messages": result.get("messages", []),
            "iteration": result.get("iteration", 0),
            "final_answer": result.get("final_answer"),
            "summary": result.get("summary"),
            "sub_agent_depth": result.get("sub_agent_depth"),
            "token_stats": result.get("token_stats"),
            "clarification_request": result.get("clarification_request"),
            "plan": plan,
            "todos": plan["todos"] if plan else state.get("todos"),
            "current_phase": "completed",
            "phase_status": "completed" if merged_error is None else "failed",
            "structured_result": structured_result,
            "schema_validation": validation,
            "error": merged_error,
            "task_results": task_results
            + [
                {
                    "phase": "synthesize",
                    "status": "completed" if merged_error is None else "failed",
                    "final_answer": result.get("final_answer"),
                    "error": merged_error,
                }
            ],
        }

    def _after_dispatch(state: AgentState) -> str:
        return "execute" if state.get("dispatch_batches") else "synthesize"

    def _after_review(state: AgentState) -> str:
        plan = state.get("plan")
        phase_index = state.get("phase_index") or 0
        if phase_index >= max(1, max_phases):
            return "synthesize"
        if plan_manager.is_plan_completed(plan):
            return "synthesize"
        if plan_manager.get_ready_todos(plan):
            return "dispatch"
        return "synthesize"

    graph = StateGraph(AgentState)
    graph.add_node("plan", _plan)
    graph.add_node("dispatch", _dispatch)
    graph.add_node("execute", _execute)
    graph.add_node("review", _review)
    graph.add_node("synthesize", _synthesize)
    graph.set_entry_point("plan")
    graph.add_edge("plan", "dispatch")
    graph.add_conditional_edges(
        "dispatch",
        _after_dispatch,
        {"execute": "execute", "synthesize": "synthesize"},
    )
    graph.add_edge("execute", "review")
    graph.add_conditional_edges(
        "review",
        _after_review,
        {"dispatch": "dispatch", "synthesize": "synthesize"},
    )
    graph.add_edge("synthesize", END)
    return graph.compile()


def _build_synthesis_message(
    objective: str,
    plan: dict[str, Any] | None,
    task_results: list[dict[str, Any]],
    capability_policy: dict[str, Any] | None = None,
) -> HumanMessage:
    lines = [f"Objective: {objective}", "", "Execution plan status:"]
    if isinstance(plan, dict):
        for todo in plan.get("todos", []):
            if isinstance(todo, dict):
                lines.append(
                    f"- [{todo.get('status', 'unknown')}] {todo.get('id', 'task')}: {todo.get('title', '')}"
                )
    else:
        lines.append("- No explicit plan available.")

    lines.append("")
    lines.append("Subtask execution results:")
    if task_results:
        for result in task_results:
            if result.get("todo_id"):
                lines.append(
                    f"- [{result.get('status', 'unknown')}] {result.get('todo_id')}: {result.get('result', '')}"
                )
    else:
        lines.append("- No dispatched subtasks were executed.")

    lines.append("")
    if capability_policy and capability_policy.get("schema_enforced") and capability_policy.get("result_schema"):
        lines.append("Structured output policy:")
        lines.append("Return valid JSON only, conforming to this schema:")
        lines.append(str(capability_policy.get("result_schema", "")))
        lines.append("")
    lines.append("Provide the final answer based on the original objective and the execution results.")
    return HumanMessage(content="\n".join(lines))


def _serialize_todos(todos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    serialized: list[dict[str, Any]] = []
    for todo in todos:
        if not isinstance(todo, dict):
            continue
        serialized.append(
            {
                "id": todo.get("id"),
                "title": todo.get("title"),
                "kind": todo.get("kind"),
                "status": todo.get("status"),
                "parallelizable": bool(todo.get("parallelizable", False)),
                "depends_on": list(todo.get("depends_on", [])),
            }
        )
    return serialized


def _serialize_batches(
    batches: list[dict[str, Any]],
    plan: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    todos_by_id = {
        todo.get("id"): todo
        for todo in (plan or {}).get("todos", [])
        if isinstance(todo, dict) and todo.get("id")
    }
    serialized: list[dict[str, Any]] = []
    for batch in batches:
        todo_ids = [todo_id for todo_id in batch.get("todo_ids", []) if isinstance(todo_id, str)]
        serialized.append(
            {
                "batch_id": batch.get("batch_id"),
                "parallel": bool(batch.get("parallel")),
                "todo_ids": todo_ids,
                "todo_titles": [
                    str(todos_by_id[todo_id].get("title", todo_id))
                    for todo_id in todo_ids
                    if todo_id in todos_by_id
                ],
            }
        )
    return serialized


def _merge_result_error(error: Any, validation: dict[str, Any]) -> str | None:
    if error:
        return str(error)
    if validation.get("valid", True):
        return None
    return f"Capability pack schema validation failed: {validation.get('error', validation.get('reason', 'unknown'))}"


async def _emit_diagnostic(event_name: str, payload: dict[str, Any]) -> None:
    try:
        from smartclaw.observability import diagnostic_bus as _dbus

        await _dbus.emit(event_name, payload)
    except Exception:
        pass
