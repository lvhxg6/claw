"""LLM-backed planner that emits TodoPlan and falls back on invalid output."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from smartclaw.agent.graph import _llm_call_with_fallback
from smartclaw.agent.orchestration_models import StepDefinition, TodoItem, TodoPlan
from smartclaw.capabilities.registry import CapabilityPackRegistry
from smartclaw.providers.config import ModelConfig
from smartclaw.providers.fallback import FallbackChain
from smartclaw.steps.registry import StepRegistry

_VALID_PLAN_ROLES = {"core", "conditional", "terminal"}
_VALID_ACTIVATION_MODES = {"immediate", "after_artifact", "approval_gated"}
_VALID_DISPLAY_POLICIES = {"always_show", "show_when_ready"}
_INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "inspection": ("检查", "巡检", "审计", "基线", "弱口令", "scan", "audit", "inspect", "review"),
    "remediation": ("整改", "修复", "加固", "hardening", "remediate", "remediation", "fix", "patch"),
    "reporting": ("报告", "汇总", "总结", "输出", "report", "summary", "deliverable"),
    "analysis": ("需求", "分析", "requirement", "analysis"),
    "design": ("设计", "接口", "api", "contract", "schema"),
    "documentation": ("文档", "doc", "documentation"),
}
_EXECUTION_KEYWORDS = ("执行", "应用", "apply", "实施", "落地", "修改", "变更", "修复", "加固", "patch", "fix")


class LLMPlanner:
    """Generate a TodoPlan from objective, pack scope, and candidate steps."""

    def __init__(
        self,
        *,
        model_config: ModelConfig,
        step_registry: StepRegistry | None = None,
        capability_registry: CapabilityPackRegistry | None = None,
        capability_pack: str | None = None,
    ) -> None:
        self._model_config = model_config
        self._step_registry = step_registry
        self._capability_registry = capability_registry
        self._capability_pack = capability_pack

    async def create_plan(
        self,
        messages: list[BaseMessage],
        *,
        artifacts: list[dict[str, Any]] | None = None,
        step_run_records: list[dict[str, Any]] | None = None,
        current_plan: TodoPlan | None = None,
    ) -> TodoPlan | None:
        """Return a validated TodoPlan, or None when LLM planning is unavailable/invalid."""
        return await self._generate_plan(
            messages,
            artifacts=artifacts,
            step_run_records=step_run_records,
            current_plan=current_plan,
            remaining_only=False,
        )

    async def replan(
        self,
        messages: list[BaseMessage],
        *,
        current_plan: TodoPlan | None,
        artifacts: list[dict[str, Any]] | None = None,
        step_run_records: list[dict[str, Any]] | None = None,
    ) -> TodoPlan | None:
        """Return a replanned TodoPlan containing only remaining work."""
        if current_plan is None:
            return None
        return await self._generate_plan(
            messages,
            artifacts=artifacts,
            step_run_records=step_run_records,
            current_plan=current_plan,
            remaining_only=True,
        )

    async def _generate_plan(
        self,
        messages: list[BaseMessage],
        *,
        artifacts: list[dict[str, Any]] | None = None,
        step_run_records: list[dict[str, Any]] | None = None,
        current_plan: TodoPlan | None,
        remaining_only: bool,
    ) -> TodoPlan | None:
        """Return a validated TodoPlan, or None when LLM planning is unavailable/invalid."""
        objective = self._extract_objective(messages)
        if not objective or self._step_registry is None:
            return None

        available_artifact_types = {
            str(item.get("artifact_type"))
            for item in (artifacts or [])
            if isinstance(item, dict) and item.get("status") == "ready" and item.get("artifact_type")
        }
        terminal_step_ids = self._terminal_step_ids(current_plan)
        pack = None
        if self._capability_registry is not None and self._capability_pack:
            pack = self._capability_registry.get(self._capability_pack)
        candidate_steps = self._step_registry.get_candidate_steps(
            pack,
            available_artifact_types=available_artifact_types if current_plan is not None else None,
            terminal_step_ids=terminal_step_ids,
        )
        if not candidate_steps:
            return None

        planner_messages = self._build_planner_messages(
            objective=objective,
            candidate_steps=candidate_steps,
            artifacts=artifacts or [],
            step_run_records=step_run_records or [],
            current_plan=current_plan,
            remaining_only=remaining_only,
        )
        try:
            response = await _llm_call_with_fallback(
                planner_messages,
                tools=None,
                model_config=self._model_config,
                fallback_chain=FallbackChain(),
                stream_callback=None,
            )
        except Exception:
            return None

        content = response.content if isinstance(response.content, str) else str(response.content)
        allowed_dependency_ids = set()
        if current_plan is not None:
            allowed_dependency_ids = {
                str(todo.get("todo_id"))
                for todo in current_plan.get("todos", [])
                if isinstance(todo, dict) and todo.get("todo_id")
            }
        return self._parse_todo_plan(
            content,
            objective=objective,
            candidate_steps=candidate_steps,
            allowed_dependency_ids=allowed_dependency_ids,
            artifacts=artifacts or [],
            current_plan=current_plan,
        )

    def _build_planner_messages(
        self,
        *,
        objective: str,
        candidate_steps: list[StepDefinition],
        artifacts: list[dict[str, Any]],
        step_run_records: list[dict[str, Any]],
        current_plan: TodoPlan | None,
        remaining_only: bool,
    ) -> list[BaseMessage]:
        plan_scope = "remaining work only" if remaining_only else "the full initial plan"
        system = SystemMessage(
            content=(
                "You are SmartClaw's planner. Return JSON only.\n"
                "Plan using only the provided candidate steps.\n"
                f"Produce {plan_scope}.\n"
                "Output schema:\n"
                "{"
                '"plan_version":"v1",'
                '"objective":"...",'
                '"strategy":"llm_dynamic",'
                '"missing_inputs":["..."],'
                '"reasoning_summary":"...",'
                '"todos":[{"todo_id":"...","step_id":"...","title":"...","kind":"...","status":"ready",'
                '"parallelizable":true,"depends_on":[],"resolved_inputs":{},'
                '"consumes_artifacts":[],"execution_mode":"subagent","approval_required":false,'
                '"plan_role":"core","activation_mode":"immediate","display_policy":"always_show"}]'
                "}\n"
                "Rules:\n"
                "- Use only step_id values from the candidate steps list.\n"
                "- depends_on must reference previous todo_id values in the same response.\n"
                "- For replanning, depends_on may also reference completed todo_id values from current_plan.\n"
                "- status must be ready when no dependencies exist, otherwise pending.\n"
                "- Prefer the minimal step set that satisfies the user's explicit request.\n"
                "- Include a step only when it is explicitly requested by the objective or is a required dependency of a selected step.\n"
                "- Do not auto-complete a full workflow just because later steps look reasonable.\n"
                "- Include terminal output steps only when the user explicitly asks for a report, summary, output, or deliverable.\n"
                "- Include approval-gated execution steps only when the user explicitly asks to execute/apply/fix, not when they only ask for analysis or a plan.\n"
                "- When replanning, do not repeat completed or failed terminal todos.\n"
                "- Do not include markdown fences."
            )
        )
        step_lines = []
        for step in candidate_steps:
            step_lines.append(
                {
                    "id": step.get("id", ""),
                    "description": step.get("description", ""),
                    "required_inputs": step.get("required_inputs", []),
                    "consumes_artifact_types": step.get("consumes_artifact_types", []),
                    "outputs": step.get("outputs", []),
                    "can_parallel": bool(step.get("can_parallel", False)),
                    "risk_level": step.get("risk_level", "low"),
                    "side_effect_level": step.get("side_effect_level", "read_only"),
                    "kind": step.get("kind", "generic"),
                    "plan_role": step.get("plan_role", ""),
                    "activation_mode": step.get("activation_mode", ""),
                    "display_policy": step.get("display_policy", ""),
                    "intent_tags": step.get("intent_tags", []),
                    "default_depends_on": step.get("default_depends_on", []),
                }
            )
        user = HumanMessage(
            content=json.dumps(
                {
                    "objective": objective,
                    "capability_pack": self._capability_pack,
                    "current_plan": current_plan or {},
                    "remaining_only": remaining_only,
                    "candidate_steps": step_lines,
                    "ready_artifacts": artifacts,
                    "step_run_records": step_run_records,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return [system, user]

    def _parse_todo_plan(
        self,
        content: str,
        *,
        objective: str,
        candidate_steps: list[StepDefinition],
        allowed_dependency_ids: set[str] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
        current_plan: TodoPlan | None = None,
    ) -> TodoPlan | None:
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        todos = parsed.get("todos")
        if not isinstance(todos, list):
            return None

        step_map = {str(step.get("id")): step for step in candidate_steps if step.get("id")}
        normalized_todos: list[TodoItem] = []
        seen_todo_ids: set[str] = set()
        permitted_dependency_ids = set(allowed_dependency_ids or set())
        for index, raw_todo in enumerate(todos):
            normalized = self._normalize_todo(
                raw_todo,
                index=index,
                step_map=step_map,
                seen_todo_ids=seen_todo_ids,
                allowed_dependency_ids=permitted_dependency_ids,
                artifacts=artifacts or [],
                current_plan=current_plan,
            )
            if normalized is None:
                return None
            normalized_todos.append(normalized)
            seen_todo_ids.add(normalized["todo_id"])
            permitted_dependency_ids.add(normalized["todo_id"])

        normalized_todos = self._prune_to_minimal_satisfaction(
            normalized_todos,
            objective=objective,
            step_map=step_map,
            current_plan=current_plan,
            artifacts=artifacts or [],
        )

        return {
            "plan_version": "v1",
            "objective": str(parsed.get("objective", objective) or objective),
            "strategy": str(parsed.get("strategy", "llm_dynamic") or "llm_dynamic"),
            "missing_inputs": [str(item) for item in parsed.get("missing_inputs", []) if str(item)],
            "reasoning_summary": str(parsed.get("reasoning_summary", "") or ""),
            "todos": normalized_todos,
        }

    def _prune_to_minimal_satisfaction(
        self,
        todos: list[TodoItem],
        *,
        objective: str,
        step_map: dict[str, StepDefinition],
        current_plan: TodoPlan | None,
        artifacts: list[dict[str, Any]],
    ) -> list[TodoItem]:
        if not todos:
            return todos

        objective_intents = self._extract_objective_intents(objective)
        explicit_output = self._objective_requests_output(objective, objective_intents)
        explicit_execution = self._objective_requests_execution(objective)
        todo_by_id = {str(todo.get("todo_id")): todo for todo in todos if todo.get("todo_id")}
        reusable_completed_step_ids = self._reusable_completed_step_ids(current_plan, artifacts=artifacts, step_map=step_map)

        selected_ids: set[str] = set()
        for todo in todos:
            step_id = str(todo.get("step_id", ""))
            step = step_map.get(step_id) or {}
            step_intents = self._step_intent_tags(step)
            if objective_intents and not (step_intents & objective_intents):
                continue
            if str(todo.get("plan_role", "core")) == "terminal" and not explicit_output:
                continue
            if str(todo.get("activation_mode", "immediate")) == "approval_gated" and not explicit_execution:
                continue
            if step_id in reusable_completed_step_ids:
                continue
            selected_ids.add(str(todo.get("todo_id")))

        if not selected_ids:
            for todo in todos:
                if (
                    str(todo.get("plan_role", "core")) == "core"
                    and str(todo.get("activation_mode", "immediate")) == "immediate"
                ):
                    selected_ids.add(str(todo.get("todo_id")))
                    break

        queue = list(selected_ids)
        while queue:
            todo_id = queue.pop(0)
            todo = todo_by_id.get(todo_id)
            if todo is None:
                continue
            for dep_id in [str(item) for item in todo.get("depends_on", []) if str(item)]:
                if dep_id not in selected_ids and dep_id in todo_by_id:
                    selected_ids.add(dep_id)
                    queue.append(dep_id)

        pruned = [dict(todo) for todo in todos if str(todo.get("todo_id")) in selected_ids]
        ordered = self._topological_order(pruned)
        completed_ids = {
            str(todo.get("todo_id"))
            for todo in ordered
            if str(todo.get("status")) == "completed" and todo.get("todo_id")
        }
        normalized: list[TodoItem] = []
        for todo in ordered:
            updated = dict(todo)
            depends_on = [str(dep_id) for dep_id in updated.get("depends_on", []) if str(dep_id) in selected_ids]
            updated["depends_on"] = depends_on
            if str(updated.get("status")) not in {"completed", "failed", "cancelled", "in_progress", "pending_approval"}:
                updated["status"] = "ready" if all(dep_id in completed_ids for dep_id in depends_on) else "pending"
            normalized.append(updated)  # type: ignore[arg-type]
        return normalized

    def _reusable_completed_step_ids(
        self,
        current_plan: TodoPlan | None,
        *,
        artifacts: list[dict[str, Any]],
        step_map: dict[str, StepDefinition],
    ) -> set[str]:
        if current_plan is None:
            return set()
        ready_artifact_types = {
            str(item.get("artifact_type"))
            for item in artifacts
            if isinstance(item, dict) and item.get("status") == "ready" and item.get("artifact_type")
        }
        reusable: set[str] = set()
        for todo in current_plan.get("todos", []):
            if not isinstance(todo, dict) or str(todo.get("status")) != "completed":
                continue
            step_id = str(todo.get("step_id", "") or "")
            if not step_id or step_id not in step_map:
                continue
            outputs = {
                str(item)
                for item in step_map[step_id].get("outputs", [])
                if str(item)
            }
            if not outputs or outputs & ready_artifact_types:
                reusable.add(step_id)
        return reusable

    def _topological_order(self, todos: list[TodoItem]) -> list[TodoItem]:
        todo_map = {str(todo.get("todo_id")): todo for todo in todos if todo.get("todo_id")}
        ordered: list[TodoItem] = []
        pending = set(todo_map.keys())
        while pending:
            progressed = False
            for todo_id in sorted(pending):
                todo = todo_map[todo_id]
                deps = [str(dep_id) for dep_id in todo.get("depends_on", []) if str(dep_id) in todo_map]
                if all(dep_id in {str(item.get("todo_id")) for item in ordered} for dep_id in deps):
                    ordered.append(todo)
                    pending.remove(todo_id)
                    progressed = True
                    break
            if not progressed:
                ordered.extend(todo_map[todo_id] for todo_id in sorted(pending))
                break
        return ordered

    def _extract_objective_intents(self, text: str) -> set[str]:
        haystack = text.lower()
        intents: set[str] = set()
        for intent, keywords in _INTENT_KEYWORDS.items():
            if any(keyword in text or keyword in haystack for keyword in keywords):
                intents.add(intent)
        return intents

    def _objective_requests_output(self, text: str, objective_intents: set[str]) -> bool:
        if objective_intents & {"reporting", "documentation"}:
            return True
        lowered = text.lower()
        return any(keyword in text or keyword in lowered for keyword in _INTENT_KEYWORDS["reporting"])

    def _objective_requests_execution(self, text: str) -> bool:
        lowered = text.lower()
        return any(keyword in text or keyword in lowered for keyword in _EXECUTION_KEYWORDS)

    def _step_intent_tags(self, step: dict[str, Any]) -> set[str]:
        explicit = {str(item).strip() for item in step.get("intent_tags", []) if str(item).strip()}
        if explicit:
            return explicit
        tags: set[str] = set()
        haystack = " ".join(
            [
                str(step.get("id", "") or ""),
                str(step.get("kind", "") or ""),
                str(step.get("description", "") or ""),
                " ".join(str(item) for item in step.get("outputs", []) if str(item)),
                " ".join(str(item) for item in step.get("consumes_artifact_types", []) if str(item)),
            ]
        ).lower()
        for intent, keywords in _INTENT_KEYWORDS.items():
            if any(keyword.lower() in haystack for keyword in keywords):
                tags.add(intent)
        if not tags and step.get("kind"):
            tags.add(str(step.get("kind")))
        return tags

    def _normalize_todo(
        self,
        raw_todo: Any,
        *,
        index: int,
        step_map: dict[str, StepDefinition],
        seen_todo_ids: set[str],
        allowed_dependency_ids: set[str],
        artifacts: list[dict[str, Any]],
        current_plan: TodoPlan | None,
    ) -> TodoItem | None:
        if not isinstance(raw_todo, dict):
            return None
        todo_id = str(raw_todo.get("todo_id", "")).strip()
        step_id = str(raw_todo.get("step_id", "")).strip()
        if not todo_id or not step_id or step_id not in step_map or todo_id in seen_todo_ids:
            return None

        depends_on = [str(item) for item in raw_todo.get("depends_on", []) if str(item)]
        permitted = set(seen_todo_ids) | set(allowed_dependency_ids)
        if any(dep_id not in permitted for dep_id in depends_on):
            return None

        kind = str(raw_todo.get("kind", step_map[step_id].get("kind", "generic")) or "generic")
        status = str(raw_todo.get("status", "ready" if not depends_on else "pending") or "ready")
        if status not in {"pending", "ready", "in_progress", "completed", "blocked", "failed", "cancelled"}:
            return None
        if status == "ready" and depends_on:
            status = "pending"

        ready_artifact_ids = {
            str(item.get("artifact_id"))
            for item in artifacts
            if isinstance(item, dict) and item.get("status") == "ready" and item.get("artifact_id")
        }
        consumes_artifacts = [
            str(item)
            for item in raw_todo.get("consumes_artifacts", [])
            if str(item) and str(item) in ready_artifact_ids
        ]
        if not consumes_artifacts and self._step_registry is not None:
            consumes_artifacts = self._step_registry.artifact_ids_for_step(
                step_id,
                artifacts,
                plan_todos=list((current_plan or {}).get("todos", [])),
            )
        resolved_inputs = raw_todo.get("resolved_inputs", {})
        if not isinstance(resolved_inputs, dict):
            resolved_inputs = {}
        if consumes_artifacts and "artifact_ids" not in resolved_inputs:
            resolved_inputs = dict(resolved_inputs)
            resolved_inputs["artifact_ids"] = list(consumes_artifacts)
        approval_required = bool(raw_todo.get("approval_required", False))
        if self._step_registry is not None:
            approval_required = approval_required or self._step_registry.approval_required_for_step(step_id)
        preferred_skill = str(raw_todo.get("preferred_skill", step_map[step_id].get("preferred_skill", "")) or "")
        plan_role = str(raw_todo.get("plan_role", step_map[step_id].get("plan_role", "core")) or "core")
        activation_mode = str(
            raw_todo.get("activation_mode", step_map[step_id].get("activation_mode", "immediate")) or "immediate"
        )
        display_policy = str(
            raw_todo.get("display_policy", step_map[step_id].get("display_policy", "always_show")) or "always_show"
        )
        if plan_role not in _VALID_PLAN_ROLES:
            plan_role = str(step_map[step_id].get("plan_role", "core") or "core")
        if activation_mode not in _VALID_ACTIVATION_MODES:
            activation_mode = str(step_map[step_id].get("activation_mode", "immediate") or "immediate")
        if display_policy not in _VALID_DISPLAY_POLICIES:
            display_policy = str(step_map[step_id].get("display_policy", "always_show") or "always_show")

        return {
            "todo_id": todo_id,
            "step_id": step_id,
            "title": str(raw_todo.get("title", step_id) or step_id),
            "kind": kind,
            "status": status,  # type: ignore[typeddict-item]
            "parallelizable": bool(raw_todo.get("parallelizable", step_map[step_id].get("can_parallel", False))),
            "depends_on": depends_on,
            "original_depends_on": list(depends_on),
            "skipped_depends_on": [str(item) for item in raw_todo.get("skipped_depends_on", []) if str(item)],
            "resolved_inputs": resolved_inputs,
            "consumes_artifacts": consumes_artifacts,
            "execution_mode": str(raw_todo.get("execution_mode", "subagent") or "subagent"),  # type: ignore[typeddict-item]
            "approval_required": approval_required,
            "preferred_skill": preferred_skill,
            "plan_role": plan_role,  # type: ignore[typeddict-item]
            "activation_mode": activation_mode,  # type: ignore[typeddict-item]
            "display_policy": display_policy,  # type: ignore[typeddict-item]
        }

    def _extract_objective(self, messages: list[BaseMessage]) -> str:
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                return content.strip()
        return ""

    def _terminal_step_ids(self, current_plan: TodoPlan | None) -> set[str]:
        if current_plan is None:
            return set()
        return {
            str(todo.get("step_id"))
            for todo in current_plan.get("todos", [])
            if isinstance(todo, dict) and str(todo.get("status")) in {"completed", "failed", "cancelled"}
        }
