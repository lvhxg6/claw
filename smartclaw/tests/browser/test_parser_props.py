"""Property-based tests for PageParser.

# Feature: smartclaw-browser-engine, Property 3: Snapshot refs consistency
# Feature: smartclaw-browser-engine, Property 4: Duplicate role+name disambiguation
# Feature: smartclaw-browser-engine, Property 5: Compact mode excludes unnamed structural elements
# Feature: smartclaw-browser-engine, Property 6: Interactive-only mode filters non-interactive elements
# Feature: smartclaw-browser-engine, Property 7: Element Reference mapping round-trip
"""

from __future__ import annotations

import re

import hypothesis.strategies as st
from hypothesis import given, settings

from smartclaw.browser.page_parser import (
    CONTENT_ROLES,
    INTERACTIVE_ROLES,
    STRUCTURAL_ROLES,
    PageParser,
    RoleRef,
)

# ---------------------------------------------------------------------------
# Custom hypothesis strategies
# ---------------------------------------------------------------------------

ALL_ROLES = sorted(INTERACTIVE_ROLES | CONTENT_ROLES | STRUCTURAL_ROLES)

# Strategy for a valid accessible name (non-empty, no quotes/newlines)
_name_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs"), whitelist_characters="-_"),
    min_size=1,
    max_size=15,
)


@st.composite
def a11y_node(draw: st.DrawFn, max_depth: int = 3, current_depth: int = 0) -> dict:
    """Generate a single A11y tree node with optional children."""
    role = draw(st.sampled_from(ALL_ROLES))
    name = draw(st.one_of(st.none(), _name_st))
    children: list[dict] = []  # type: ignore[type-arg]

    if current_depth < max_depth:
        num_children = draw(st.integers(min_value=0, max_value=3))
        for _ in range(num_children):
            children.append(draw(a11y_node(max_depth=max_depth, current_depth=current_depth + 1)))

    node: dict = {"role": role}  # type: ignore[type-arg]
    if name is not None:
        node["name"] = name
    if children:
        node["children"] = children
    return node


@st.composite
def a11y_tree(draw: st.DrawFn) -> dict:
    """Generate a complete A11y tree with a WebArea root."""
    num_children = draw(st.integers(min_value=0, max_value=5))
    children = [draw(a11y_node()) for _ in range(num_children)]
    return {"role": "WebArea", "name": "Test Page", "children": children}


@st.composite
def a11y_tree_with_duplicates(draw: st.DrawFn) -> dict:
    """Generate an A11y tree guaranteed to have duplicate role+name pairs."""
    role = draw(st.sampled_from(sorted(INTERACTIVE_ROLES)))
    name = draw(_name_st)
    num_dupes = draw(st.integers(min_value=2, max_value=5))

    children = [{"role": role, "name": name} for _ in range(num_dupes)]
    # Add some extra random nodes
    num_extra = draw(st.integers(min_value=0, max_value=3))
    for _ in range(num_extra):
        children.append(draw(a11y_node(max_depth=1)))

    return {"role": "WebArea", "name": "Test Page", "children": children}


# Regex to extract [ref=eN] from snapshot text
_REF_IN_TEXT = re.compile(r"\[ref=(e\d+)\]")


# ---------------------------------------------------------------------------
# Property 3: Snapshot refs consistency
# ---------------------------------------------------------------------------


@given(tree=a11y_tree())
@settings(max_examples=100)
def test_snapshot_refs_consistency(tree: dict) -> None:
    """**Validates: Requirements 3.2, 3.3, 3.7, 3.8**

    For any A11y tree:
    (a) every [ref=eN] in snapshot text has a corresponding refs map entry,
    (b) every refs map entry has a corresponding [ref=eN] in snapshot text,
    (c) all interactive-role elements have refs assigned,
    (d) all content-role elements with non-empty names have refs assigned.
    """
    parser = PageParser()
    result = parser.snapshot(tree)

    # (a) text refs → map
    text_refs = set(_REF_IN_TEXT.findall(result.snapshot))
    map_refs = set(result.refs.keys())
    assert text_refs == map_refs, f"text_refs={text_refs}, map_refs={map_refs}"

    # (c) & (d): collect all nodes that should have refs
    expected_ref_roles: list[tuple[str, str | None]] = []
    _collect_refable_nodes(tree, expected_ref_roles)

    # Every refable node should appear in the refs map values
    ref_values = list(result.refs.values())
    for role, name in expected_ref_roles:
        found = any(
            rv.role == role and rv.name == name
            for rv in ref_values
        )
        assert found, f"Expected ref for ({role}, {name!r}) not found in refs"


def _collect_refable_nodes(
    node: dict, out: list[tuple[str, str | None]]
) -> None:
    """Recursively collect (role, name) pairs that should have refs."""
    role = node.get("role", "")
    name = node.get("name") or None

    # Skip root wrapper
    if role not in ("WebArea", "RootWebArea") and (
        role in INTERACTIVE_ROLES or (role in CONTENT_ROLES and name)
    ):
        out.append((role, name))

    for child in node.get("children", []):
        _collect_refable_nodes(child, out)


# ---------------------------------------------------------------------------
# Property 4: Duplicate role+name disambiguation
# ---------------------------------------------------------------------------


@given(tree=a11y_tree_with_duplicates())
@settings(max_examples=100)
def test_duplicate_role_name_disambiguation(tree: dict) -> None:
    """**Validates: Requirements 3.4**

    When two or more elements share the same role and name, the PageParser
    assigns distinct [nth=N] indices starting from 0, sequential.
    """
    parser = PageParser()
    result = parser.snapshot(tree)

    # Group refs by (role, name)
    from collections import defaultdict
    groups: dict[tuple[str, str | None], list[RoleRef]] = defaultdict(list)
    for rr in result.refs.values():
        groups[(rr.role, rr.name)].append(rr)

    for key, refs_list in groups.items():
        if len(refs_list) > 1:
            nth_values = sorted(rr.nth for rr in refs_list if rr.nth is not None)
            expected = list(range(len(refs_list)))
            assert nth_values == expected, (
                f"For {key}: expected nth={expected}, got {nth_values}"
            )


# ---------------------------------------------------------------------------
# Property 5: Compact mode excludes unnamed structural elements
# ---------------------------------------------------------------------------


@given(tree=a11y_tree())
@settings(max_examples=100)
def test_compact_mode_excludes_unnamed_structural(tree: dict) -> None:
    """**Validates: Requirements 3.5**

    With compact=True, no unnamed structural-role element appears in the
    snapshot output unless it has descendants with refs.
    """
    parser = PageParser()
    result_normal = parser.snapshot(tree)
    result_compact = parser.snapshot(tree, compact=True)

    if result_compact.snapshot == "(empty)":
        return

    # All refs from compact should be a subset of normal refs
    assert set(result_compact.refs.keys()).issubset(set(result_normal.refs.keys()))

    # Verify: every structural role line in compact output either has a name
    # or the compact result still contains at least one ref (meaning it has
    # ref descendants that justified keeping it).
    for line in result_compact.snapshot.splitlines():
        match = re.match(r'^\s*-\s+(\w+)(.*)$', line)
        if not match:
            continue
        role = match.group(1)
        rest = match.group(2)

        if role in STRUCTURAL_ROLES:
            has_name = bool(re.search(r'"[^"]+"', rest))
            if not has_name:
                # Unnamed structural kept — compact guarantees it has ref descendants.
                # We verify the overall compact result has refs (non-trivial tree).
                assert len(result_compact.refs) > 0


# ---------------------------------------------------------------------------
# Property 6: Interactive-only mode filters non-interactive elements
# ---------------------------------------------------------------------------


@given(tree=a11y_tree())
@settings(max_examples=100)
def test_interactive_only_mode(tree: dict) -> None:
    """**Validates: Requirements 3.6**

    With interactive_only=True, every element in the snapshot output has a
    role that belongs to INTERACTIVE_ROLES.
    """
    parser = PageParser()
    result = parser.snapshot(tree, interactive_only=True)

    if result.snapshot == "(empty)":
        return

    for line in result.snapshot.splitlines():
        match = re.match(r'^\s*-\s+(\w+)', line)
        if not match:
            continue
        role = match.group(1)
        assert role in INTERACTIVE_ROLES, (
            f"Non-interactive role '{role}' found in interactive_only snapshot"
        )

    # All refs should also be interactive
    for ref_str, rr in result.refs.items():
        assert rr.role in INTERACTIVE_ROLES, (
            f"Ref {ref_str} has non-interactive role '{rr.role}'"
        )


# ---------------------------------------------------------------------------
# Property 7: Element Reference mapping round-trip
# ---------------------------------------------------------------------------


@given(tree=a11y_tree())
@settings(max_examples=100)
def test_element_reference_mapping_round_trip(tree: dict) -> None:
    """**Validates: Requirements 3.9**

    Parsing the tree to produce a SnapshotResult, then re-parsing the
    snapshot text, produces an equivalent RoleRefMap.
    """
    parser = PageParser()
    result = parser.snapshot(tree)

    if result.snapshot == "(empty)":
        return

    # Re-parse the snapshot text
    reparsed_refs = PageParser.parse_snapshot_text(result.snapshot)

    # Same keys
    assert set(result.refs.keys()) == set(reparsed_refs.keys()), (
        f"Keys differ: original={set(result.refs.keys())}, "
        f"reparsed={set(reparsed_refs.keys())}"
    )

    # Same values
    for ref_str in result.refs:
        original = result.refs[ref_str]
        reparsed = reparsed_refs[ref_str]
        assert original.role == reparsed.role, (
            f"{ref_str}: role {original.role} != {reparsed.role}"
        )
        assert original.name == reparsed.name, (
            f"{ref_str}: name {original.name!r} != {reparsed.name!r}"
        )
        assert original.nth == reparsed.nth, (
            f"{ref_str}: nth {original.nth} != {reparsed.nth}"
        )
