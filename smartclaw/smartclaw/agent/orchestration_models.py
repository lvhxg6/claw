"""Shared orchestration schemas for planner, dispatcher, and graph stages."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

TodoStatus = Literal[
    "pending",
    "pending_approval",
    "ready",
    "in_progress",
    "completed",
    "blocked",
    "failed",
    "cancelled",
]
ExecutionMode = Literal["subagent", "skill", "tool", "orchestrator"]
ArtifactStatus = Literal["ready", "invalid"]
PlanRole = Literal["core", "conditional", "terminal"]
ActivationMode = Literal["immediate", "after_artifact", "approval_gated"]
DisplayPolicy = Literal["always_show", "show_when_ready"]


class StepDefinition(TypedDict, total=False):
    """Minimal step definition schema for Phase 1 orchestration."""

    id: str
    domain: str
    description: str
    required_inputs: list[str]
    consumes_artifact_types: list[str]
    outputs: list[str]
    preferred_skill: str
    can_parallel: bool
    risk_level: str
    completion_signal: str
    side_effect_level: str
    kind: str
    plan_role: PlanRole
    activation_mode: ActivationMode
    display_policy: DisplayPolicy
    intent_tags: list[str]
    default_depends_on: list[str]


class TodoItem(TypedDict, total=False):
    """Executable todo instance produced by the planner."""

    todo_id: str
    step_id: str
    title: str
    kind: str
    status: TodoStatus
    parallelizable: bool
    depends_on: list[str]
    resolved_inputs: dict[str, Any]
    consumes_artifacts: list[str]
    execution_mode: ExecutionMode
    approval_required: bool
    preferred_skill: str
    plan_role: PlanRole
    activation_mode: ActivationMode
    display_policy: DisplayPolicy


class TodoPlan(TypedDict, total=False):
    """Planner output consumed by the orchestrator."""

    plan_version: str
    objective: str
    strategy: str
    missing_inputs: list[str]
    reasoning_summary: str
    todos: list[TodoItem]


class ArtifactValidation(TypedDict, total=False):
    """Validation result attached to an artifact envelope."""

    is_valid: bool
    errors: list[str]


class ArtifactEnvelope(TypedDict, total=False):
    """Lightweight artifact reference tracked in runtime state."""

    artifact_id: str
    artifact_type: str
    schema_version: str
    producer_step: str
    status: ArtifactStatus
    summary: str
    validation: ArtifactValidation
    payload_path: str


class StepRunRecord(TypedDict, total=False):
    """Normalized step execution record."""

    todo_id: str
    step_id: str
    title: str
    batch_id: str
    phase_index: int
    status: str
    result: str
    error: str | None
    attempts: int
    task_group: str
    artifact_ids: list[str]


def todo_identifier(todo: dict[str, Any]) -> str:
    """Return the stable todo identifier, tolerating legacy payloads."""
    value = todo.get("todo_id") or todo.get("id") or todo.get("step_id") or ""
    return str(value)


def todo_step_identifier(todo: dict[str, Any]) -> str:
    """Return the logical step identifier for a todo."""
    value = todo.get("step_id") or todo.get("id") or todo.get("todo_id") or ""
    return str(value)
