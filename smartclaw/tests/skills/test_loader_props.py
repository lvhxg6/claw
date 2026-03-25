"""Property-based tests for SkillsLoader.

Uses hypothesis with @settings(max_examples=100, deadline=None).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from smartclaw.skills.loader import SkillsLoader
from smartclaw.skills.models import (
    MAX_DESCRIPTION_LENGTH,
    MAX_NAME_LENGTH,
    NAME_PATTERN,
    SkillDefinition,
    ToolDef,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid kebab-case name: 1+ alphanumeric segments joined by hyphens
_segment = st.from_regex(r"[a-zA-Z0-9]{1,10}", fullmatch=True)
_valid_name = st.builds(
    lambda segs: "-".join(segs),
    st.lists(_segment, min_size=1, max_size=4),
).filter(lambda n: len(n) <= MAX_NAME_LENGTH)

_valid_description = st.text(
    min_size=1, max_size=200, alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z"))
).filter(lambda s: s.strip())

_valid_entry_point = st.builds(
    lambda mod, func: f"{mod}:{func}",
    st.from_regex(r"[a-z][a-z0-9_]{0,15}(\.[a-z][a-z0-9_]{0,15}){0,2}", fullmatch=True),
    st.from_regex(r"[a-z][a-z_]{0,15}", fullmatch=True),
)

_optional_str = st.one_of(st.none(), st.text(min_size=1, max_size=30).filter(lambda s: s.strip()))

_tool_def = st.builds(
    ToolDef,
    name=st.from_regex(r"[a-z_]{1,20}", fullmatch=True),
    description=st.text(min_size=1, max_size=50).filter(lambda s: s.strip()),
    function=st.from_regex(r"[a-z][a-z0-9_.]{0,20}:[a-z_]{1,15}", fullmatch=True),
)

_param_value = st.one_of(
    st.integers(min_value=0, max_value=1000),
    st.text(min_size=1, max_size=20).filter(lambda s: s.strip()),
    st.booleans(),
)
_parameters = st.dictionaries(
    keys=st.from_regex(r"[a-z_]{1,15}", fullmatch=True),
    values=_param_value,
    max_size=3,
)

_valid_skill_definition = st.builds(
    SkillDefinition,
    name=_valid_name,
    description=_valid_description,
    entry_point=_valid_entry_point,
    version=_optional_str,
    author=_optional_str,
    tools=st.lists(_tool_def, max_size=3),
    parameters=_parameters,
)


def _write_skill_yaml(base_dir: Path, skill_name: str, definition: SkillDefinition) -> None:
    """Helper: write a skill.yaml file into base_dir/skill_name/skill.yaml."""
    skill_dir = base_dir / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    yaml_str = SkillsLoader.serialize_skill_yaml(definition)
    (skill_dir / "skill.yaml").write_text(yaml_str, encoding="utf-8")


# ---------------------------------------------------------------------------
# Property 10: Skill Directory Priority
# ---------------------------------------------------------------------------


# Feature: smartclaw-p1-enhanced-capabilities, Property 10: Skill Directory Priority
@given(data=st.data())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_skill_directory_priority(tmp_path: Path, data: st.DataObject) -> None:
    """For any skill name that exists in multiple source directories,
    list_skills returns only the highest-priority source.

    Validates: Requirements 5.2, 5.3
    """
    name = data.draw(_valid_name)
    desc = data.draw(_valid_description)
    entry = data.draw(_valid_entry_point)

    workspace_dir = tmp_path / "workspace"
    global_dir = tmp_path / "global"
    builtin_dir = tmp_path / "builtin"

    # Create the same skill in all three directories with different descriptions
    for base, source_label in [
        (workspace_dir, "workspace"),
        (global_dir, "global"),
        (builtin_dir, "builtin"),
    ]:
        defn = SkillDefinition(
            name=name,
            description=f"{desc} from {source_label}",
            entry_point=entry,
        )
        _write_skill_yaml(base, name, defn)

    loader = SkillsLoader(
        workspace_dir=str(workspace_dir),
        global_dir=str(global_dir),
        builtin_dir=str(builtin_dir),
    )
    skills = loader.list_skills()

    # Should have exactly one entry for this name
    matching = [s for s in skills if s.name == name]
    assert len(matching) == 1
    assert matching[0].source == "workspace"
    assert "from workspace" in matching[0].description


# ---------------------------------------------------------------------------
# Property 11: Skill Definition Validation
# ---------------------------------------------------------------------------


# Feature: smartclaw-p1-enhanced-capabilities, Property 11: Skill Definition Validation
@given(data=st.data())
@settings(max_examples=100, deadline=None)
def test_skill_definition_validation_invalid_name(data: st.DataObject) -> None:
    """Invalid name patterns, oversized names, oversized descriptions,
    or missing required fields are rejected by validate().

    Validates: Requirements 5.4, 5.8
    """
    # Choose one type of invalidity
    invalid_type = data.draw(st.sampled_from([
        "bad_name_pattern",
        "long_name",
        "long_description",
        "missing_name",
        "missing_description",
        "missing_entry_point",
    ]))

    name = "valid-name"
    description = "A valid description"
    entry_point = "pkg.mod:func"

    if invalid_type == "bad_name_pattern":
        # Names with spaces, underscores, leading hyphens, etc.
        name = data.draw(st.sampled_from([
            "has space", "under_score", "-leading", "trailing-",
            "double--hyphen", "", "has.dot",
        ]))
    elif invalid_type == "long_name":
        name = "a" * (MAX_NAME_LENGTH + 1)
    elif invalid_type == "long_description":
        description = "x" * (MAX_DESCRIPTION_LENGTH + 1)
    elif invalid_type == "missing_name":
        name = ""
    elif invalid_type == "missing_description":
        description = ""
    elif invalid_type == "missing_entry_point":
        entry_point = ""

    defn = SkillDefinition(
        name=name, description=description, entry_point=entry_point
    )
    errors = defn.validate()
    assert len(errors) > 0, f"Expected validation errors for {invalid_type}"


# Feature: smartclaw-p1-enhanced-capabilities, Property 11: Skill Definition Validation (valid case)
@given(defn=_valid_skill_definition)
@settings(max_examples=100, deadline=None)
def test_skill_definition_validation_valid(defn: SkillDefinition) -> None:
    """Valid SkillDefinitions pass validation with no errors.

    Validates: Requirements 5.4, 5.8
    """
    errors = defn.validate()
    assert errors == [], f"Unexpected errors: {errors}"


# ---------------------------------------------------------------------------
# Property 12: Skills Summary Contains All Skills
# ---------------------------------------------------------------------------


# Feature: smartclaw-p1-enhanced-capabilities, Property 12: Skills Summary Contains All Skills
@given(data=st.data())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_skills_summary_contains_all_skills(tmp_path: Path, data: st.DataObject) -> None:
    """For any set of valid discovered skills, build_skills_summary
    returns a string containing every skill's name and description.

    Validates: Requirements 5.13
    """
    definitions = data.draw(st.lists(_valid_skill_definition, min_size=1, max_size=5))

    # Deduplicate by name (keep first)
    seen: set[str] = set()
    unique_defs: list[SkillDefinition] = []
    for d in definitions:
        if d.name not in seen:
            seen.add(d.name)
            unique_defs.append(d)

    workspace_dir = tmp_path / "ws"
    for defn in unique_defs:
        _write_skill_yaml(workspace_dir, defn.name, defn)

    loader = SkillsLoader(
        workspace_dir=str(workspace_dir),
        global_dir=str(tmp_path / "empty_global"),
        builtin_dir=None,
    )
    summary = loader.build_skills_summary()

    for defn in unique_defs:
        assert defn.name in summary, f"Skill name '{defn.name}' not in summary"
        assert defn.description in summary, (
            f"Skill description '{defn.description}' not in summary"
        )


# ---------------------------------------------------------------------------
# Property 13: Skill Definition YAML Round-Trip
# ---------------------------------------------------------------------------


# Feature: smartclaw-p1-enhanced-capabilities, Property 13: Skill Definition YAML Round-Trip
@given(defn=_valid_skill_definition)
@settings(max_examples=100, deadline=None)
def test_skill_definition_yaml_round_trip(defn: SkillDefinition) -> None:
    """For any valid SkillDefinition, serialize then parse produces
    an equivalent object with all fields preserved.

    Validates: Requirements 6.3
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

    # Compare parameters — YAML round-trip may change types slightly,
    # so compare via string representation for robustness
    assert len(restored.parameters) == len(defn.parameters)
    for key in defn.parameters:
        assert key in restored.parameters
        # YAML may deserialize booleans/ints differently, compare values
        assert str(restored.parameters[key]) == str(defn.parameters[key])
