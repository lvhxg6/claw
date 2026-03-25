"""NativeCommandTool — execute native commands (shell/script/exec) as LangChain BaseTool.

Provides placeholder substitution, dynamic args_schema generation, and a factory
method to create tool instances from ToolDef definitions.

Subprocess execution follows the patterns established in ``smartclaw/tools/shell.py``.
"""

from __future__ import annotations

import asyncio
import pathlib
import re
from typing import Any

import structlog
from pydantic import BaseModel, Field, create_model

from smartclaw.skills.models import ParameterDef, ToolDef
from smartclaw.tools.base import SmartClawTool

logger = structlog.get_logger(component="skills.native_command")

# ---------------------------------------------------------------------------
# Type mapping for dynamic schema generation
# ---------------------------------------------------------------------------

_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "boolean": bool,
}

TRUNCATION_INDICATOR = "\n... [truncated — {omitted} characters omitted]"


# ---------------------------------------------------------------------------
# Placeholder substitution
# ---------------------------------------------------------------------------


def substitute_placeholders(
    template: str,
    params: dict[str, Any],
    param_defs: dict[str, ParameterDef],
) -> str:
    """Replace ``{param_name}`` placeholders in *template*.

    Resolution order for each placeholder:
    1. If the name exists in *params* → use ``str(params[name])``
    2. Elif the name exists in *param_defs* and has a non-None default → use default
    3. Else → raise ``ValueError("Missing required parameter: {name}")``
    """
    placeholder_names = re.findall(r"\{(\w+)\}", template)
    if not placeholder_names:
        return template

    def _replacer(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in params:
            return str(params[name])
        if name in param_defs and param_defs[name].default is not None:
            return str(param_defs[name].default)
        raise ValueError(f"Missing required parameter: {name}")

    return re.sub(r"\{(\w+)\}", _replacer, template)


def substitute_args(
    args: list[str],
    params: dict[str, Any],
    param_defs: dict[str, ParameterDef],
) -> list[str]:
    """Apply :func:`substitute_placeholders` to each element in *args*."""
    return [substitute_placeholders(a, params, param_defs) for a in args]


# ---------------------------------------------------------------------------
# Dynamic args_schema generation
# ---------------------------------------------------------------------------


def _build_args_schema(
    tool_name: str,
    param_defs: dict[str, ParameterDef],
) -> type[BaseModel]:
    """Dynamically create a Pydantic ``BaseModel`` from *param_defs*.

    Type mapping: ``"string"`` → ``str``, ``"integer"`` → ``int``,
    ``"boolean"`` → ``bool``, other → ``str`` (fallback).

    Parameters with ``default=None`` are required (no default in Pydantic).
    Parameters with a default value use ``Field(default=...)``.

    Model name: ``{ToolName}Input`` (camel-cased from kebab/snake name).
    """
    # Convert tool name to CamelCase for the model name
    model_name = "".join(part.capitalize() for part in re.split(r"[-_]", tool_name)) + "Input"

    fields: dict[str, Any] = {}
    for pname, pdef in param_defs.items():
        py_type = _TYPE_MAP.get(pdef.type, str)
        if pdef.default is None:
            # Required field
            fields[pname] = (py_type, Field(description=pdef.description or pname))
        else:
            # Optional field with default
            fields[pname] = (py_type, Field(default=pdef.default, description=pdef.description or pname))

    return create_model(model_name, **fields)  # type: ignore[call-overload]


# ---------------------------------------------------------------------------
# NativeCommandTool
# ---------------------------------------------------------------------------


class NativeCommandTool(SmartClawTool):
    """Execute native commands (shell/script/exec) as LangChain BaseTool."""

    name: str
    description: str
    args_schema: type[BaseModel]

    # Internal configuration (not exposed to LLM)
    tool_type: str = "shell"
    command: str = ""
    command_args: list[str] = Field(default_factory=list)
    working_dir: str | None = None
    timeout: int = 60
    max_output_chars: int = 10_000
    deny_patterns: list[str] = Field(default_factory=list)
    param_defs: dict[str, ParameterDef] = Field(default_factory=dict)

    def _run(self, **kwargs: Any) -> str:  # type: ignore[override]
        raise NotImplementedError("Use async")

    async def _arun(self, **kwargs: Any) -> str:  # type: ignore[override]
        """Execute the command with placeholder substitution."""

        async def _do() -> str:
            # 1. Placeholder substitution
            try:
                cmd = substitute_placeholders(self.command, kwargs, self.param_defs)
                args = substitute_args(self.command_args, kwargs, self.param_defs)
                wd_template = self.working_dir
                wd: str | None = None
                if wd_template is not None:
                    wd = substitute_placeholders(wd_template, kwargs, self.param_defs)
            except ValueError as e:
                return f"Error: {e}"

            # 2. Deny pattern check (on substituted command + args)
            full_command = cmd if not args else f"{cmd} {' '.join(args)}"
            for pattern in self.deny_patterns:
                if re.search(pattern, full_command):
                    return "Error: Command blocked by security policy"

            # 3. Working dir check
            cwd: str | None = None
            if wd is not None:
                wd_path = pathlib.Path(wd)
                if not wd_path.exists() or not wd_path.is_dir():
                    return f"Error: Working directory not found — {wd}"
                cwd = str(wd_path.resolve())

            # 4. Execute based on tool_type
            try:
                if self.tool_type == "shell":
                    proc = await asyncio.create_subprocess_shell(
                        cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=cwd,
                    )
                elif self.tool_type == "script":
                    # Script: command + args joined for shell execution
                    script_cmd = cmd if not args else f"{cmd} {' '.join(args)}"
                    proc = await asyncio.create_subprocess_shell(
                        script_cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=cwd,
                    )
                elif self.tool_type == "exec":
                    proc = await asyncio.create_subprocess_exec(
                        cmd,
                        *args,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                        cwd=cwd,
                    )
                else:
                    return f"Error: Unsupported tool type: {self.tool_type}"

                # 5. Timeout via asyncio.wait_for
                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        proc.communicate(),
                        timeout=self.timeout,
                    )
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
                    return f"Error: Command timed out after {self.timeout}s"

                stdout = stdout_bytes.decode(errors="replace") if stdout_bytes else ""
                stderr = stderr_bytes.decode(errors="replace") if stderr_bytes else ""

                # 6. Build output
                parts: list[str] = []
                if stdout:
                    parts.append(stdout)
                if stderr:
                    parts.append(f"STDERR:\n{stderr}")

                exit_code = proc.returncode
                if exit_code and exit_code != 0:
                    parts.append(f"Exit code: {exit_code}")

                output = "\n".join(parts)

                # 7. Truncation
                if len(output) > self.max_output_chars:
                    omitted = len(output) - self.max_output_chars
                    output = output[: self.max_output_chars] + f"\n... [truncated — {omitted} characters omitted]"

                return output if output else "(no output)"

            except Exception as e:
                return f"Error: {e}"

        return await self._safe_run(_do())

    @classmethod
    def from_tool_def(cls, tool_def: ToolDef) -> NativeCommandTool:
        """Factory: create a NativeCommandTool from a ToolDef.

        Validates that ``tool_def.type`` is one of ``shell``, ``script``, ``exec``.
        Raises ``ValueError`` for unsupported types.
        """
        if tool_def.type not in ("shell", "script", "exec"):
            raise ValueError(f"Unsupported tool type: {tool_def.type}")

        args_schema = _build_args_schema(tool_def.name, tool_def.parameters)

        return cls(
            name=tool_def.name,
            description=tool_def.description,
            args_schema=args_schema,
            tool_type=tool_def.type,
            command=tool_def.command,
            command_args=tool_def.args,
            working_dir=tool_def.working_dir,
            timeout=tool_def.timeout,
            max_output_chars=tool_def.max_output_chars,
            deny_patterns=tool_def.deny_patterns,
            param_defs=tool_def.parameters,
        )
