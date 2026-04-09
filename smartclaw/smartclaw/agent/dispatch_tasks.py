"""dispatch_tasks — controlled worker fan-out for orchestrator mode."""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
from pathlib import Path
from typing import Any, TypedDict

import structlog
from langchain_core.tools import BaseTool

from smartclaw.agent.orchestration_models import todo_identifier, todo_step_identifier

logger = structlog.get_logger(component="agent.dispatch_tasks")

_TRUTHY = {"1", "true", "yes", "on"}
_TRACE_APPROVAL = os.environ.get("SMARTCLAW_TRACE_APPROVAL", "").strip().lower() in _TRUTHY


class DispatchTaskResult(TypedDict, total=False):
    """Normalized result returned by orchestrator task dispatch."""

    todo_id: str
    step_id: str
    title: str
    batch_id: str
    phase_index: int
    status: str
    result: str
    error: str | None


class DispatchTasks:
    """Run orchestrator batches through the low-level spawn_sub_agent primitive."""

    def __init__(
        self,
        *,
        spawn_tool: BaseTool | None,
        max_concurrent_workers: int = 4,
        max_task_retries: int = 0,
        retry_on_error: bool = True,
        concurrency_limits: dict[str, int] | None = None,
        skill_context_provider: Any | None = None,
        session_key: str | None = None,
    ) -> None:
        self._spawn_tool = spawn_tool
        self._max_concurrent_workers = max(1, max_concurrent_workers)
        self._max_task_retries = max(0, max_task_retries)
        self._retry_on_error = retry_on_error
        self._concurrency_limits = {
            str(group): max(1, int(limit))
            for group, limit in (concurrency_limits or {}).items()
        }
        self._skill_context_provider = skill_context_provider
        self._session_key = session_key

    @property
    def enabled(self) -> bool:
        """Whether dispatch can actually launch worker tasks."""
        return self._spawn_tool is not None

    async def run_batches(
        self,
        *,
        plan: dict[str, Any],
        batches: list[dict[str, Any]],
        phase_index: int,
    ) -> list[DispatchTaskResult]:
        """Execute a list of dispatch batches and aggregate results."""
        if self._spawn_tool is None or not batches:
            return []

        semaphore = asyncio.Semaphore(self._max_concurrent_workers)
        group_semaphores = {
            group: asyncio.Semaphore(limit)
            for group, limit in self._concurrency_limits.items()
        }
        results: list[DispatchTaskResult] = []
        for batch in batches:
            if isinstance(batch, dict):
                results.extend(
                    await self._run_batch(
                        batch,
                        plan=plan,
                        phase_index=phase_index,
                        semaphore=semaphore,
                        group_semaphores=group_semaphores,
                    )
                )
        return results

    async def _run_batch(
        self,
        batch: dict[str, Any],
        *,
        plan: dict[str, Any],
        phase_index: int,
        semaphore: asyncio.Semaphore,
        group_semaphores: dict[str, asyncio.Semaphore],
    ) -> list[DispatchTaskResult]:
        if self._spawn_tool is None:
            return []

        todo_ids = [todo_id for todo_id in batch.get("todo_ids", []) if isinstance(todo_id, str)]
        objective = str(plan.get("objective", ""))

        await _emit_diagnostic(
            "dispatch.batch_started",
            {
                "session_key": self._session_key,
                "batch_id": batch.get("batch_id"),
                "parallel": bool(batch.get("parallel")),
                "todo_ids": todo_ids,
                "todos": [
                    {
                        "todo_id": todo_id,
                        "step_id": str((_find_todo(plan, todo_id) or {}).get("step_id", todo_id)),
                        "title": str((_find_todo(plan, todo_id) or {}).get("title", todo_id)),
                        "kind": str((_find_todo(plan, todo_id) or {}).get("kind", "generic")),
                    }
                    for todo_id in todo_ids
                ],
                "phase_index": phase_index,
            },
        )

        async def _execute_todo(todo_id: str) -> DispatchTaskResult:
            todo = _find_todo(plan, todo_id) or {
                "todo_id": todo_id,
                "step_id": todo_id,
                "title": todo_id,
                "kind": "generic",
                "resolved_inputs": {},
                "execution_mode": "subagent",
            }
            task_prompt = _build_subtask_prompt(
                objective,
                todo,
                plan=plan,
                skill_context=_resolve_skill_context(
                    self._skill_context_provider,
                    str(todo.get("preferred_skill", "") or ""),
                ),
            )
            task_group = str(todo.get("kind", "default") or "default")
            before_change_snapshot = _git_change_snapshot()
            before_changed_paths = set(before_change_snapshot.keys())
            if _TRACE_APPROVAL:
                logger.info(
                    "todo_dispatch_trace_start",
                    session_key=self._session_key,
                    phase_index=phase_index,
                    batch_id=str(batch.get("batch_id", "")),
                    batch_parallel=bool(batch.get("parallel")),
                    todo_id=todo_id,
                    step_id=todo_step_identifier(todo),
                    todo_title=str(todo.get("title", todo_id)),
                    task_group=task_group,
                    before_changed_count=len(before_changed_paths),
                    before_changed_paths=sorted(before_changed_paths),
                )
            await _emit_diagnostic(
                "subagent.spawned",
                {
                    "session_key": self._session_key,
                    "todo_id": todo_id,
                    "step_id": todo_step_identifier(todo),
                    "todo_title": str(todo.get("title", todo_id)),
                    "batch_id": batch.get("batch_id"),
                    "phase_index": phase_index,
                    "task_group": task_group,
                },
            )

            group_semaphore = group_semaphores.get(task_group)
            if group_semaphore is None:
                group_semaphore = asyncio.Semaphore(self._max_concurrent_workers)

            attempt = 0
            while True:
                attempt += 1
                async with semaphore, group_semaphore:
                    try:
                        result = await self._spawn_tool.ainvoke({"task": task_prompt})
                        status = "failed" if str(result).startswith("Error:") else "completed"
                        error = str(result) if status == "failed" else None
                    except Exception as exc:
                        result = f"Error: {exc}"
                        status = "failed"
                        error = str(exc)

                should_retry = (
                    self._retry_on_error
                    and status == "failed"
                    and attempt <= self._max_task_retries
                )
                if not should_retry:
                    break
                await _emit_diagnostic(
                    "subagent.retry_scheduled",
                    {
                        "session_key": self._session_key,
                        "todo_id": todo_id,
                        "step_id": todo_step_identifier(todo),
                        "todo_title": str(todo.get("title", todo_id)),
                        "batch_id": batch.get("batch_id"),
                        "phase_index": phase_index,
                        "attempt": attempt,
                        "task_group": task_group,
                    },
                )

            after_change_snapshot = _git_change_snapshot()
            after_changed_paths = set(after_change_snapshot.keys())
            new_changed_paths = sorted(after_changed_paths - before_changed_paths)
            touched_changed_paths = sorted(
                path
                for path in (before_changed_paths | after_changed_paths)
                if before_change_snapshot.get(path) != after_change_snapshot.get(path)
            )
            if _TRACE_APPROVAL:
                logger.info(
                    "todo_dispatch_trace_end",
                    session_key=self._session_key,
                    phase_index=phase_index,
                    batch_id=str(batch.get("batch_id", "")),
                    batch_parallel=bool(batch.get("parallel")),
                    todo_id=todo_id,
                    step_id=todo_step_identifier(todo),
                    todo_title=str(todo.get("title", todo_id)),
                    task_group=task_group,
                    status=status,
                    attempts=attempt,
                    new_changed_count=len(new_changed_paths),
                    new_changed_paths=new_changed_paths,
                    touched_changed_count=len(touched_changed_paths),
                    touched_changed_paths=touched_changed_paths,
                    after_changed_count=len(after_changed_paths),
                )

            await _emit_diagnostic(
                "subagent.completed",
                {
                    "session_key": self._session_key,
                    "todo_id": todo_id,
                    "step_id": todo_step_identifier(todo),
                    "todo_title": str(todo.get("title", todo_id)),
                    "batch_id": batch.get("batch_id"),
                    "phase_index": phase_index,
                    "status": status,
                    "attempts": attempt,
                    "task_group": task_group,
                    "result_preview": str(result)[:240],
                    "error": error,
                },
            )
            return {
                "todo_id": todo_id,
                "step_id": todo_step_identifier(todo),
                "title": str(todo.get("title", todo_id)),
                "batch_id": str(batch.get("batch_id", "")),
                "phase_index": phase_index,
                "status": status,
                "result": str(result),
                "error": error,
                "attempts": attempt,
                "task_group": task_group,
            }

        if batch.get("parallel"):
            batch_results = list(await asyncio.gather(*(_execute_todo(todo_id) for todo_id in todo_ids)))
        else:
            batch_results = []
            for todo_id in todo_ids:
                batch_results.append(await _execute_todo(todo_id))

        await _emit_diagnostic(
            "dispatch.batch_ended",
            {
                "session_key": self._session_key,
                "batch_id": batch.get("batch_id"),
                "parallel": bool(batch.get("parallel")),
                "phase_index": phase_index,
                "result_count": len(batch_results),
            },
        )
        return batch_results


def _find_todo(plan: dict[str, Any] | None, todo_id: str) -> dict[str, Any] | None:
    if plan is None:
        return None
    for todo in plan.get("todos", []):
        if isinstance(todo, dict) and todo_identifier(todo) == todo_id:
            return todo
    return None


def _build_subtask_prompt(
    objective: str,
    todo: dict[str, Any],
    *,
    plan: dict[str, Any] | None = None,
    skill_context: str = "",
) -> str:
    resolved_inputs = todo.get("resolved_inputs") or {}
    prompt_lines = [
        f"Objective: {objective}\n"
        f"Current task: {todo.get('title', todo_identifier(todo) or 'task')}\n"
        f"Step ID: {todo_step_identifier(todo)}\n"
        f"Task kind: {todo.get('kind', 'generic')}\n"
        f"Resolved inputs: {resolved_inputs}"
    ]
    plan_status_lines = _build_plan_status_lines(plan)
    if plan_status_lines:
        prompt_lines.append("")
        prompt_lines.append("Execution plan status:")
        prompt_lines.extend(plan_status_lines)
    execution_constraints = _build_execution_constraints(todo, plan)
    if execution_constraints:
        prompt_lines.append("")
        prompt_lines.append("Execution status constraints:")
        prompt_lines.extend(execution_constraints)
    prompt_lines.append("")
    prompt_lines.append("Return a concise result including findings, actions taken, and remaining risks.")
    prompt = "\n".join(prompt_lines)
    if skill_context:
        prompt += f"\n\nPreferred skill guidance:\n{skill_context}\n"
    return prompt


def _build_plan_status_lines(plan: dict[str, Any] | None) -> list[str]:
    if not isinstance(plan, dict):
        return []
    lines: list[str] = []
    for item in plan.get("todos", []):
        if not isinstance(item, dict):
            continue
        lines.append(
            f"- [{item.get('status', 'unknown')}] {todo_identifier(item) or 'task'}"
            f" ({todo_step_identifier(item) or 'step'}): {item.get('title', '')}"
        )
    return lines


def _build_execution_constraints(todo: dict[str, Any], plan: dict[str, Any] | None) -> list[str]:
    step_id = str(todo_step_identifier(todo) or "")
    if step_id != "report":
        return [
            "- Base your result on the execution plan status above.",
            "- Treat skipped, cancelled, blocked, or pending approval tasks as not executed.",
        ]

    remediation_todos = [
        item
        for item in (plan or {}).get("todos", [])
        if isinstance(item, dict)
        and (
            "remediat" in str(todo_step_identifier(item) or "").lower()
            or "remediat" in str(todo_identifier(item) or "").lower()
        )
    ]
    completed_remediation = any(str(item.get("status")) == "completed" for item in remediation_todos)
    skipped_like_statuses = {
        str(item.get("status", "unknown"))
        for item in remediation_todos
        if str(item.get("status", "unknown")) in {"cancelled", "skipped", "pending_approval", "blocked"}
    }
    constraints = [
        "- Base the report on the execution plan status above and the actual execution evidence only.",
        "- Do not describe planned actions as completed changes.",
        "- Treat skipped, cancelled, blocked, or pending approval remediation tasks as not executed.",
    ]
    if completed_remediation:
        constraints.append("- You may describe remediation as completed only for tasks explicitly marked [completed].")
    else:
        constraints.append(
            "- Do not claim completed remediation, auto-fix completion, or counts of completed fixes unless a remediation task is explicitly marked [completed]."
        )
    if skipped_like_statuses:
        constraints.append(
            f"- In this run, remediation status includes: {', '.join(sorted(skipped_like_statuses))}; report it as skipped or not executed."
        )
    return constraints


def _resolve_skill_context(provider: Any | None, skill_name: str) -> str:
    if provider is None or not skill_name:
        return ""
    try:
        content = provider(skill_name)
    except Exception:
        return ""
    return str(content or "").strip()


def _git_change_snapshot() -> dict[str, str]:
    """Return changed paths and content fingerprint from git status (best effort)."""
    if not _TRACE_APPROVAL:
        return {}
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except Exception as exc:
        logger.warning("todo_dispatch_trace_git_snapshot_failed", error=str(exc))
        return {}

    if result.returncode != 0:
        logger.warning(
            "todo_dispatch_trace_git_status_failed",
            return_code=result.returncode,
            stderr=(result.stderr or "").strip()[:200],
        )
        return {}

    changed_snapshot: dict[str, str] = {}
    for line in (result.stdout or "").splitlines():
        if len(line) < 4:
            continue
        raw_path = line[3:].strip()
        if not raw_path:
            continue
        if " -> " in raw_path:
            raw_path = raw_path.split(" -> ", maxsplit=1)[1].strip()
        if raw_path:
            changed_snapshot[raw_path] = _file_fingerprint(raw_path)
    return changed_snapshot


def _file_fingerprint(path: str) -> str:
    file_path = Path(path)
    if not file_path.exists():
        return "missing"
    if file_path.is_dir():
        return "directory"

    hasher = hashlib.sha1()
    total_bytes = 0
    try:
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8192), b""):
                total_bytes += len(chunk)
                hasher.update(chunk)
    except Exception as exc:
        logger.warning("todo_dispatch_trace_fingerprint_failed", path=path, error=str(exc))
        return "unreadable"

    return f"{total_bytes}:{hasher.hexdigest()}"


async def _emit_diagnostic(event_name: str, payload: dict[str, Any]) -> None:
    try:
        from smartclaw.observability import diagnostic_bus as _dbus

        await _dbus.emit(event_name, payload)
    except Exception:
        pass
