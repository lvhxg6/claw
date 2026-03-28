"""DispatchPolicy — basic batching rules for orchestrator mode."""

from __future__ import annotations

from typing import TypedDict

from smartclaw.agent.orchestration_models import TodoItem, todo_identifier


class DispatchBatch(TypedDict):
    """A group of todo ids scheduled together."""

    batch_id: str
    todo_ids: list[str]
    parallel: bool


class DispatchPolicy:
    """Build conservative execution batches from todo items."""

    def __init__(self, *, max_batch_size: int = 4) -> None:
        self._max_batch_size = max(1, max_batch_size)

    def build_batches(self, todos: list[TodoItem]) -> list[DispatchBatch]:
        """Build batches while respecting todo dependencies and parallel hints."""
        ready_todos = [todo for todo in todos if todo["status"] == "ready"]
        if not ready_todos:
            return []

        batches: list[DispatchBatch] = []
        current_parallel: list[str] = []

        def flush_parallel() -> None:
            if current_parallel:
                batches.append(
                    {
                        "batch_id": f"batch-{len(batches) + 1}",
                        "todo_ids": list(current_parallel),
                        "parallel": True,
                    }
                )
                current_parallel.clear()

        for todo in ready_todos:
            if todo["parallelizable"]:
                current_parallel.append(todo_identifier(todo))
                if len(current_parallel) >= self._max_batch_size:
                    flush_parallel()
                continue

            flush_parallel()
            batches.append(
                {
                    "batch_id": f"batch-{len(batches) + 1}",
                    "todo_ids": [todo_identifier(todo)],
                    "parallel": False,
                }
            )

        flush_parallel()
        return batches
