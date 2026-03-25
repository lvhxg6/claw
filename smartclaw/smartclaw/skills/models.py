"""Skill data models — SkillDefinition, ToolDef, SkillInfo, ParameterDef.

Defines the core data structures for skill discovery and loading.
Adapted from PicoClaw's ``pkg/skills/loader.go`` SkillInfo / SkillMetadata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

NAME_PATTERN = re.compile(r"^[a-zA-Z0-9]+(-[a-zA-Z0-9]+)*$")
MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024

_VALID_TOOL_TYPES = {"shell", "script", "exec", None}


@dataclass
class ParameterDef:
    """Tool parameter definition for native command tools."""

    type: str = "string"       # "string", "integer", "boolean"
    description: str = ""
    default: Any = None        # None means required parameter


@dataclass
class ToolDef:
    """Embedded tool definition within a skill."""

    name: str
    description: str
    function: str = ""  # Python dotted path, e.g. "pkg.mod:func"

    # --- Native command extension fields ---
    type: str | None = None                                     # "shell", "script", "exec", or None
    command: str = ""                                           # Command string or executable path
    args: list[str] = field(default_factory=list)               # CLI args for exec type
    working_dir: str | None = None                              # Working directory ({workspace} supported)
    timeout: int = 60                                           # Timeout in seconds
    max_output_chars: int = 10_000                              # Output truncation threshold
    deny_patterns: list[str] = field(default_factory=list)      # Security deny regex patterns
    parameters: dict[str, ParameterDef] = field(default_factory=dict)  # Parameter definitions

    def validate(self) -> list[str]:
        """Return validation errors. Empty list means valid."""
        errors: list[str] = []
        if self.type not in _VALID_TOOL_TYPES:
            errors.append(f"unrecognized tool type: {self.type!r}")
            return errors
        if self.type in ("shell", "script", "exec") and not self.command:
            errors.append(f"command is required for type={self.type!r}")
        if self.type is None and not self.function:
            errors.append("function is required for Python entry_point tools")
        return errors


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
    entry_point: str = ""
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

        # entry_point / native command tools check
        has_native_tools = any(
            t.type in ("shell", "script", "exec") for t in self.tools
        )
        if not self.entry_point and not has_native_tools:
            errors.append(
                "entry_point or at least one native command tool is required"
            )

        return errors



@dataclass
class SkillInfo:
    """Skill discovery information returned by SkillsLoader.list_skills."""

    name: str
    path: str
    source: str  # "workspace" | "global" | "builtin"
    description: str
