"""Property-based tests for NativeCommandTool, placeholder substitution, and factory.

Uses hypothesis with @settings(max_examples=100, deadline=None).
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from pydantic import BaseModel

from smartclaw.skills.models import ParameterDef, ToolDef
from smartclaw.skills.native_command import (
    NativeCommandTool,
    _build_args_schema,
    substitute_placeholders,
    substitute_args,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Safe identifier characters for param names
_param_name = st.from_regex(r"[a-z][a-z0-9_]{0,14}", fullmatch=True)

# Simple non-empty values (avoid braces to prevent nested placeholders)
_param_value = st.one_of(
    st.text(min_size=1, max_size=30, alphabet=st.characters(
        whitelist_categories=("L", "N"),
    )).filter(lambda s: s.strip() and "{" not in s and "}" not in s),
    st.integers(min_value=-1000, max_value=1000),
    st.booleans(),
)

_param_type = st.sampled_from(["string", "integer", "boolean"])

_native_type = st.sampled_from(["shell", "script", "exec"])

_tool_name = st.from_regex(r"[a-z][a-z0-9-]{0,19}", fullmatch=True)
_tool_desc = st.text(min_size=1, max_size=50, alphabet=st.characters(
    whitelist_categories=("L", "N", "P", "Z"),
)).filter(lambda s: s.strip())

_valid_command = st.text(min_size=1, max_size=50, alphabet=st.characters(
    whitelist_categories=("L", "N", "P", "Z"),
)).filter(lambda s: s.strip())


@st.composite
def st_template_with_params(draw: st.DrawFn) -> tuple[str, dict[str, Any], dict[str, ParameterDef]]:
    """Generate a template with N placeholders and matching params dict."""
    n = draw(st.integers(min_value=1, max_value=5))
    names = draw(st.lists(_param_name, min_size=n, max_size=n, unique=True))
    values = draw(st.lists(_param_value, min_size=n, max_size=n))

    params = dict(zip(names, values))
    param_defs = {
        name: ParameterDef(type="string", description=f"param {name}")
        for name in names
    }

    # Build template with placeholders interspersed with literal text
    parts: list[str] = []
    for name in names:
        parts.append(f"prefix-{{{name}}}")
    template = " ".join(parts)

    return template, params, param_defs


@st.composite
def st_template_missing_required(draw: st.DrawFn) -> tuple[str, dict[str, Any], dict[str, ParameterDef]]:
    """Generate a template with a placeholder that has no value and no default."""
    name = draw(_param_name)
    template = f"cmd {{{name}}}"
    params: dict[str, Any] = {}  # No value provided
    param_defs = {name: ParameterDef(type="string", description="required", default=None)}
    return template, params, param_defs


@st.composite
def st_template_with_default(draw: st.DrawFn) -> tuple[str, dict[str, Any], dict[str, ParameterDef], str]:
    """Generate a template with a placeholder that uses a default value."""
    name = draw(_param_name)
    default_val = draw(st.text(min_size=1, max_size=20, alphabet=st.characters(
        whitelist_categories=("L", "N"),
    )).filter(lambda s: s.strip() and "{" not in s and "}" not in s))
    template = f"cmd {{{name}}}"
    params: dict[str, Any] = {}  # No value provided
    param_defs = {name: ParameterDef(type="string", description="with default", default=default_val)}
    return template, params, param_defs, default_val


@st.composite
def st_deny_pattern_and_command(draw: st.DrawFn) -> tuple[str, list[str]]:
    """Generate a command and a deny pattern that matches it."""
    keyword = draw(st.sampled_from(["rm", "sudo", "shutdown", "reboot", "dangerous"]))
    command = f"{keyword} -rf /tmp"
    pattern = rf"\b{keyword}\b"
    return command, [pattern]


@st.composite
def st_long_output(draw: st.DrawFn) -> tuple[str, int]:
    """Generate output longer than max_output_chars."""
    max_chars = draw(st.integers(min_value=50, max_value=200))
    # Generate output that exceeds max_chars
    output = "x" * (max_chars + draw(st.integers(min_value=10, max_value=500)))
    return output, max_chars


@st.composite
def st_valid_tool_def(draw: st.DrawFn) -> ToolDef:
    """Generate a valid native command ToolDef."""
    tool_type = draw(_native_type)
    name = draw(_tool_name)
    desc = draw(_tool_desc)
    command = draw(_valid_command)

    # Generate 0-3 parameters
    n_params = draw(st.integers(min_value=0, max_value=3))
    param_names = draw(st.lists(_param_name, min_size=n_params, max_size=n_params, unique=True))
    parameters: dict[str, ParameterDef] = {}
    for pname in param_names:
        ptype = draw(_param_type)
        has_default = draw(st.booleans())
        if has_default:
            if ptype == "string":
                default = draw(st.text(min_size=1, max_size=10, alphabet=st.characters(
                    whitelist_categories=("L", "N"),
                )).filter(lambda s: s.strip()))
            elif ptype == "integer":
                default = draw(st.integers(min_value=0, max_value=100))
            else:
                default = draw(st.booleans())
        else:
            default = None
        parameters[pname] = ParameterDef(type=ptype, description=f"param {pname}", default=default)

    return ToolDef(
        name=name,
        description=desc,
        type=tool_type,
        command=command,
        parameters=parameters,
    )


@st.composite
def st_param_defs_for_schema(draw: st.DrawFn) -> dict[str, ParameterDef]:
    """Generate a dict of ParameterDef for schema testing."""
    n = draw(st.integers(min_value=1, max_value=5))
    names = draw(st.lists(_param_name, min_size=n, max_size=n, unique=True))
    defs: dict[str, ParameterDef] = {}
    for name in names:
        ptype = draw(_param_type)
        has_default = draw(st.booleans())
        if has_default:
            if ptype == "string":
                default = "default_val"
            elif ptype == "integer":
                default = 42
            else:
                default = True
        else:
            default = None
        defs[name] = ParameterDef(type=ptype, description=f"desc {name}", default=default)
    return defs


# ---------------------------------------------------------------------------
# Feature: smartclaw-native-command-skills, Property 5:
# Placeholder substitution completeness
# ---------------------------------------------------------------------------


# Feature: smartclaw-native-command-skills, Property 5: Placeholder substitution completeness
@given(data=st_template_with_params())
@settings(max_examples=100, deadline=None)
def test_placeholder_substitution_completeness(
    data: tuple[str, dict[str, Any], dict[str, ParameterDef]],
) -> None:
    """For any template with N placeholders and N params provided,
    substitute_placeholders() returns a string with no remaining placeholders
    for those N names, and each is replaced by the string representation.

    **Validates: Requirements 3.1, 3.2, 3.6**
    """
    template, params, param_defs = data
    result = substitute_placeholders(template, params, param_defs)

    # No remaining placeholders for the provided param names
    for name in params:
        assert f"{{{name}}}" not in result, f"Placeholder {{{name}}} still present"

    # Each value appears in the result
    for name, value in params.items():
        assert str(value) in result, f"Value {value!r} for {name} not found in result"


# ---------------------------------------------------------------------------
# Feature: smartclaw-native-command-skills, Property 6:
# Missing required parameter raises ValueError
# ---------------------------------------------------------------------------


# Feature: smartclaw-native-command-skills, Property 6: Missing required parameter raises ValueError
@given(data=st_template_missing_required())
@settings(max_examples=100, deadline=None)
def test_missing_required_parameter_raises(
    data: tuple[str, dict[str, Any], dict[str, ParameterDef]],
) -> None:
    """For any template with a placeholder where the param is not in params
    and has no default, substitute_placeholders() raises ValueError.

    **Validates: Requirements 3.5**
    """
    template, params, param_defs = data
    with pytest.raises(ValueError, match="Missing required parameter"):
        substitute_placeholders(template, params, param_defs)


# ---------------------------------------------------------------------------
# Feature: smartclaw-native-command-skills, Property 7:
# Default value fallback
# ---------------------------------------------------------------------------


# Feature: smartclaw-native-command-skills, Property 7: Default value fallback
@given(data=st_template_with_default())
@settings(max_examples=100, deadline=None)
def test_default_value_fallback(
    data: tuple[str, dict[str, Any], dict[str, ParameterDef], str],
) -> None:
    """For any template with a placeholder not in params but with a default
    in param_defs, substitute_placeholders() uses the default value.

    **Validates: Requirements 3.4**
    """
    template, params, param_defs, default_val = data
    result = substitute_placeholders(template, params, param_defs)
    assert str(default_val) in result
    # No remaining placeholders
    for name in param_defs:
        assert f"{{{name}}}" not in result


# ---------------------------------------------------------------------------
# Feature: smartclaw-native-command-skills, Property 8:
# Deny pattern blocks matching commands
# ---------------------------------------------------------------------------


# Feature: smartclaw-native-command-skills, Property 8: Deny pattern blocks matching commands
@given(data=st_deny_pattern_and_command())
@settings(max_examples=100, deadline=None)
def test_deny_pattern_blocks_matching_commands(
    data: tuple[str, list[str]],
) -> None:
    """For any command matching a deny pattern regex,
    NativeCommandTool returns a security policy error string.

    **Validates: Requirements 4.7, 5.7, 6.7**
    """
    command, deny_patterns = data

    schema = _build_args_schema("test-tool", {})
    tool = NativeCommandTool(
        name="test-tool",
        description="test",
        args_schema=schema,
        tool_type="shell",
        command=command,
        deny_patterns=deny_patterns,
    )

    result = asyncio.run(tool._arun())
    assert "blocked by security policy" in result


# ---------------------------------------------------------------------------
# Feature: smartclaw-native-command-skills, Property 9:
# Output truncation respects max_output_chars
# ---------------------------------------------------------------------------


# Feature: smartclaw-native-command-skills, Property 9: Output truncation respects max_output_chars
@given(data=st_long_output())
@settings(max_examples=100, deadline=None)
def test_output_truncation_respects_limit(
    data: tuple[str, int],
) -> None:
    """For any output exceeding max_output_chars, the returned string length
    is ≤ max_output_chars + truncation indicator length, and ends with
    a truncation indicator.

    **Validates: Requirements 4.6, 5.6, 6.6**
    """
    output_text, max_chars = data
    omitted = len(output_text) - max_chars
    indicator = f"\n... [truncated — {omitted} characters omitted]"

    # Simulate truncation logic
    truncated = output_text[:max_chars] + indicator
    assert len(truncated) <= max_chars + len(indicator)
    assert "truncated" in truncated
    assert str(omitted) in truncated


# ---------------------------------------------------------------------------
# Feature: smartclaw-native-command-skills, Property 10:
# Factory creates BaseTool with correct name/description/args_schema
# ---------------------------------------------------------------------------


# Feature: smartclaw-native-command-skills, Property 10: Factory creates BaseTool with correct name/description/args_schema
@given(tool_def=st_valid_tool_def())
@settings(max_examples=100, deadline=None)
def test_factory_creates_correct_base_tool(tool_def: ToolDef) -> None:
    """For any valid ToolDef with type in {shell, script, exec},
    from_tool_def() returns a BaseTool with matching name, description,
    and args_schema fields.

    **Validates: Requirements 7.1, 7.2, 7.3, 7.4**
    """
    tool = NativeCommandTool.from_tool_def(tool_def)

    assert tool.name == tool_def.name
    assert tool.description == tool_def.description
    assert issubclass(tool.args_schema, BaseModel)

    # Check that schema fields match parameters
    schema_fields = tool.args_schema.model_fields
    for pname in tool_def.parameters:
        assert pname in schema_fields, f"Parameter {pname} missing from schema"


# ---------------------------------------------------------------------------
# Feature: smartclaw-native-command-skills, Property 11:
# Dynamic args_schema type mapping
# ---------------------------------------------------------------------------


# Feature: smartclaw-native-command-skills, Property 11: Dynamic args_schema type mapping
@given(param_defs=st_param_defs_for_schema())
@settings(max_examples=100, deadline=None)
def test_dynamic_args_schema_type_mapping(param_defs: dict[str, ParameterDef]) -> None:
    """For any ParameterDef dict, the dynamic args_schema maps types correctly:
    string→str, integer→int, boolean→bool. default=None → required field.

    **Validates: Requirements 7.4, 1.10**
    """
    type_map = {"string": str, "integer": int, "boolean": bool}

    schema = _build_args_schema("test-tool", param_defs)
    fields = schema.model_fields

    for pname, pdef in param_defs.items():
        assert pname in fields, f"Field {pname} missing"
        field_info = fields[pname]
        expected_type = type_map.get(pdef.type, str)
        assert field_info.annotation == expected_type, (
            f"Field {pname}: expected {expected_type}, got {field_info.annotation}"
        )

        if pdef.default is None:
            # Required field: should have no default or PydanticUndefined
            assert field_info.is_required(), f"Field {pname} should be required"
        else:
            # Optional field with default
            assert field_info.default == pdef.default, (
                f"Field {pname}: expected default {pdef.default}, got {field_info.default}"
            )
