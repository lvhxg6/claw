"""dispatch_tasks — controlled worker fan-out for orchestrator mode."""

from __future__ import annotations

import asyncio
from typing import Any, TypedDict

from langchain_core.tools import BaseTool


class DispatchTaskResult(TypedDict, total=False):
    """Normalized result returned by orchestrator task dispatch."""

    todo_id: str
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
    ) -> None:
        self._spawn_tool = spawn_tool
        self._max_concurrent_workers = max(1, max_concurrent_workers)
        self._max_task_retries = max(0, max_task_retries)
        self._retry_on_error = retry_on_error
        self._concurrency_limits = {
            str(group): max(1, int(limit))
            for group, limit in (concurrency_limits or {}).items()
        }

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
                "batch_id": batch.get("batch_id"),
                "parallel": bool(batch.get("parallel")),
                "todo_ids": todo_ids,
                "todos": [
                    {
                        "id": todo_id,
                        "title": str((_find_todo(plan, todo_id) or {}).get("title", todo_id)),
                        "kind": str((_find_todo(plan, todo_id) or {}).get("kind", "generic")),
                    }
                    for todo_id in todo_ids
                ],
                "phase_index": phase_index,
            },
        )

        async def _execute_todo(todo_id: str) -> DispatchTaskResult:
            todo = _find_todo(plan, todo_id) or {"id": todo_id, "title": todo_id, "kind": "generic"}
            task_prompt = _build_subtask_prompt(objective, todo)
            task_group = str(todo.get("kind", "default") or "default")
            await _emit_diagnostic(
                "subagent.spawned",
                {
                    "todo_id": todo_id,
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
                        "todo_id": todo_id,
                        "todo_title": str(todo.get("title", todo_id)),
                        "batch_id": batch.get("batch_id"),
                        "phase_index": phase_index,
                        "attempt": attempt,
                        "task_group": task_group,
                    },
                )

            await _emit_diagnostic(
                "subagent.completed",
                {
                    "todo_id": todo_id,
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
        if isinstance(todo, dict) and todo.get("id") == todo_id:
            return todo
    return None


def _build_subtask_prompt(objective: str, todo: dict[str, Any]) -> str:
    return (
        f"Objective: {objective}\n"
        f"Current task: {todo.get('title', todo.get('id', 'task'))}\n"
        f"Task kind: {todo.get('kind', 'generic')}\n"
        "Return a concise result including findings, actions taken, and remaining risks."
    )


async def _emit_diagnostic(event_name: str, payload: dict[str, Any]) -> None:
    try:
        from smartclaw.observability import diagnostic_bus as _dbus

        await _dbus.emit(event_name, payload)
    except Exception:
        pass
