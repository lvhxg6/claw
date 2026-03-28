"""ShellTool — execute shell commands via asyncio subprocess.

Supports timeout, output truncation, deny-pattern blocking, and
separate stdout/stderr capture.
"""

from __future__ import annotations

import asyncio
import pathlib
import re
from typing import Any

from pydantic import BaseModel, Field

import structlog

from smartclaw.tools.base import SmartClawTool

# ---------------------------------------------------------------------------
# Deny patterns
# ---------------------------------------------------------------------------

DEFAULT_DENY_PATTERNS: list[str] = [
    r"\brm\s+-[rf]{1,2}\b",
    r"\bsudo\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bpoweroff\b",
    r"\bdd\s+if=",
    r"\bmkfs\b",
    r"\bchmod\s+[0-7]{3,4}\b",
    r"\bchown\b",
    r"\bkill\b",
    r"\bpkill\b",
    r"\bkillall\b",
    # Security: Block command substitution and shell injection
    r"\$\(",  # $(command) substitution
    r"`[^`]*`",  # Backtick substitution
    r"\|\s*sh\b",  # Pipe to shell
    r"\|\s*bash\b",  # Pipe to bash
    r">\s*/etc/",  # Write to system config
    r">>\s*/etc/",  # Append to system config
]

MAX_OUTPUT_CHARS = 10_000

# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------


class ShellInput(BaseModel):
    command: str = Field(description="Shell command to execute")
    timeout_seconds: int = Field(default=60, description="Timeout in seconds")
    working_dir: str | None = Field(default=None, description="Working directory")


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


class ShellTool(SmartClawTool):
    """Execute shell commands with timeout, deny patterns, and output truncation."""

    name: str = "exec_command"
    description: str = "Execute a shell command and return the output."
    args_schema: type[BaseModel] = ShellInput

    deny_patterns: list[str] = Field(default_factory=lambda: list(DEFAULT_DENY_PATTERNS))

    async def _arun(  # type: ignore[override]
        self,
        command: str,
        timeout_seconds: int = 60,
        working_dir: str | None = None,
        **kwargs: Any,
    ) -> str:
        async def _do() -> str:
            # Check deny patterns
            for pattern in self.deny_patterns:
                if re.search(pattern, command):
                    # Log security event for audit
                    logger = structlog.get_logger(component="security.shell")
                    logger.warning("command_blocked_by_policy", command=command, pattern=pattern)
                    return "Error: Command blocked by security policy"

            # Validate working_dir
            cwd: str | None = None
            if working_dir is not None:
                wd = pathlib.Path(working_dir)
                if not wd.exists() or not wd.is_dir():
                    return f"Error: Working directory not found — {working_dir}"
                cwd = str(wd.resolve())

            try:
                proc = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=cwd,
                )

                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        proc.communicate(),
                        timeout=timeout_seconds,
                    )
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
                    # Gather partial output
                    partial = ""
                    if proc.stdout:
                        try:
                            partial_bytes = await asyncio.wait_for(proc.stdout.read(), timeout=1)
                            partial = partial_bytes.decode(errors="replace")
                        except Exception:
                            pass
                    return (
                        f"Error: Command timed out after {timeout_seconds}s\n"
                        f"{partial}"
                    ).rstrip()

                stdout = stdout_bytes.decode(errors="replace") if stdout_bytes else ""
                stderr = stderr_bytes.decode(errors="replace") if stderr_bytes else ""

                # Build output
                parts: list[str] = []
                if stdout:
                    parts.append(stdout)
                if stderr:
                    parts.append(f"STDERR:\n{stderr}")

                exit_code = proc.returncode
                if exit_code and exit_code != 0:
                    parts.append(f"Exit code: {exit_code}")

                output = "\n".join(parts)

                # Truncate if needed
                if len(output) > MAX_OUTPUT_CHARS:
                    omitted = len(output) - MAX_OUTPUT_CHARS
                    output = output[:MAX_OUTPUT_CHARS] + f"\n... [truncated — {omitted} characters omitted]"

                return output if output else "(no output)"

            except Exception as e:
                return f"Error: {e}"

        return await self._safe_run(_do())
