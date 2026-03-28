"""Graph-stage middleware for orchestrator mode."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from smartclaw.agent.artifact_store import ArtifactStore
from smartclaw.agent.orchestration_models import (
    ArtifactEnvelope,
    StepRunRecord,
    TodoItem,
    TodoPlan,
    todo_identifier,
)
from smartclaw.agent.plan_manager import PlanManager
from smartclaw.capabilities.governance import build_approval_request
from smartclaw.steps.registry import StepRegistry

StageName = Literal["plan", "dispatch", "execute", "normalize", "review", "synthesize", "finish"]


@dataclass
class MiddlewareContext:
    """Shared runtime context passed to graph-stage middlewares."""

    stage: StageName
    plan_manager: PlanManager
    step_registry: StepRegistry | None
    artifact_store: ArtifactStore
    session_key: str | None
    emit_diagnostic: Callable[[str, dict[str, Any]], Awaitable[None]]
    serialize_todos: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]
    serialize_batches: Callable[[list[dict[str, Any]], dict[str, Any] | None], list[dict[str, Any]]]


class StageMiddleware(Protocol):
    """Middleware hook interface for orchestrator graph stages."""

    async def before_stage(
        self,
        state: dict[str, Any],
        ctx: MiddlewareContext,
    ) -> dict[str, Any]:
        """Return optional state updates before the stage executes."""

    async def after_stage(
        self,
        state: dict[str, Any],
        update: dict[str, Any],
        ctx: MiddlewareContext,
    ) -> dict[str, Any]:
        """Return optional state updates after the stage executes."""


class MiddlewareRunner:
    """Execute graph-stage middlewares in a deterministic order."""

    def __init__(self, middlewares: list[StageMiddleware]) -> None:
        self._middlewares = list(middlewares)

    async def run_before(
        self,
        stage: StageName,
        state: dict[str, Any],
        *,
        ctx: MiddlewareContext,
    ) -> dict[str, Any]:
        del stage
        combined: dict[str, Any] = {}
        effective_state = dict(state)
        for middleware in self._middlewares:
            update = await middleware.before_stage(effective_state, ctx)
            if not update:
                continue
            combined.update(update)
            effective_state.update(update)
        return combined

    async def run_after(
        self,
        stage: StageName,
        state: dict[str, Any],
        update: dict[str, Any],
        *,
        ctx: MiddlewareContext,
    ) -> dict[str, Any]:
        del stage
        combined: dict[str, Any] = {}
        effective_state = {**state, **update}
        effective_update = dict(update)
        for middleware in self._middlewares:
            middleware_update = await middleware.after_stage(effective_state, effective_update, ctx)
            if not middleware_update:
                continue
            combined.update(middleware_update)
            effective_update.update(middleware_update)
            effective_state.update(middleware_update)
        return combined


class GovernanceStageMiddleware:
    """Runtime governance guardrails enforced at stage boundaries."""

    async def before_stage(
        self,
        state: dict[str, Any],
        ctx: MiddlewareContext,
    ) -> dict[str, Any]:
        if ctx.stage != "dispatch":
            return {}
        plan = ctx.plan_manager.refresh_ready_todos(state.get("plan"))
        if plan is None:
            return {}
        approval_granted = bool(state.get("approval_granted"))
        approval_action = str(state.get("approval_action", "") or "").strip().lower()
        existing_pending_approval = [
            todo
            for todo in plan.get("todos", [])
            if isinstance(todo, dict)
            and str(todo.get("status")) == "pending_approval"
            and bool(todo.get("approval_required"))
        ]
        if approval_action == "report_only" and existing_pending_approval:
            skipped_ids = [todo_identifier(todo) for todo in existing_pending_approval]
            updated_plan = ctx.plan_manager.skip_pending_approval_todos(plan, skipped_ids)
            await ctx.emit_diagnostic(
                "governance.approval_skipped",
                {
                    "phase_index": (state.get("phase_index") or 0) + 1,
                    "action": approval_action,
                    "todo_ids": skipped_ids,
                },
            )
            return {
                "plan": updated_plan,
                "todos": updated_plan["todos"] if updated_plan else state.get("todos"),
                "clarification_request": None,
            }

        if approval_granted and existing_pending_approval:
            approved_ids = [todo_identifier(todo) for todo in existing_pending_approval]
            updated_plan = ctx.plan_manager.approve_pending_todos(plan, approved_ids)
            await ctx.emit_diagnostic(
                "governance.approval_granted",
                {
                    "phase_index": (state.get("phase_index") or 0) + 1,
                    "action": approval_action or "approve",
                    "todo_ids": approved_ids,
                },
            )
            return {
                "plan": updated_plan,
                "todos": updated_plan["todos"] if updated_plan else state.get("todos"),
                "clarification_request": None,
            }

        ready_todos = ctx.plan_manager.get_ready_todos(plan)
        approval_pending = [
            todo
            for todo in ready_todos
            if bool(todo.get("approval_required")) and not approval_granted
        ]
        if not approval_pending:
            return {"plan": plan, "todos": plan["todos"]}

        if approval_action == "report_only":
            skipped_ids = [todo_identifier(todo) for todo in approval_pending]
            updated_plan = ctx.plan_manager.skip_pending_approval_todos(plan, skipped_ids)
            await ctx.emit_diagnostic(
                "governance.approval_skipped",
                {
                    "phase_index": (state.get("phase_index") or 0) + 1,
                    "action": approval_action,
                    "todo_ids": skipped_ids,
                },
            )
            return {
                "plan": updated_plan,
                "todos": updated_plan["todos"] if updated_plan else state.get("todos"),
                "clarification_request": None,
            }

        updated_plan = ctx.plan_manager.mark_todos_pending_approval(
            plan,
            [todo_identifier(todo) for todo in approval_pending],
        )
        clarification_request = _build_todo_approval_request(
            state.get("capability_policy"),
            approval_pending,
            capability_pack=str(state.get("capability_pack", "") or ""),
            artifacts=state.get("artifacts"),
            step_run_records=state.get("step_run_records"),
        )
        await ctx.emit_diagnostic(
            "governance.approval_required",
            {
                "phase_index": (state.get("phase_index") or 0) + 1,
                "todo_ids": [todo_identifier(todo) for todo in approval_pending],
                "todo_titles": [str(todo.get("title", todo_identifier(todo))) for todo in approval_pending],
            },
        )
        return {
            "plan": updated_plan,
            "todos": updated_plan["todos"] if updated_plan else state.get("todos"),
            "clarification_request": clarification_request,
        }

    async def after_stage(
        self,
        state: dict[str, Any],
        update: dict[str, Any],
        ctx: MiddlewareContext,
    ) -> dict[str, Any]:
        del state, update, ctx
        return {}


class ArtifactStageMiddleware:
    """Normalize worker outputs into artifacts and step records."""

    async def before_stage(
        self,
        state: dict[str, Any],
        ctx: MiddlewareContext,
    ) -> dict[str, Any]:
        if ctx.stage not in {"normalize", "synthesize"}:
            return {}
        payload: dict[str, Any] = {
            "phase": ctx.stage,
            "phase_index": state.get("phase_index") or 0,
        }
        if ctx.stage == "normalize":
            payload["raw_result_count"] = len(state.get("raw_task_results") or [])
        else:
            payload["result_count"] = len(state.get("task_results") or [])
            payload["artifact_count"] = len(state.get("artifacts") or [])
        await ctx.emit_diagnostic("phase.started", payload)
        return {}

    async def after_stage(
        self,
        state: dict[str, Any],
        update: dict[str, Any],
        ctx: MiddlewareContext,
    ) -> dict[str, Any]:
        if ctx.stage == "normalize":
            return await self._normalize_artifacts(state, ctx)
        if ctx.stage == "synthesize":
            await ctx.emit_diagnostic(
                "phase.ended",
                {
                    "phase": "synthesize",
                    "phase_index": state.get("phase_index") or 0,
                    "completed": update.get("error") is None,
                },
            )
        return {}

    async def _normalize_artifacts(
        self,
        state: dict[str, Any],
        ctx: MiddlewareContext,
    ) -> dict[str, Any]:
        raw_task_results = list(state.get("raw_task_results") or [])
        existing_artifacts = list(state.get("artifacts") or [])
        existing_records = list(state.get("step_run_records") or [])
        existing_task_results = list(state.get("task_results") or [])
        normalized_records: list[StepRunRecord] = []
        new_artifacts: list[ArtifactEnvelope] = []
        resolved_session_key = state.get("session_key") or ctx.session_key

        for raw_result in raw_task_results:
            if not isinstance(raw_result, dict) or not raw_result.get("todo_id"):
                continue
            todo_id = str(raw_result.get("todo_id"))
            step_id = str(raw_result.get("step_id") or todo_id)
            artifact_ids: list[str] = []
            if raw_result.get("status") == "completed" and raw_result.get("result"):
                artifact_type = (
                    ctx.step_registry.artifact_type_for_step(step_id)
                    if ctx.step_registry is not None
                    else f"{step_id}_result"
                )
                artifact = ctx.artifact_store.create_artifact(
                    session_key=resolved_session_key,
                    step_id=step_id,
                    artifact_type=artifact_type,
                    result=str(raw_result.get("result", "")),
                    metadata={
                        "todo_id": todo_id,
                        "phase_index": int(raw_result.get("phase_index", 0) or 0),
                        "batch_id": str(raw_result.get("batch_id", "")),
                    },
                )
                new_artifacts.append(artifact)
                artifact_ids.append(artifact["artifact_id"])

            normalized_records.append(
                {
                    "todo_id": todo_id,
                    "step_id": step_id,
                    "title": str(raw_result.get("title", todo_id)),
                    "batch_id": str(raw_result.get("batch_id", "")),
                    "phase_index": int(raw_result.get("phase_index", 0) or 0),
                    "status": str(raw_result.get("status", "unknown")),
                    "result": str(raw_result.get("result", "")),
                    "error": str(raw_result.get("error")) if raw_result.get("error") is not None else None,
                    "attempts": int(raw_result.get("attempts", 1) or 1),
                    "task_group": str(raw_result.get("task_group", "default")),
                    "artifact_ids": artifact_ids,
                }
            )

        await ctx.emit_diagnostic(
            "phase.ended",
            {
                "phase": "normalize",
                "phase_index": state.get("phase_index") or 0,
                "record_count": len(normalized_records),
                "artifact_count": len(new_artifacts),
            },
        )
        return {
            "raw_task_results": [],
            "artifacts": existing_artifacts + new_artifacts,
            "step_run_records": existing_records + normalized_records,
            "task_results": existing_task_results + normalized_records,
        }


class StepTrackingStageMiddleware:
    """Emit stage-level tracking diagnostics from a single place."""

    async def before_stage(
        self,
        state: dict[str, Any],
        ctx: MiddlewareContext,
    ) -> dict[str, Any]:
        if ctx.stage == "execute":
            await ctx.emit_diagnostic(
                "phase.started",
                {
                    "phase": "execute",
                    "phase_index": (state.get("phase_index") or 0) + 1,
                    "batch_count": len(state.get("dispatch_batches") or []),
                },
            )
        return {}

    async def after_stage(
        self,
        state: dict[str, Any],
        update: dict[str, Any],
        ctx: MiddlewareContext,
    ) -> dict[str, Any]:
        if ctx.stage == "plan":
            plan = update.get("plan")
            if isinstance(plan, dict):
                await ctx.emit_diagnostic(
                    "plan.created",
                    {
                        "objective": plan.get("objective"),
                        "strategy": plan.get("strategy"),
                        "planner_source": update.get("planner_source"),
                        "plan_version": plan.get("plan_version"),
                        "todo_count": len(plan.get("todos", [])),
                        "todos": ctx.serialize_todos(plan.get("todos", [])),
                    },
                )
        elif ctx.stage == "dispatch":
            plan = update.get("plan")
            if isinstance(plan, dict):
                ready_todos = ctx.plan_manager.get_ready_todos(plan)
                approval_pending_ids = [
                    todo_identifier(todo)
                    for todo in plan.get("todos", [])
                    if isinstance(todo, dict) and str(todo.get("status")) == "pending_approval"
                ]
                await ctx.emit_diagnostic(
                    "dispatch.created",
                    {
                        "phase_index": (state.get("phase_index") or 0) + 1,
                        "batch_count": len(update.get("dispatch_batches") or []),
                        "ready_todo_ids": [todo_identifier(todo) for todo in ready_todos],
                        "ready_todos": ctx.serialize_todos(ready_todos),
                        "approval_pending_todo_ids": approval_pending_ids,
                        "batches": ctx.serialize_batches(update.get("dispatch_batches") or [], plan),
                    },
                )
        elif ctx.stage == "execute":
            await ctx.emit_diagnostic(
                "phase.ended",
                {
                    "phase": "execute",
                    "phase_index": (state.get("phase_index") or 0) + 1,
                    "result_count": len(update.get("raw_task_results") or []),
                },
            )
        elif ctx.stage == "review":
            plan = update.get("plan")
            if isinstance(plan, dict):
                ready_todos = ctx.plan_manager.get_ready_todos(plan)
                await ctx.emit_diagnostic(
                    "plan.updated",
                    {
                        "phase_index": update.get("phase_index") or ((state.get("phase_index") or 0) + 1),
                        "phase_status": update.get("phase_status"),
                        "planner_source": update.get("planner_source", "static"),
                        "replanning_count": update.get("replanning_count"),
                        "ready_todo_ids": [todo_identifier(todo) for todo in ready_todos],
                        "ready_todos": ctx.serialize_todos(ready_todos),
                        "todos": ctx.serialize_todos(plan.get("todos", [])),
                    },
                )
        return {}


def _build_todo_approval_request(
    capability_policy: dict[str, Any] | None,
    approval_pending: list[TodoItem],
    *,
    capability_pack: str = "",
    artifacts: list[dict[str, Any]] | None = None,
    step_run_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if not approval_pending:
        return None
    base_request = build_approval_request(capability_policy)
    titles = [str(todo.get("title", todo_identifier(todo) or "task")) for todo in approval_pending]
    details = list(base_request.get("details") or [])
    details.append(f"待审批步骤: {', '.join(titles)}")
    finding_preview = _approval_findings_preview(artifacts, step_run_records)
    if finding_preview:
        details.append(f"检查摘要: {finding_preview}")
    action_preview = _approval_action_preview(approval_pending)
    if action_preview:
        details.append(f"拟执行动作: {action_preview}")
    details.append("原因: 待审批步骤包含写操作或中高风险变更。")
    base_request["question"] = base_request["question"]
    base_request["details"] = details
    active_pack = str((capability_policy or {}).get("name", "") or capability_pack)
    if active_pack == "security-governance":
        base_request["options"] = ["approve", "report_only", "cancel"]
        base_request["option_descriptions"] = {
            "approve": "继续执行待审批的整改或加固步骤。",
            "report_only": "跳过整改步骤，仅基于当前检查结果继续生成报告。",
            "cancel": "终止本次执行，不再继续后续步骤。",
        }
    return base_request


def _approval_findings_preview(
    artifacts: list[dict[str, Any]] | None,
    step_run_records: list[dict[str, Any]] | None,
) -> str:
    for artifact in reversed(list(artifacts or [])):
        if not isinstance(artifact, dict):
            continue
        producer_step = str(artifact.get("producer_step", "") or "")
        artifact_type = str(artifact.get("artifact_type", "") or "")
        summary = str(artifact.get("summary", "") or "").strip()
        if summary and (producer_step == "inspect" or artifact_type == "inspection_result"):
            return _truncate_preview(summary)
    for record in reversed(list(step_run_records or [])):
        if not isinstance(record, dict):
            continue
        if str(record.get("step_id", "") or "") != "inspect":
            continue
        result = str(record.get("result", "") or "").strip()
        if result:
            return _truncate_preview(result)
    return ""


def _approval_action_preview(approval_pending: list[TodoItem]) -> str:
    actions = [str(todo.get("title", todo_identifier(todo) or "task")).strip() for todo in approval_pending]
    return ", ".join(item for item in actions if item)


def _truncate_preview(text: str, limit: int = 220) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."
