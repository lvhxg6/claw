"""Property-based tests for ToolDef and SkillDefinition validation.

Uses hypothesis with @settings(max_examples=100, deadline=None).
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from smartclaw.skills.models import (
    MAX_NAME_LENGTH,
    ParameterDef,
    SkillDefinition,
    ToolDef,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_native_type = st.sampled_from(["shell", "script", "exec"])

_valid_command = st.text(min_size=1, max_size=50, alphabet=st.characters(
    whitelist_categories=("L", "N", "P", "Z"),
)).filter(lambda s: s.strip())

_segment = st.from_regex(r"[a-zA-Z0-9]{1,10}", fullmatch=True)
_valid_name = st.builds(
    lambda segs: "-".join(segs),
    st.lists(_segment, min_size=1, max_size=3),
).filter(lambda n: 1 <= len(n) <= MAX_NAME_LENGTH)

_valid_description = st.text(
    min_size=1, max_size=200,
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
).filter(lambda s: s.strip())

_unrecognized_type = st.text(min_size=1, max_size=20).filter(
    lambda s: s not in {"shell", "script", "exec"}
)

_tool_name = st.from_regex(r"[a-z_]{1,20}", fullmatch=True)
_tool_desc = st.text(min_size=1, max_size=50).filter(lambda s: s.strip())


def _native_tool_def(cmd: str = "") -> st.SearchStrategy[ToolDef]:
    """Strategy for a native command ToolDef with given command (empty by default)."""
    return st.builds(
        ToolDef,
        name=_tool_name,
        description=_tool_desc,
        type=_native_type,
        command=st.just(cmd),
    )


def _native_tool_with_command() -> st.SearchStrategy[ToolDef]:
    """Strategy for a valid native command ToolDef (non-empty command)."""
    return st.builds(
        ToolDef,
        name=_tool_name,
        description=_tool_desc,
        type=_native_type,
        command=_valid_command,
    )


# ---------------------------------------------------------------------------
# Feature: smartclaw-native-command-skills, Property 1:
# ToolDef validation — native command type must have command
# ---------------------------------------------------------------------------


# Feature: smartclaw-native-command-skills, Property 1: ToolDef validation — native command type must have command
@given(tool=_native_tool_def(cmd=""))
@settings(max_examples=100, deadline=None)
def test_native_type_empty_command_returns_error(tool: ToolDef) -> None:
    """For any ToolDef with type in {shell, script, exec} and empty command,
    validate() returns a non-empty error list.

    **Validates: Requirements 1.11**
    """
    errors = tool.validate()
    assert len(errors) > 0
    assert any("command" in e for e in errors)


# ---------------------------------------------------------------------------
# Feature: smartclaw-native-command-skills, Property 2:
# ToolDef validation — Python type must have function
# ---------------------------------------------------------------------------


# Feature: smartclaw-native-command-skills, Property 2: ToolDef validation — Python type must have function
@given(
    name=_tool_name,
    description=_tool_desc,
)
@settings(max_examples=100, deadline=None)
def test_python_type_empty_function_returns_error(name: str, description: str) -> None:
    """For any ToolDef with type=None and empty function,
    validate() returns a non-empty error list.

    **Validates: Requirements 1.12**
    """
    tool = ToolDef(name=name, description=description, function="", type=None)
    errors = tool.validate()
    assert len(errors) > 0
    assert any("function" in e for e in errors)


# ---------------------------------------------------------------------------
# Feature: smartclaw-native-command-skills, Property 3:
# ToolDef validation — unrecognized type is rejected
# ---------------------------------------------------------------------------


# Feature: smartclaw-native-command-skills, Property 3: ToolDef validation — unrecognized type is rejected
@given(
    name=_tool_name,
    description=_tool_desc,
    bad_type=_unrecognized_type,
)
@settings(max_examples=100, deadline=None)
def test_unrecognized_type_returns_error(name: str, description: str, bad_type: str) -> None:
    """For any ToolDef with type not in {shell, script, exec, None},
    validate() returns a non-empty error list.

    **Validates: Requirements 1.13**
    """
    tool = ToolDef(name=name, description=description, type=bad_type)
    errors = tool.validate()
    assert len(errors) > 0
    assert any("unrecognized" in e for e in errors)


# ---------------------------------------------------------------------------
# Feature: smartclaw-native-command-skills, Property 12:
# SkillDefinition validation — no entry_point but has native command tools is valid
# ---------------------------------------------------------------------------


# Feature: smartclaw-native-command-skills, Property 12: SkillDefinition validation — no entry_point but has native command tools is valid
@given(
    name=_valid_name,
    description=_valid_description,
    tools=st.lists(_native_tool_with_command(), min_size=1, max_size=5),
)
@settings(max_examples=100, deadline=None)
def test_no_entry_point_with_native_tools_is_valid(
    name: str, description: str, tools: list[ToolDef],
) -> None:
    """For any SkillDefinition with no entry_point but at least one native
    command tool (type in {shell, script, exec}), validate() returns empty errors.

    **Validates: Requirements 9.1**
    """
    defn = SkillDefinition(
        name=name,
        description=description,
        entry_point="",
        tools=tools,
    )
    errors = defn.validate()
    assert errors == [], f"Unexpected errors: {errors}"


# ---------------------------------------------------------------------------
# Feature: smartclaw-native-command-skills, Property 13:
# SkillDefinition validation — no entry_point and no native command tools is invalid
# ---------------------------------------------------------------------------


# Feature: smartclaw-native-command-skills, Property 13: SkillDefinition validation — no entry_point and no native command tools is invalid
@given(
    name=_valid_name,
    description=_valid_description,
    python_tools=st.lists(
        st.builds(
            ToolDef,
            name=_tool_name,
            description=_tool_desc,
            function=st.from_regex(r"[a-z][a-z0-9_.]{0,20}:[a-z_]{1,15}", fullmatch=True),
            type=st.none(),
        ),
        max_size=3,
    ),
)
@settings(max_examples=100, deadline=None)
def test_no_entry_point_no_native_tools_is_invalid(
    name: str, description: str, python_tools: list[ToolDef],
) -> None:
    """For any SkillDefinition with no entry_point and no native command tools,
    validate() returns a non-empty error list.

    **Validates: Requirements 9.2**
    """
    defn = SkillDefinition(
        name=name,
        description=description,
        entry_point="",
        tools=python_tools,
    )
    errors = defn.validate()
    assert len(errors) > 0
    assert any("entry_point" in e or "native" in e for e in errors)
