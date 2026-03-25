"""Property-based tests for SKILL.md parsing and discovery.

Uses hypothesis with @settings(max_examples=100, deadline=None).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from smartclaw.skills.loader import SkillsLoader
from smartclaw.skills.markdown_skill import parse_skill_md, split_frontmatter
from smartclaw.skills.models import MAX_NAME_LENGTH, NAME_PATTERN

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_segment = st.from_regex(r"[a-zA-Z0-9]{1,10}", fullmatch=True)
_valid_name = st.builds(
    lambda segs: "-".join(segs),
    st.lists(_segment, min_size=1, max_size=3),
).filter(lambda n: 1 <= len(n) <= MAX_NAME_LENGTH and NAME_PATTERN.match(n))

_valid_description = st.text(
    min_size=1, max_size=200,
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
).filter(lambda s: s.strip())

_body_text = st.text(
    min_size=10, max_size=300,
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
).filter(lambda s: s.strip() and "---" not in s)

_valid_entry_point = st.builds(
    lambda mod, func: f"{mod}:{func}",
    st.from_regex(r"[a-z][a-z0-9_]{0,15}(\.[a-z][a-z0-9_]{0,15}){0,2}", fullmatch=True),
    st.from_regex(r"[a-z][a-z_]{0,15}", fullmatch=True),
)


# ---------------------------------------------------------------------------
# Feature: smartclaw-native-command-skills, Property 15:
# SKILL.md frontmatter parsing — name and description extraction
# ---------------------------------------------------------------------------


# Feature: smartclaw-native-command-skills, Property 15: SKILL.md frontmatter parsing — name and description extraction
@given(
    name=_valid_name,
    description=_valid_description,
    body=_body_text,
)
@settings(max_examples=100, deadline=None)
def test_frontmatter_extracts_name_and_description(
    name: str, description: str, body: str,
) -> None:
    """For any SKILL.md with valid YAML frontmatter, parse_skill_md()
    correctly extracts name and description, and body does not contain
    frontmatter.

    **Validates: Requirements 11.2, 11.4**
    """
    # Use yaml.dump to properly serialize frontmatter values
    fm_data = {"name": name, "description": description}
    fm_yaml = yaml.dump(fm_data, default_flow_style=False, allow_unicode=True).strip()
    content = f"---\n{fm_yaml}\n---\n{body}"
    parsed_name, parsed_desc, parsed_body = parse_skill_md(content, "fallback-dir")

    assert parsed_name == name
    assert parsed_desc == description
    assert "---" not in parsed_body
    assert body in parsed_body


# ---------------------------------------------------------------------------
# Feature: smartclaw-native-command-skills, Property 16:
# SKILL.md no frontmatter fallback
# ---------------------------------------------------------------------------


# Feature: smartclaw-native-command-skills, Property 16: SKILL.md no frontmatter fallback
@given(
    dir_name=_valid_name,
    first_para=st.text(
        min_size=5, max_size=100,
        alphabet=st.characters(whitelist_categories=("L", "N", "Z")),
    ).filter(lambda s: s.strip() and "\n" not in s and "---" not in s and "#" not in s),
)
@settings(max_examples=100, deadline=None)
def test_no_frontmatter_fallback(dir_name: str, first_para: str) -> None:
    """For any SKILL.md without frontmatter, parse_skill_md() uses
    dir_name as name and first paragraph as description.

    **Validates: Requirements 11.3**
    """
    content = f"{first_para}\n\nMore content here."
    parsed_name, parsed_desc, parsed_body = parse_skill_md(content, dir_name)

    assert parsed_name == dir_name
    assert parsed_desc == first_para.strip()
    assert parsed_body == content


# ---------------------------------------------------------------------------
# Feature: smartclaw-native-command-skills, Property 17:
# Skill directory discovery — skill.yaml or SKILL.md both valid
# ---------------------------------------------------------------------------


# Feature: smartclaw-native-command-skills, Property 17: Skill directory discovery — skill.yaml or SKILL.md both valid
@given(data=st.data())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_skill_yaml_or_skill_md_both_valid(tmp_path: Path, data: st.DataObject) -> None:
    """For any skill directory containing skill.yaml or SKILL.md (or both),
    list_skills() identifies it as a valid skill. Directories without
    either are ignored.

    **Validates: Requirements 12.1, 12.2**
    """
    name = data.draw(_valid_name)
    desc = data.draw(_valid_description)
    entry_point = data.draw(_valid_entry_point)
    has_yaml = data.draw(st.booleans())
    has_md = data.draw(st.booleans())

    # Ensure at least one file exists
    if not has_yaml and not has_md:
        has_md = True

    workspace_dir = tmp_path / "workspace"
    skill_dir = workspace_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)

    # Clean any leftover files from previous hypothesis examples
    for f in skill_dir.iterdir():
        f.unlink()

    if has_yaml:
        yaml_data = {
            "name": name,
            "description": desc,
            "entry_point": entry_point,
        }
        (skill_dir / "skill.yaml").write_text(
            yaml.dump(yaml_data, allow_unicode=True), encoding="utf-8"
        )

    if has_md:
        md_content = f'---\nname: "{name}"\ndescription: "{desc}"\n---\n# Skill\n\nSome content.'
        (skill_dir / "SKILL.md").write_text(md_content, encoding="utf-8")

    # Also create an empty directory (should be ignored)
    empty_dir = workspace_dir / "empty-dir"
    empty_dir.mkdir(parents=True, exist_ok=True)

    loader = SkillsLoader(
        workspace_dir=str(workspace_dir),
        global_dir=str(tmp_path / "empty_global"),
        builtin_dir=None,
    )
    skills = loader.list_skills()

    skill_names = [s.name for s in skills]
    assert name in skill_names, f"Skill '{name}' not found in {skill_names}"
    assert "empty-dir" not in skill_names
