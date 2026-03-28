"""Orchestrator graph — staged planning and controlled worker dispatch."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph as _CompiledStateGraph

from smartclaw.agent.artifact_store import ArtifactStore
from smartclaw.agent.dispatch_policy import DispatchPolicy
from smartclaw.agent.dispatch_tasks import DispatchTasks
from smartclaw.agent.graph import build_graph
from smartclaw.agent.llm_planner import LLMPlanner
from smartclaw.agent.orchestrator_middleware import (
    ArtifactStageMiddleware,
    GovernanceStageMiddleware,
    MiddlewareContext,
    MiddlewareRunner,
    StageName,
    StepTrackingStageMiddleware,
)
from smartclaw.agent.orchestration_models import (
    TodoItem,
    TodoPlan,
    todo_identifier,
    todo_step_identifier,
)
from smartclaw.agent.plan_manager import PlanManager
from smartclaw.agent.state import AgentState
from smartclaw.capabilities.registry import CapabilityPackRegistry
from smartclaw.capabilities.governance import (
    build_schema_retry_prompt,
    validate_structured_output,
)
from smartclaw.providers.config import ModelConfig
from smartclaw.skills.loader import SkillsLoader
from smartclaw.steps.registry import StepRegistry

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
    capability_registry: CapabilityPackRegistry | None = None,
    step_registry: StepRegistry | None = None,
    skills_loader: SkillsLoader | None = None,
    capability_pack: str | None = None,
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
    plan_manager = PlanManager(
        step_registry=step_registry,
        capability_registry=capability_registry,
        capability_pack=capability_pack,
    )
    llm_planner = LLMPlanner(
        model_config=model_config,
        step_registry=step_registry,
        capability_registry=capability_registry,
        capability_pack=capability_pack,
    )
    dispatch_policy = DispatchPolicy(max_batch_size=max_batch_size)
    spawn_tool = next((tool for tool in tools if tool.name == "spawn_sub_agent"), None)
    artifact_store = ArtifactStore()
    middleware_runner = MiddlewareRunner(
        [
            GovernanceStageMiddleware(),
            ArtifactStageMiddleware(),
            StepTrackingStageMiddleware(),
        ]
    )

    def _load_skill_context(skill_name: str) -> str:
        if skills_loader is None or not skill_name:
            return ""
        return skills_loader.load_skills_for_context([skill_name])

    async def _run_stage(
        stage: StageName,
        state: AgentState,
        handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        ctx = MiddlewareContext(
            stage=stage,
            plan_manager=plan_manager,
            step_registry=step_registry,
            artifact_store=artifact_store,
            session_key=session_key,
            emit_diagnostic=_emit_diagnostic,
            serialize_todos=_serialize_todos,
            serialize_batches=_serialize_batches,
        )
        before_update = await middleware_runner.run_before(stage, state, ctx=ctx)
        effective_state = {**state, **before_update}
        stage_update = await handler(effective_state)
        merged_update = {**before_update, **stage_update}
        after_update = await middleware_runner.run_after(stage, effective_state, merged_update, ctx=ctx)
        merged_update.update(after_update)
        return merged_update

    async def _plan_core(state: dict[str, Any]) -> dict[str, Any]:
        if state.get("plan") and (
            state.get("approval_action") or state.get("approval_granted") is not None
        ):
            existing_plan = plan_manager.refresh_ready_todos(state.get("plan"))
            return {
                "plan": existing_plan,
                "todos": existing_plan["todos"] if existing_plan else state.get("todos"),
                "current_phase": "plan",
                "phase_status": "completed",
                "phase_index": state.get("phase_index") or 0,
                "dispatch_batches": state.get("dispatch_batches") or [],
                "raw_task_results": state.get("raw_task_results") or [],
                "task_results": state.get("task_results") or [],
                "artifacts": state.get("artifacts") or [],
                "step_run_records": state.get("step_run_records") or [],
                "replanning_count": state.get("replanning_count") or 0,
                "planner_source": "checkpoint_resume",
                "clarification_request": None,
            }
        plan = await llm_planner.create_plan(
            state.get("messages", []),
            artifacts=state.get("artifacts"),
            step_run_records=state.get("step_run_records"),
            current_plan=state.get("plan"),
        )
        planner_source = "llm"
        if plan is None:
            plan = plan_manager.create_initial_plan(
                state.get("messages", []),
                artifacts=state.get("artifacts"),
                current_plan=state.get("plan"),
            )
            planner_source = "rule_fallback"
        return {
            "plan": plan,
            "todos": plan["todos"],
            "current_phase": "plan",
            "phase_status": "completed",
            "phase_index": 0,
            "dispatch_batches": [],
            "raw_task_results": [],
            "task_results": [],
            "artifacts": list(state.get("artifacts") or []),
            "step_run_records": list(state.get("step_run_records") or []),
            "replanning_count": 0,
            "planner_source": planner_source,
        }

    async def _dispatch_core(state: dict[str, Any]) -> dict[str, Any]:
        plan = plan_manager.refresh_ready_todos(state.get("plan"))
        phase_index = state.get("phase_index") or 0
        ready_todos = plan_manager.get_ready_todos(plan)
        batches = dispatch_policy.build_batches(ready_todos) if spawn_tool is not None else []
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
        phase_status = (
            "ready"
            if normalized_batches
            else "awaiting_approval"
            if plan_manager.has_pending_approval(plan)
            else "skipped"
        )
        return {
            "plan": plan,
            "todos": plan["todos"] if plan else state.get("todos"),
            "current_phase": "dispatch",
            "phase_status": phase_status,
            "dispatch_batches": normalized_batches,
        }

    async def _execute_core(state: dict[str, Any]) -> dict[str, Any]:
        phase_index = (state.get("phase_index") or 0) + 1
        dispatch_batches = state.get("dispatch_batches") or []
        plan = state.get("plan")
        capability_policy = state.get("capability_policy") or {}
        dispatch_runner = DispatchTasks(
            spawn_tool=spawn_tool,
            max_concurrent_workers=max_concurrent_workers,
            max_task_retries=int(capability_policy.get("max_task_retries", 0) or 0),
            retry_on_error=bool(capability_policy.get("retry_on_error", True)),
            concurrency_limits=dict(capability_policy.get("concurrency_limits", {}) or {}),
            skill_context_provider=_load_skill_context,
        )

        phase_results: list[dict[str, Any]] = []
        if isinstance(plan, dict) and dispatch_batches:
            phase_results = await dispatch_runner.run_batches(
                plan=plan,
                batches=dispatch_batches,
                phase_index=phase_index,
            )

        return {
            "current_phase": "execute",
            "phase_status": "completed" if phase_results or not dispatch_batches else "failed",
            "raw_task_results": phase_results,
        }

    async def _normalize_core(state: dict[str, Any]) -> dict[str, Any]:
        return {
            "current_phase": "normalize",
            "phase_status": "completed",
        }

    async def _review_core(state: dict[str, Any]) -> dict[str, Any]:
        phase_index = (state.get("phase_index") or 0) + 1
        updated_plan = plan_manager.apply_results(state.get("plan"), state.get("step_run_records"))
        replanning_count = int(state.get("replanning_count") or 0)
        planner_source = "static"
        capability_policy = state.get("capability_policy") or {}
        ready_todos = plan_manager.get_ready_todos(updated_plan)
        guardrail_status = _detect_repeated_error_guard(
            step_run_records=state.get("step_run_records"),
            capability_policy=capability_policy,
        )

        if guardrail_status is None and _should_attempt_replan(plan_manager, updated_plan, ready_todos):
            replanned_plan = await llm_planner.replan(
                state.get("messages", []),
                current_plan=updated_plan,
                artifacts=state.get("artifacts"),
                step_run_records=state.get("step_run_records"),
            )
            if replanned_plan is not None:
                updated_plan = _merge_replanned_plan(updated_plan, replanned_plan)
                updated_plan = plan_manager.refresh_ready_todos(updated_plan)
                planner_source = "llm_replan"
            else:
                fallback_replan = plan_manager.replan(
                    state.get("messages", []),
                    artifacts=state.get("artifacts"),
                    current_plan=updated_plan,
                )
                updated_plan = _merge_replanned_plan(updated_plan, fallback_replan)
                updated_plan = plan_manager.refresh_ready_todos(updated_plan)
                planner_source = "rule_fallback"
            replanning_count += 1

        ready_todos = plan_manager.get_ready_todos(updated_plan)
        if guardrail_status is not None:
            phase_status = "guarded_stop"
        elif plan_manager.is_plan_completed(updated_plan):
            phase_status = "completed"
        elif ready_todos:
            phase_status = "ready"
        elif plan_manager.has_pending_approval(updated_plan):
            phase_status = "awaiting_approval"
        elif plan_manager.has_remaining_work(updated_plan):
            phase_status = "blocked"
        else:
            phase_status = "completed"

        if phase_status == "ready" and planner_source == "static":
            replanning_count += 1
        return {
            "plan": updated_plan,
            "todos": updated_plan["todos"] if updated_plan else state.get("todos"),
            "current_phase": "review",
            "phase_status": phase_status,
            "phase_index": phase_index,
            "dispatch_batches": [],
            "replanning_count": replanning_count,
            "planner_source": planner_source,
            "guardrail_status": guardrail_status,
        }

    async def _finish_core(state: dict[str, Any]) -> dict[str, Any]:
        guardrail_status = state.get("guardrail_status") or _infer_budget_guardrail(
            state,
            max_phases=max_phases,
        )
        final_answer = state.get("final_answer")
        phase_status = state.get("phase_status") or "completed"
        if guardrail_status is not None and state.get("phase_status") != "awaiting_approval":
            final_answer = _build_guardrail_fallback_message(state, guardrail_status)
            if str(guardrail_status.get("reason")) == "budget_exceeded":
                phase_status = "budget_exceeded"
            else:
                phase_status = "guarded_stop"
        return {
            "current_phase": "finish",
            "phase_status": phase_status,
            "plan": state.get("plan"),
            "todos": state.get("todos"),
            "task_results": state.get("task_results"),
            "artifacts": state.get("artifacts"),
            "step_run_records": state.get("step_run_records"),
            "clarification_request": state.get("clarification_request"),
            "final_answer": final_answer,
            "error": state.get("error"),
            "guardrail_status": guardrail_status,
        }

    async def _synthesize_core(state: dict[str, Any]) -> dict[str, Any]:
        plan = state.get("plan")
        task_results = list(state.get("task_results") or [])
        artifacts = list(state.get("artifacts") or [])
        objective = plan.get("objective", "") if isinstance(plan, dict) else ""
        capability_policy = state.get("capability_policy") or {}
        messages = list(state.get("messages", []))
        messages.append(_build_synthesis_message(objective, plan, task_results, artifacts, capability_policy))

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
            retry_messages.append(
                _build_synthesis_message(objective, plan, task_results, artifacts, capability_policy)
            )
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
            "current_phase": "finish",
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
        if state.get("dispatch_batches"):
            return "execute"
        if state.get("phase_status") == "awaiting_approval":
            return "finish"
        return "synthesize"

    def _after_review(state: AgentState) -> str:
        plan = state.get("plan")
        phase_index = int(state.get("phase_index") or 0)
        capability_policy = state.get("capability_policy") or {}
        replanning_count = int(state.get("replanning_count") or 0)
        max_replanning_rounds = int(capability_policy.get("max_replanning_rounds", 0) or 0)

        if state.get("guardrail_status"):
            return "finish"
        if phase_index >= max(1, max_phases):
            return "finish"
        if max_replanning_rounds > 0 and replanning_count > max_replanning_rounds:
            return "finish"
        if plan_manager.is_plan_completed(plan):
            return "synthesize"
        if plan_manager.get_ready_todos(plan):
            return "dispatch"
        if plan_manager.has_pending_approval(plan):
            return "finish"
        return "synthesize"

    async def _plan(state: AgentState) -> dict[str, Any]:
        return await _run_stage("plan", state, _plan_core)

    async def _dispatch(state: AgentState) -> dict[str, Any]:
        return await _run_stage("dispatch", state, _dispatch_core)

    async def _execute(state: AgentState) -> dict[str, Any]:
        return await _run_stage("execute", state, _execute_core)

    async def _normalize(state: AgentState) -> dict[str, Any]:
        return await _run_stage("normalize", state, _normalize_core)

    async def _review(state: AgentState) -> dict[str, Any]:
        return await _run_stage("review", state, _review_core)

    async def _synthesize(state: AgentState) -> dict[str, Any]:
        return await _run_stage("synthesize", state, _synthesize_core)

    async def _finish(state: AgentState) -> dict[str, Any]:
        return await _run_stage("finish", state, _finish_core)

    graph = StateGraph(AgentState)
    graph.add_node("plan", _plan)
    graph.add_node("dispatch", _dispatch)
    graph.add_node("execute", _execute)
    graph.add_node("normalize", _normalize)
    graph.add_node("review", _review)
    graph.add_node("synthesize", _synthesize)
    graph.add_node("finish", _finish)
    graph.set_entry_point("plan")
    graph.add_edge("plan", "dispatch")
    graph.add_conditional_edges(
        "dispatch",
        _after_dispatch,
        {"execute": "execute", "synthesize": "synthesize", "finish": "finish"},
    )
    graph.add_edge("execute", "normalize")
    graph.add_edge("normalize", "review")
    graph.add_conditional_edges(
        "review",
        _after_review,
        {"dispatch": "dispatch", "synthesize": "synthesize", "finish": "finish"},
    )
    graph.add_edge("synthesize", END)
    graph.add_edge("finish", END)
    return graph.compile()


def _build_synthesis_message(
    objective: str,
    plan: dict[str, Any] | None,
    task_results: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    capability_policy: dict[str, Any] | None = None,
) -> HumanMessage:
    lines = [f"Objective: {objective}", "", "Execution plan status:"]
    if isinstance(plan, dict):
        for todo in plan.get("todos", []):
            if isinstance(todo, dict):
                lines.append(
                    f"- [{todo.get('status', 'unknown')}] {todo_identifier(todo) or 'task'}"
                    f" ({todo_step_identifier(todo) or 'step'}): {todo.get('title', '')}"
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
    lines.append("Artifacts:")
    if artifacts:
        for artifact in artifacts:
            lines.append(
                f"- [{artifact.get('status', 'unknown')}] {artifact.get('artifact_type', 'artifact')}: "
                f"{artifact.get('summary', '')}"
            )
    else:
        lines.append("- No artifacts were produced.")

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
                "todo_id": todo_identifier(todo),
                "step_id": todo_step_identifier(todo),
                "title": todo.get("title"),
                "kind": todo.get("kind"),
                "status": todo.get("status"),
                "parallelizable": bool(todo.get("parallelizable", False)),
                "depends_on": list(todo.get("depends_on", [])),
                "execution_mode": todo.get("execution_mode"),
                "plan_role": todo.get("plan_role"),
                "activation_mode": todo.get("activation_mode"),
                "display_policy": todo.get("display_policy"),
            }
        )
    return serialized


def _serialize_batches(
    batches: list[dict[str, Any]],
    plan: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    todos_by_id = {
        todo_identifier(todo): todo
        for todo in (plan or {}).get("todos", [])
        if isinstance(todo, dict) and todo_identifier(todo)
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


def _should_attempt_replan(
    plan_manager: PlanManager,
    plan: TodoPlan | None,
    ready_todos: list[TodoItem],
) -> bool:
    if plan is None:
        return False
    if plan_manager.has_pending_approval(plan):
        return False
    if plan_manager.is_plan_completed(plan):
        return True
    return not ready_todos and plan_manager.has_remaining_work(plan)


def _merge_replanned_plan(current_plan: TodoPlan | None, replanned_plan: TodoPlan) -> TodoPlan:
    if current_plan is None:
        return replanned_plan
    terminal_todos = [
        todo
        for todo in current_plan.get("todos", [])
        if isinstance(todo, dict) and str(todo.get("status")) in {"completed", "failed", "cancelled"}
    ]
    seen_todo_ids = {
        todo_identifier(todo)
        for todo in terminal_todos
        if isinstance(todo, dict) and todo_identifier(todo)
    }
    remaining_todos = []
    for todo in replanned_plan.get("todos", []):
        if not isinstance(todo, dict):
            continue
        todo_id = todo_identifier(todo)
        if todo_id and todo_id in seen_todo_ids:
            continue
        if todo_id:
            seen_todo_ids.add(todo_id)
        remaining_todos.append(todo)
    merged_plan = dict(replanned_plan)
    merged_plan["todos"] = terminal_todos + remaining_todos
    merged_plan["objective"] = str(replanned_plan.get("objective", current_plan.get("objective", "")))
    return merged_plan  # type: ignore[return-value]


def _merge_result_error(error: Any, validation: dict[str, Any]) -> str | None:
    if error:
        return str(error)
    if validation.get("valid", True):
        return None
    return f"Capability pack schema validation failed: {validation.get('error', validation.get('reason', 'unknown'))}"


def _detect_repeated_error_guard(
    *,
    step_run_records: list[dict[str, Any]] | None,
    capability_policy: dict[str, Any] | None,
) -> dict[str, Any] | None:
    threshold = int((capability_policy or {}).get("repeated_error_threshold", 0) or 0)
    if threshold <= 0:
        return None
    failed_records = [
        record
        for record in (step_run_records or [])
        if isinstance(record, dict) and str(record.get("status")) == "failed"
    ]
    if not failed_records:
        return None
    latest = failed_records[-1]
    latest_fingerprint = _error_fingerprint(latest)
    if not latest_fingerprint:
        return None
    if int(latest.get("attempts", 1) or 1) >= threshold:
        return {
            "reason": "repeated_error",
            "threshold": threshold,
            "step_id": str(latest.get("step_id", "")),
            "todo_id": str(latest.get("todo_id", "")),
            "error": str(latest.get("error") or latest.get("result") or ""),
            "fingerprint": latest_fingerprint,
            "source": "task_retries",
        }
    matching_tail = []
    for record in reversed(failed_records):
        if _error_fingerprint(record) != latest_fingerprint:
            break
        matching_tail.append(record)
    if len(matching_tail) >= threshold:
        return {
            "reason": "repeated_error",
            "threshold": threshold,
            "step_id": str(latest.get("step_id", "")),
            "todo_id": str(latest.get("todo_id", "")),
            "error": str(latest.get("error") or latest.get("result") or ""),
            "fingerprint": latest_fingerprint,
            "source": "repeated_failures",
        }
    return None


def _error_fingerprint(record: dict[str, Any]) -> str:
    step_id = str(record.get("step_id", "") or "")
    error = str(record.get("error") or record.get("result") or "").strip().lower()
    if not error:
        return ""
    normalized = " ".join(error.replace("error:", "").split())
    return f"{step_id}:{normalized}"


def _infer_budget_guardrail(
    state: dict[str, Any],
    *,
    max_phases: int,
) -> dict[str, Any] | None:
    if state.get("phase_status") == "awaiting_approval":
        return None
    capability_policy = state.get("capability_policy") or {}
    replanning_count = int(state.get("replanning_count") or 0)
    max_replanning_rounds = int(capability_policy.get("max_replanning_rounds", 0) or 0)
    phase_index = int(state.get("phase_index") or 0)
    if max_replanning_rounds > 0 and replanning_count > max_replanning_rounds:
        return {
            "reason": "budget_exceeded",
            "limit": "max_replanning_rounds",
            "current": replanning_count,
            "budget": max_replanning_rounds,
        }
    if phase_index >= max(1, max_phases):
        return {
            "reason": "budget_exceeded",
            "limit": "max_phases",
            "current": phase_index,
            "budget": max(1, max_phases),
        }
    return None


def _build_guardrail_fallback_message(
    state: dict[str, Any],
    guardrail_status: dict[str, Any],
) -> str:
    plan = state.get("plan") or {}
    todos = [
        todo
        for todo in plan.get("todos", [])
        if isinstance(todo, dict)
    ]
    completed = [str(todo.get("title", todo_identifier(todo))) for todo in todos if str(todo.get("status")) == "completed"]
    blocked = [
        str(todo.get("title", todo_identifier(todo)))
        for todo in todos
        if str(todo.get("status")) in {"failed", "pending", "blocked", "pending_approval"}
    ]
    lines = [f"Objective: {plan.get('objective', '')}".strip()]
    reason = str(guardrail_status.get("reason", "guardrail_stop"))
    if reason == "repeated_error":
        lines.append("Execution stopped because the same failure pattern repeated and automatic recovery was halted.")
        lines.append(
            f"Affected step: {guardrail_status.get('step_id', '')}."
        )
        if guardrail_status.get("error"):
            lines.append(f"Latest error: {guardrail_status['error']}")
        lines.append("Recommended next step: verify external dependencies or inputs before retrying.")
    else:
        lines.append("Execution stopped because the orchestration budget was exhausted.")
        lines.append(
            f"Exceeded limit: {guardrail_status.get('limit', 'budget')} "
            f"({guardrail_status.get('current', 0)}/{guardrail_status.get('budget', 0)})."
        )
        lines.append("Recommended next step: narrow the task scope or provide additional guidance before retrying.")
    if completed:
        lines.append(f"Completed steps: {', '.join(completed)}.")
    if blocked:
        lines.append(f"Remaining or blocked steps: {', '.join(blocked)}.")
    return "\n".join([line for line in lines if line])


async def _emit_diagnostic(event_name: str, payload: dict[str, Any]) -> None:
    try:
        from smartclaw.observability import diagnostic_bus as _dbus

        await _dbus.emit(event_name, payload)
    except Exception:
        pass
