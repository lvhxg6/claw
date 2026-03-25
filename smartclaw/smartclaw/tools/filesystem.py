"""Filesystem tools — read_file, write_file, list_directory.

All tools extend ``SmartClawTool`` and enforce ``PathPolicy`` before I/O.
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


class ReadFileInput(BaseModel):
    path: str = Field(description="File path to read")
    max_bytes: int = Field(default=1_048_576, description="Max bytes to read")


class WriteFileInput(BaseModel):
    path: str = Field(description="File path to write")
    content: str = Field(description="Content to write")


class ListDirectoryInput(BaseModel):
    path: str = Field(description="Directory path to list")


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

TRUNCATION_SUFFIX = "\n\n... [truncated — file exceeds max_bytes limit]"


class ReadFileTool(SmartClawTool):
    """Read file content with optional size limit."""

    name: str = "read_file"
    description: str = "Read the content of a file at the given path."
    args_schema: type[BaseModel] = ReadFileInput

    path_policy: PathPolicy = Field(default_factory=PathPolicy)

    async def _arun(self, path: str, max_bytes: int = 1_048_576, **kwargs: Any) -> str:  # type: ignore[override]
        async def _do() -> str:
            try:
                self.path_policy.check(path)
            except PathDeniedError as e:
                return f"Error: {e}"

            p = pathlib.Path(path)
            if not p.exists():
                return f"Error: File not found — {path}"

            data = p.read_bytes()
            if len(data) > max_bytes:
                truncated = data[:max_bytes].decode(errors="replace")
                return truncated + TRUNCATION_SUFFIX
            return data.decode(errors="replace")

        return await self._safe_run(_do())


class WriteFileTool(SmartClawTool):
    """Write content to a file, creating parent directories if needed."""

    name: str = "write_file"
    description: str = "Write content to a file at the given path."
    args_schema: type[BaseModel] = WriteFileInput

    path_policy: PathPolicy = Field(default_factory=PathPolicy)

    async def _arun(self, path: str, content: str, **kwargs: Any) -> str:  # type: ignore[override]
        async def _do() -> str:
            try:
                self.path_policy.check(path)
            except PathDeniedError as e:
                return f"Error: {e}"

            p = pathlib.Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
            return f"Successfully wrote {len(content)} characters to {path}"

        return await self._safe_run(_do())


class ListDirectoryTool(SmartClawTool):
    """List directory entries with file type indicators."""

    name: str = "list_directory"
    description: str = "List the contents of a directory."
    args_schema: type[BaseModel] = ListDirectoryInput

    path_policy: PathPolicy = Field(default_factory=PathPolicy)

    async def _arun(self, path: str, **kwargs: Any) -> str:  # type: ignore[override]
        async def _do() -> str:
            try:
                self.path_policy.check(path)
            except PathDeniedError as e:
                return f"Error: {e}"

            p = pathlib.Path(path)
            if not p.exists():
                return f"Error: Directory not found — {path}"
            if not p.is_dir():
                return f"Error: Not a directory — {path}"

            entries: list[str] = []
            for entry in sorted(p.iterdir()):
                if entry.is_dir():
                    entries.append(f"[DIR]  {entry.name}")
                elif entry.is_symlink():
                    entries.append(f"[LINK] {entry.name}")
                else:
                    entries.append(f"[FILE] {entry.name}")
            return "\n".join(entries) if entries else "(empty directory)"

        return await self._safe_run(_do())
