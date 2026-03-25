"""Skill data models — SkillDefinition, ToolDef, SkillInfo.

Defines the core data structures for skill discovery and loading.
Adapted from PicoClaw's ``pkg/skills/loader.go`` SkillInfo / SkillMetadata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

NAME_PATTERN = re.compile(r"^[a-zA-Z0-9]+(-[a-zA-Z0-9]+)*$")
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024


@dataclass
class ToolDef:
    """Embedded tool definition within a skill."""

    name: str
    description: str
    function: str  # Python dotted path, e.g. "pkg.mod:func"


@dataclass
class SkillDefinition:
    """YAML skill definition.

    Fields mirror the ``skill.yaml`` schema:
    - name: kebab-case identifier (max 64 chars)
    - description: human-readable summary (max 1024 chars)
    - entry_point: Python module:function path
    - version, author: optional metadata
    - tools: embedded tool definitions
    - parameters: configurable parameters with defaults
    """

    name: str
    description: str
    entry_point: str
    version: str | None = None
    author: str | None = None
    tools: list[ToolDef] = field(default_factory=list)
    parameters: dict[str, object] = field(default_factory=dict)

    def validate(self) -> list[str]:
        """Return a list of validation errors. Empty list means valid."""
        errors: list[str] = []

        # name checks
        if not self.name:
            errors.append("name is required")
        else:
            if len(self.name) > MAX_NAME_LENGTH:
                errors.append(f"name exceeds {MAX_NAME_LENGTH} characters")
            if not NAME_PATTERN.match(self.name):
                errors.append("name must be alphanumeric with hyphens (kebab-case)")

        # description checks
        if not self.description:
            errors.append("description is required")
        elif len(self.description) > MAX_DESCRIPTION_LENGTH:
            errors.append(f"description exceeds {MAX_DESCRIPTION_LENGTH} characters")

        # entry_point checks
        if not self.entry_point:
            errors.append("entry_point is required")

        return errors


@dataclass
class SkillInfo:
    """Skill discovery information returned by SkillsLoader.list_skills."""

    name: str
    path: str
    source: str  # "workspace" | "global" | "builtin"
    description: str
