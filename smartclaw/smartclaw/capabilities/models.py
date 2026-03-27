"""Capability pack data models."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

NAME_PATTERN = re.compile(r"^[a-zA-Z0-9]+(-[a-zA-Z0-9]+)*$")


@dataclass
class CapabilityPackDefinition:
    """Structured definition loaded from a capability pack manifest."""

    name: str
    description: str
    version: str | None = None
    scenario_types: list[str] = field(default_factory=list)
    preferred_mode: Literal["classic", "orchestrator"] | None = None
    task_profile: str | None = None
    prompt: str = ""
    result_schema: str = ""
    result_format: Literal["text", "json"] = "text"
    schema_enforced: bool = False
    max_schema_retries: int = 0
    approval_required: bool = False
    approval_message: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    denied_tools: list[str] = field(default_factory=list)
    tool_groups: dict[str, list[str]] = field(default_factory=dict)
    concurrency_limits: dict[str, int] = field(default_factory=dict)
    max_task_retries: int = 0
    retry_on_error: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    manifest_path: str | None = None

    def validate(self) -> list[str]:
        """Return validation errors. Empty list means valid."""
        errors: list[str] = []
        if not self.name:
            errors.append("name is required")
        elif not NAME_PATTERN.match(self.name):
            errors.append("name must be alphanumeric with hyphens (kebab-case)")
        if not self.description:
            errors.append("description is required")
        if self.preferred_mode not in {None, "classic", "orchestrator"}:
            errors.append("preferred_mode must be classic or orchestrator")
        if self.result_format not in {"text", "json"}:
            errors.append("result_format must be text or json")
        if self.max_schema_retries < 0:
            errors.append("max_schema_retries must be >= 0")
        if self.max_task_retries < 0:
            errors.append("max_task_retries must be >= 0")
        if self.allowed_tools and self.denied_tools:
            overlap = sorted(set(self.allowed_tools) & set(self.denied_tools))
            if overlap:
                errors.append(f"allowed_tools and denied_tools overlap: {', '.join(overlap)}")
        for group, limit in self.concurrency_limits.items():
            if limit < 1:
                errors.append(f"concurrency_limits[{group}] must be >= 1")
        return errors

    @property
    def has_tool_policy(self) -> bool:
        """Whether the pack carries any tool scoping policy."""
        return bool(self.allowed_tools or self.denied_tools)


@dataclass(frozen=True)
class CapabilityPackInfo:
    """Discovery metadata for a capability pack."""

    name: str
    path: str
    source: str
    description: str
    scenario_types: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CapabilityResolution:
    """Resolved capability pack for a request."""

    requested_name: str | None
    resolved_name: str | None
    reason: str
    pack: CapabilityPackDefinition | None = None
