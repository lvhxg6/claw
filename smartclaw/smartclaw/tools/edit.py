"""EditFileTool and AppendFileTool — file editing and appending.

Provides:
- ``replace_single_occurrence`` — pure function for single-match text replacement
- ``EditFileTool`` — edit files via old_text → new_text replacement
- ``AppendFileTool`` — append content to end of file
"""

from __future__ import annotations

import pathlib
from typing import Any

from pydantic import BaseModel, Field

from smartclaw.security.path_policy import PathDeniedError, PathPolicy
from smartclaw.tools.base import SmartClawTool


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------


class EditFileInput(BaseModel):
    path: str = Field(description="File path to edit")
    old_text: str = Field(description="Exact text to find and replace")
    new_text: str = Field(description="Replacement text")


class AppendFileInput(BaseModel):
    path: str = Field(description="File path to append to")
    content: str = Field(description="Content to append")


# ---------------------------------------------------------------------------
# Core pure function
# ---------------------------------------------------------------------------


def replace_single_occurrence(content: str, old_text: str, new_text: str) -> str:
    """Replace exactly one occurrence of *old_text* with *new_text*.

    Returns the new content string on success.

    Raises:
        ValueError: If *old_text* is not found or appears more than once.
    """
    count = content.count(old_text)
    if count == 0:
        msg = "old_text not found in file. Make sure it matches exactly"
        raise ValueError(msg)
    if count > 1:
        msg = f"old_text appears {count} times. Please provide more context to make it unique"
        raise ValueError(msg)
    return content.replace(old_text, new_text, 1)


# ---------------------------------------------------------------------------
# EditFileTool
# ---------------------------------------------------------------------------


class EditFileTool(SmartClawTool):
    """Edit a file by replacing a single exact match of old_text with new_text."""

    name: str = "edit_file"
    description: str = "Edit a file by replacing old_text with new_text. The old_text must match exactly once."
    args_schema: type[BaseModel] = EditFileInput

    path_policy: PathPolicy = Field(default_factory=PathPolicy)

    async def _arun(self, path: str, old_text: str, new_text: str, **kwargs: Any) -> str:  # type: ignore[override]
        async def _do() -> str:
            try:
                self.path_policy.check(path)
            except PathDeniedError as e:
                return f"Error: {e}"

            p = pathlib.Path(path)
            if not p.exists():
                return f"Error: File not found — {path}"

            content = p.read_text(encoding="utf-8")
            try:
                new_content = replace_single_occurrence(content, old_text, new_text)
            except ValueError as e:
                return f"Error: {e}"

            p.write_text(new_content, encoding="utf-8")
            return f"Successfully edited {path}"

        return await self._safe_run(_do())


# ---------------------------------------------------------------------------
# AppendFileTool
# ---------------------------------------------------------------------------


class AppendFileTool(SmartClawTool):
    """Append content to the end of a file. Creates the file if it does not exist."""

    name: str = "append_file"
    description: str = "Append content to the end of a file. Creates the file if it does not exist."
    args_schema: type[BaseModel] = AppendFileInput

    path_policy: PathPolicy = Field(default_factory=PathPolicy)

    async def _arun(self, path: str, content: str, **kwargs: Any) -> str:  # type: ignore[override]
        async def _do() -> str:
            try:
                self.path_policy.check(path)
            except PathDeniedError as e:
                return f"Error: {e}"

            p = pathlib.Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)

            with p.open("a", encoding="utf-8") as f:
                f.write(content)

            return f"Successfully appended {len(content)} characters to {path}"

        return await self._safe_run(_do())
