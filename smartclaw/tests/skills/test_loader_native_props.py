"""Property-based tests for SkillsLoader native command YAML parsing.

Uses hypothesis with @settings(max_examples=100, deadline=None).
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from smartclaw.skills.loader import SkillsLoader
from smartclaw.skills.models import (
    MAX_NAME_LENGTH,
    ParameterDef,
    SkillDefinition,
    ToolDef,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_segment = st.from_regex(r"[a-zA-Z0-9]{1,10}", fullmatch=True)
_valid_name = st.builds(
    lambda segs: "-".join(segs),
    st.lists(_segment, min_size=1, max_size=3),
).filter(lambda n: 1 <= len(n) <= MAX_NAME_LENGTH)

_valid_description = st.text(
    min_size=1, max_size=200,
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
).filter(lambda s: s.strip())

_valid_entry_point = st.builds(
    lambda mod, func: f"{mod}:{func}",
    st.from_regex(r"[a-z][a-z0-9_]{0,15}(\.[a-z][a-z0-9_]{0,15}){0,2}", fullmatch=True),
    st.from_regex(r"[a-z][a-z_]{0,15}", fullmatch=True),
)

_optional_str = st.one_of(st.none(), st.text(
    min_size=1, max_size=30,
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
).filter(lambda s: s.strip()))

_native_type = st.sampled_from(["shell", "script", "exec"])

_tool_name = st.from_regex(r"[a-z][a-z0-9_]{0,19}", fullmatch=True)
_tool_desc = st.text(
    min_size=1, max_size=50,
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
).filter(lambda s: s.strip())

_valid_command = st.text(
    min_size=1, max_size=50,
    alphabet=st.characters(whitelist_categories=("L", "N")),
).filter(lambda s: s.strip())

_param_type = st.sampled_from(["string", "integer", "boolean"])

_param_name = st.from_regex(r"[a-z][a-z0-9_]{0,14}", fullmatch=True)


@st.composite
def st_parameter_def(draw: st.DrawFn) -> ParameterDef:
    """Generate a random ParameterDef."""
    ptype = draw(_param_type)
    desc = draw(st.text(min_size=1, max_size=30, alphabet=st.characters(
        whitelist_categories=("L", "N", "Z"),
    )).filter(lambda s: s.strip()))
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
    return ParameterDef(type=ptype, description=desc, default=default)


@st.composite
def st_native_tool_def(draw: st.DrawFn) -> ToolDef:
    """Generate a valid native command ToolDef."""
    return ToolDef(
        name=draw(_tool_name),
        description=draw(_tool_desc),
        type=draw(_native_type),
        command=draw(_valid_command),
        args=draw(st.lists(st.text(min_size=1, max_size=10, alphabet=st.characters(
            whitelist_categories=("L", "N"),
        )).filter(lambda s: s.strip()), max_size=3)),
        working_dir=draw(st.one_of(st.none(), st.just("/tmp"))),
        timeout=draw(st.sampled_from([30, 60, 120])),
        max_output_chars=draw(st.sampled_from([5000, 10_000, 20_000])),
        deny_patterns=draw(st.lists(st.just(r"\brm\b"), max_size=2)),
        parameters=draw(st.dictionaries(
            keys=_param_name,
            values=st_parameter_def(),
            max_size=3,
        )),
    )


@st.composite
def st_python_tool_def(draw: st.DrawFn) -> ToolDef:
    """Generate a traditional Python ToolDef (type=None)."""
    return ToolDef(
        name=draw(_tool_name),
        description=draw(_tool_desc),
        function=draw(st.from_regex(r"[a-z][a-z0-9_.]{0,20}:[a-z_]{1,15}", fullmatch=True)),
    )


@st.composite
def st_skill_definition_with_native(draw: st.DrawFn) -> SkillDefinition:
    """Generate a SkillDefinition containing native command tools."""
    has_entry = draw(st.booleans())
    native_tools = draw(st.lists(st_native_tool_def(), min_size=1, max_size=3))
    python_tools = draw(st.lists(st_python_tool_def(), max_size=2)) if has_entry else []
    all_tools = native_tools + python_tools

    return SkillDefinition(
        name=draw(_valid_name),
        description=draw(_valid_description),
        entry_point=draw(_valid_entry_point) if has_entry else "",
        version=draw(_optional_str),
        author=draw(_optional_str),
        tools=all_tools,
        parameters=draw(st.dictionaries(
            keys=st.from_regex(r"[a-z_]{1,15}", fullmatch=True),
            values=st.one_of(
                st.integers(min_value=0, max_value=1000),
                st.text(min_size=1, max_size=20, alphabet=st.characters(
                    whitelist_categories=("L", "N", "P", "Z"),
                )).filter(lambda s: s.strip()),
                st.booleans(),
            ),
            max_size=3,
        )),
    )


# ---------------------------------------------------------------------------
# Feature: smartclaw-native-command-skills, Property 4:
# SkillDefinition YAML round-trip with native command tools
# ---------------------------------------------------------------------------


# Feature: smartclaw-native-command-skills, Property 4: SkillDefinition YAML round-trip with native command tools
@given(defn=st_skill_definition_with_native())
@settings(max_examples=100, deadline=None)
def test_skill_definition_yaml_round_trip_native(defn: SkillDefinition) -> None:
    """For any valid SkillDefinition containing native command tools,
    serialize then parse produces an equivalent SkillDefinition with
    all fields preserved.

    **Validates: Requirements 2.7**
    """
    yaml_str = SkillsLoader.serialize_skill_yaml(defn)
    restored = SkillsLoader.parse_skill_yaml(yaml_str)

    assert restored.name == defn.name
    assert restored.description == defn.description
    assert restored.entry_point == defn.entry_point
    assert restored.version == defn.version
    assert restored.author == defn.author

    # Compare tools
    assert len(restored.tools) == len(defn.tools)
    for orig_t, rest_t in zip(defn.tools, restored.tools):
        assert rest_t.name == orig_t.name
        assert rest_t.description == orig_t.description
        assert rest_t.function == orig_t.function
        assert rest_t.type == orig_t.type
        assert rest_t.command == orig_t.command
        assert rest_t.args == orig_t.args
        assert rest_t.working_dir == orig_t.working_dir
        assert rest_t.timeout == orig_t.timeout
        assert rest_t.max_output_chars == orig_t.max_output_chars
        assert rest_t.deny_patterns == orig_t.deny_patterns

        # Compare parameters
        assert len(rest_t.parameters) == len(orig_t.parameters)
        for pname in orig_t.parameters:
            assert pname in rest_t.parameters
            orig_p = orig_t.parameters[pname]
            rest_p = rest_t.parameters[pname]
            assert rest_p.type == orig_p.type
            assert rest_p.description == orig_p.description
            # YAML may change types slightly for defaults
            assert str(rest_p.default) == str(orig_p.default)

    # Compare skill-level parameters
    assert len(restored.parameters) == len(defn.parameters)
    for key in defn.parameters:
        assert key in restored.parameters
        assert str(restored.parameters[key]) == str(defn.parameters[key])


# ---------------------------------------------------------------------------
# Feature: smartclaw-native-command-skills, Property 14:
# Backward compat — no type field → ToolDef.type is None
# ---------------------------------------------------------------------------


# Feature: smartclaw-native-command-skills, Property 14: Backward compat — no type field → ToolDef.type is None
@given(
    name=_valid_name,
    description=_valid_description,
    entry_point=_valid_entry_point,
    tool_name=_tool_name,
    tool_desc=_tool_desc,
    function=st.from_regex(r"[a-z][a-z0-9_.]{0,20}:[a-z_]{1,15}", fullmatch=True),
)
@settings(max_examples=100, deadline=None)
def test_no_type_field_backward_compat(
    name: str,
    description: str,
    entry_point: str,
    tool_name: str,
    tool_desc: str,
    function: str,
) -> None:
    """For any skill.yaml tool definition without a type field,
    parse_skill_yaml() produces a ToolDef with type=None and
    function correctly populated.

    **Validates: Requirements 2.2, 10.2, 10.3**
    """
    import yaml

    data = {
        "name": name,
        "description": description,
        "entry_point": entry_point,
        "tools": [
            {
                "name": tool_name,
                "description": tool_desc,
                "function": function,
            }
        ],
    }
    yaml_str = yaml.dump(data, default_flow_style=False, allow_unicode=True)
    defn = SkillsLoader.parse_skill_yaml(yaml_str)

    assert len(defn.tools) == 1
    tool = defn.tools[0]
    assert tool.type is None
    assert tool.function == function
    assert tool.name == tool_name
    assert tool.description == tool_desc
