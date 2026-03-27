"""PlanManager — lightweight planning primitives for orchestrator mode."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage

TodoStatus = Literal["pending", "ready", "in_progress", "completed", "blocked", "failed", "cancelled"]


class TodoItem(TypedDict):
    """A minimal orchestrator todo item."""

    id: str
    title: str
    kind: str
    status: TodoStatus
    parallelizable: bool
    depends_on: list[str]


class ExecutionPlan(TypedDict):
    """Execution plan tracked by orchestrator mode."""

    objective: str
    strategy: str
    todos: list[TodoItem]


class PlanManager:
    """Create and update coarse-grained execution plans."""

    def create_initial_plan(self, messages: list[BaseMessage]) -> ExecutionPlan:
        """Build an initial plan from the latest user message."""
        objective = self._extract_objective(messages)
        todos = self._infer_todos(objective)
        todos = self._reconcile_dependencies(todos)
        return {
            "objective": objective,
            "strategy": "phase_oriented",
            "todos": todos,
        }

    def mark_plan_completed(self, plan: ExecutionPlan | None) -> ExecutionPlan | None:
        """Return *plan* with all todos marked completed."""
        if plan is None:
            return None
        completed_todos: list[TodoItem] = []
        for todo in plan["todos"]:
            updated = dict(todo)
            updated["status"] = "completed"
            completed_todos.append(updated)  # type: ignore[arg-type]
        return {
            "objective": plan["objective"],
            "strategy": plan["strategy"],
            "todos": completed_todos,
        }

    def apply_results(
        self,
        plan: ExecutionPlan | None,
        task_results: list[dict[str, Any]] | None,
    ) -> ExecutionPlan | None:
        """Update todo status based on task results."""
        if plan is None:
            return None
        results_by_id = {
            result["todo_id"]: result
            for result in (task_results or [])
            if isinstance(result, dict) and result.get("todo_id")
        }
        updated_todos: list[TodoItem] = []
        for todo in plan["todos"]:
            updated = dict(todo)
            result = results_by_id.get(todo["id"])
            if result is not None:
                updated["status"] = "completed" if result.get("status") == "completed" else "failed"
            updated_todos.append(updated)  # type: ignore[arg-type]
        updated_plan: ExecutionPlan = {
            "objective": plan["objective"],
            "strategy": plan["strategy"],
            "todos": updated_todos,
        }
        return self.refresh_ready_todos(updated_plan)

    def refresh_ready_todos(self, plan: ExecutionPlan | None) -> ExecutionPlan | None:
        """Promote pending todos whose dependencies are satisfied."""
        if plan is None:
            return None

        statuses = {todo["id"]: todo["status"] for todo in plan["todos"]}
        refreshed_todos: list[TodoItem] = []
        for todo in plan["todos"]:
            updated = dict(todo)
            if updated["status"] in {"completed", "failed", "cancelled", "in_progress"}:
                refreshed_todos.append(updated)  # type: ignore[arg-type]
                continue

            if not updated["depends_on"]:
                updated["status"] = "ready"
            else:
                dependency_states = [statuses.get(dep_id, "failed") for dep_id in updated["depends_on"]]
                if any(state in {"failed", "cancelled", "blocked"} for state in dependency_states):
                    updated["status"] = "blocked"
                elif all(state == "completed" for state in dependency_states):
                    updated["status"] = "ready"
                else:
                    updated["status"] = "pending"
            refreshed_todos.append(updated)  # type: ignore[arg-type]

        return {
            "objective": plan["objective"],
            "strategy": plan["strategy"],
            "todos": refreshed_todos,
        }

    def mark_todos_in_progress(
        self,
        plan: ExecutionPlan | None,
        todo_ids: list[str],
    ) -> ExecutionPlan | None:
        """Mark the selected ready todos as in progress."""
        if plan is None:
            return None
        selected = set(todo_ids)
        updated_todos: list[TodoItem] = []
        for todo in plan["todos"]:
            updated = dict(todo)
            if updated["id"] in selected and updated["status"] == "ready":
                updated["status"] = "in_progress"
            updated_todos.append(updated)  # type: ignore[arg-type]
        return {
            "objective": plan["objective"],
            "strategy": plan["strategy"],
            "todos": updated_todos,
        }

    def get_ready_todos(self, plan: ExecutionPlan | None) -> list[TodoItem]:
        """Return todos that are ready for dispatch."""
        if plan is None:
            return []
        return [todo for todo in plan["todos"] if todo["status"] == "ready"]

    def is_plan_completed(self, plan: ExecutionPlan | None) -> bool:
        """Return True when all todos are completed."""
        return bool(plan and plan["todos"] and all(todo["status"] == "completed" for todo in plan["todos"]))

    def has_remaining_work(self, plan: ExecutionPlan | None) -> bool:
        """Return True when at least one todo still needs processing."""
        if plan is None:
            return False
        return any(todo["status"] in {"pending", "ready", "in_progress", "blocked"} for todo in plan["todos"])

    def _extract_objective(self, messages: list[BaseMessage]) -> str:
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                return content.strip()
        return ""

    def _infer_todos(self, objective: str) -> list[TodoItem]:
        text = objective.strip()
        if not text:
            return []

        todos: list[TodoItem] = []

        if any(keyword in text for keyword in ("检查", "巡检", "基线", "弱口令", "firewall", "防火墙")):
            todos.append(
                {
                    "id": "inspect",
                    "title": "执行检查任务",
                    "kind": "inspection",
                    "status": "ready",
                    "parallelizable": True,
                    "depends_on": [],
                }
            )

        if any(keyword in text for keyword in ("根据结果", "加固", "整改", "修复", "hardening")):
            todos.append(
                {
                    "id": "remediate",
                    "title": "根据检查结果执行整改",
                    "kind": "remediation",
                    "status": "pending" if todos else "ready",
                    "parallelizable": False,
                    "depends_on": ["inspect"] if todos else [],
                }
            )

        if any(keyword in text for keyword in ("报告", "汇总", "总结", "输出")):
            deps = [todo["id"] for todo in todos] or ["execute"]
            todos.append(
                {
                    "id": "report",
                    "title": "汇总结果并生成输出",
                    "kind": "report",
                    "status": "pending" if todos else "ready",
                    "parallelizable": False,
                    "depends_on": deps,
                }
            )

        if not todos:
            todos.append(
                {
                    "id": "execute",
                    "title": "执行任务",
                    "kind": "generic",
                    "status": "ready",
                    "parallelizable": False,
                    "depends_on": [],
                }
            )

        return todos

    def _reconcile_dependencies(self, todos: list[TodoItem]) -> list[TodoItem]:
        """Normalize initial todo statuses against their dependencies."""
        plan: ExecutionPlan = {
            "objective": "",
            "strategy": "phase_oriented",
            "todos": todos,
        }
        refreshed = self.refresh_ready_todos(plan)
        return refreshed["todos"] if refreshed is not None else todos
