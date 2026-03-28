"""Governance helpers for capability packs."""

from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator


def build_runtime_policy(pack: Any | None) -> dict[str, Any] | None:
    """Build a runtime-safe governance policy from a capability pack."""
    if pack is None:
        return None
    return {
        "name": pack.name,
        "approval_required": bool(getattr(pack, "approval_required", False)),
        "approval_message": getattr(pack, "approval_message", "") or "",
        "allowed_steps": list(getattr(pack, "allowed_steps", []) or []),
        "preferred_steps": list(getattr(pack, "preferred_steps", []) or []),
        "schema_enforced": bool(getattr(pack, "schema_enforced", False)),
        "result_schema": getattr(pack, "result_schema", "") or "",
        "result_format": getattr(pack, "result_format", "text") or "text",
        "max_schema_retries": int(getattr(pack, "max_schema_retries", 0) or 0),
        "max_task_retries": int(getattr(pack, "max_task_retries", 0) or 0),
        "max_replanning_rounds": int(getattr(pack, "max_replanning_rounds", 0) or 0),
        "repeated_error_threshold": int(getattr(pack, "repeated_error_threshold", 0) or 0),
        "retry_on_error": bool(getattr(pack, "retry_on_error", True)),
        "concurrency_limits": dict(getattr(pack, "concurrency_limits", {}) or {}),
    }


def approval_required(policy: dict[str, Any] | None) -> bool:
    """Whether the active policy requires explicit approval before execution."""
    return bool(policy and policy.get("approval_required"))


def build_approval_request(policy: dict[str, Any] | None) -> dict[str, Any]:
    """Return a clarification payload for capability-pack approval."""
    message = "This capability pack requires explicit approval before execution."
    if policy and policy.get("approval_message"):
        message = str(policy["approval_message"])
    return {
        "kind": "approval",
        "question": message,
        "details": None,
        "options": ["approve", "cancel"],
        "option_descriptions": {
            "approve": "Continue the pending execution.",
            "cancel": "Stop the current execution.",
        },
    }


def validate_structured_output(
    output: str | None,
    policy: dict[str, Any] | None,
) -> tuple[dict[str, Any] | list[Any] | None, dict[str, Any]]:
    """Validate structured output against the capability-pack schema."""
    if not policy or not policy.get("schema_enforced") or not policy.get("result_schema"):
        return None, {"valid": True, "reason": "schema_not_enforced"}

    schema_text = str(policy.get("result_schema", "")).strip()
    if not schema_text:
        return None, {"valid": True, "reason": "schema_not_enforced"}

    try:
        schema = json.loads(schema_text)
    except json.JSONDecodeError as exc:
        return None, {
            "valid": False,
            "reason": "invalid_schema_json",
            "error": str(exc),
        }

    if not output:
        return None, {
            "valid": False,
            "reason": "empty_output",
            "error": "Final answer is empty",
        }

    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as exc:
        return None, {
            "valid": False,
            "reason": "invalid_output_json",
            "error": str(exc),
        }

    try:
        Draft202012Validator(schema).validate(parsed)
    except Exception as exc:
        return parsed, {
            "valid": False,
            "reason": "schema_validation_failed",
            "error": str(exc),
        }

    return parsed, {
        "valid": True,
        "reason": "validated",
    }


def build_schema_retry_prompt(
    objective: str,
    policy: dict[str, Any] | None,
    validation: dict[str, Any],
) -> str:
    """Build a retry prompt that requests schema-conformant JSON output."""
    schema = str((policy or {}).get("result_schema", "")).strip()
    error = str(validation.get("error", "schema validation failed"))
    return (
        f"Original objective: {objective}\n\n"
        "Your previous final answer did not satisfy the required structured output policy.\n"
        f"Validation error: {error}\n\n"
        "Return only valid JSON that conforms to this schema:\n"
        f"{schema}"
    )
