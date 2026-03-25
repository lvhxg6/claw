"""Unit tests for PageParser.

Covers Requirements 3.1–3.8: empty page snapshot, specific page snapshot
examples, role classification verification, ref assignment, compact mode,
interactive-only mode, duplicate disambiguation.
"""

from __future__ import annotations

from smartclaw.browser.page_parser import (
    CONTENT_ROLES,
    INTERACTIVE_ROLES,
    STRUCTURAL_ROLES,
    PageParser,
)

# ---------------------------------------------------------------------------
# Empty page snapshot (Requirement 3.1)
# ---------------------------------------------------------------------------


def test_snapshot_none_returns_empty():
    """None raw tree returns empty snapshot."""
    parser = PageParser()
    result = parser.snapshot(None)

    assert result.snapshot == "(empty)"
    assert result.refs == {}


def test_snapshot_empty_children():
    """WebArea with no children returns empty snapshot."""
    parser = PageParser()
    result = parser.snapshot({"role": "WebArea", "name": "Empty", "children": []})

    assert result.snapshot == "(empty)"
    assert result.refs == {}


# ---------------------------------------------------------------------------
# Specific page snapshot (Requirements 3.2, 3.3, 3.7, 3.8)
# ---------------------------------------------------------------------------


def test_snapshot_basic_page():
    """Basic page with navigation, heading, and buttons."""
    tree = {
        "role": "WebArea",
        "name": "Test",
        "children": [
            {
                "role": "navigation",
                "name": "Main Menu",
                "children": [
                    {"role": "link", "name": "Home"},
                    {"role": "link", "name": "About"},
                ],
            },
            {"role": "heading", "name": "Welcome"},
            {"role": "textbox", "name": "Search"},
            {"role": "button", "name": "Submit"},
        ],
    }

    parser = PageParser()
    result = parser.snapshot(tree)

    # Check refs assigned: navigation + 2 links + heading + textbox + button
    assert len(result.refs) == 6

    # Check navigation (content role with name) gets a ref
    nav_ref = next(
        (k for k, v in result.refs.items() if v.role == "navigation"), None
    )
    assert nav_ref is not None

    # Check interactive elements have refs
    link_refs = [k for k, v in result.refs.items() if v.role == "link"]
    assert len(link_refs) == 2

    # Check snapshot text format
    assert "[ref=" in result.snapshot
    assert 'navigation "Main Menu"' in result.snapshot
    assert 'link "Home"' in result.snapshot
    assert 'heading "Welcome"' in result.snapshot


def test_snapshot_assigns_sequential_refs():
    """Refs are assigned sequentially as e1, e2, e3, ..."""
    tree = {
        "role": "WebArea",
        "name": "Test",
        "children": [
            {"role": "button", "name": "A"},
            {"role": "button", "name": "B"},
            {"role": "button", "name": "C"},
        ],
    }

    parser = PageParser()
    result = parser.snapshot(tree)

    assert "e1" in result.refs
    assert "e2" in result.refs
    assert "e3" in result.refs
    assert result.refs["e1"].name == "A"
    assert result.refs["e2"].name == "B"
    assert result.refs["e3"].name == "C"


# ---------------------------------------------------------------------------
# Duplicate role+name disambiguation (Requirement 3.4)
# ---------------------------------------------------------------------------


def test_snapshot_duplicate_role_name_gets_nth():
    """Duplicate role+name pairs get [nth=N] annotations."""
    tree = {
        "role": "WebArea",
        "name": "Test",
        "children": [
            {"role": "button", "name": "Search"},
            {"role": "button", "name": "Search"},
            {"role": "button", "name": "Search"},
        ],
    }

    parser = PageParser()
    result = parser.snapshot(tree)

    assert len(result.refs) == 3
    nths = sorted(v.nth for v in result.refs.values() if v.nth is not None)
    assert nths == [0, 1, 2]

    # Check text contains nth annotations
    assert "[nth=0]" in result.snapshot
    assert "[nth=1]" in result.snapshot
    assert "[nth=2]" in result.snapshot


def test_snapshot_unique_role_name_no_nth():
    """Unique role+name pairs do NOT get nth annotations."""
    tree = {
        "role": "WebArea",
        "name": "Test",
        "children": [
            {"role": "button", "name": "Submit"},
            {"role": "link", "name": "Home"},
        ],
    }

    parser = PageParser()
    result = parser.snapshot(tree)

    for rr in result.refs.values():
        assert rr.nth is None


# ---------------------------------------------------------------------------
# Compact mode (Requirement 3.5)
# ---------------------------------------------------------------------------


def test_compact_removes_unnamed_structural():
    """Compact mode removes unnamed structural elements without ref descendants."""
    tree = {
        "role": "WebArea",
        "name": "Test",
        "children": [
            {
                "role": "group",
                # No name — structural, unnamed
                "children": [
                    {"role": "generic"},  # structural, unnamed, no children
                ],
            },
            {"role": "button", "name": "OK"},
        ],
    }

    parser = PageParser()
    result = parser.snapshot(tree, compact=True)

    assert "group" not in result.snapshot
    assert "generic" not in result.snapshot
    assert "button" in result.snapshot


def test_compact_keeps_unnamed_structural_with_ref_descendants():
    """Compact mode keeps unnamed structural elements that have ref descendants."""
    tree = {
        "role": "WebArea",
        "name": "Test",
        "children": [
            {
                "role": "list",
                # No name — structural, unnamed, but has ref descendants
                "children": [
                    {"role": "listitem", "name": "Item 1"},
                ],
            },
        ],
    }

    parser = PageParser()
    result = parser.snapshot(tree, compact=True)

    assert "list" in result.snapshot
    assert "listitem" in result.snapshot


# ---------------------------------------------------------------------------
# Interactive-only mode (Requirement 3.6)
# ---------------------------------------------------------------------------


def test_interactive_only_filters_non_interactive():
    """Interactive-only mode includes only interactive elements."""
    tree = {
        "role": "WebArea",
        "name": "Test",
        "children": [
            {"role": "heading", "name": "Title"},
            {"role": "button", "name": "Click"},
            {"role": "navigation", "name": "Nav"},
            {"role": "textbox", "name": "Input"},
            {"role": "group", "children": [{"role": "link", "name": "Link"}]},
        ],
    }

    parser = PageParser()
    result = parser.snapshot(tree, interactive_only=True)

    assert "heading" not in result.snapshot
    assert "navigation" not in result.snapshot
    assert "group" not in result.snapshot
    assert "button" in result.snapshot
    assert "textbox" in result.snapshot
    assert "link" in result.snapshot


# ---------------------------------------------------------------------------
# Role classification verification
# ---------------------------------------------------------------------------


def test_role_sets_are_disjoint():
    """INTERACTIVE, CONTENT, and STRUCTURAL role sets are disjoint."""
    assert not (INTERACTIVE_ROLES & CONTENT_ROLES)
    assert not (INTERACTIVE_ROLES & STRUCTURAL_ROLES)
    assert not (CONTENT_ROLES & STRUCTURAL_ROLES)


def test_interactive_roles_get_refs_without_name():
    """Interactive roles get refs even without a name."""
    tree = {
        "role": "WebArea",
        "name": "Test",
        "children": [
            {"role": "button"},  # no name
            {"role": "textbox"},  # no name
        ],
    }

    parser = PageParser()
    result = parser.snapshot(tree)

    assert len(result.refs) == 2
    roles = {v.role for v in result.refs.values()}
    assert "button" in roles
    assert "textbox" in roles


def test_content_roles_need_name_for_ref():
    """Content roles only get refs when they have a name."""
    tree = {
        "role": "WebArea",
        "name": "Test",
        "children": [
            {"role": "heading", "name": "Title"},  # has name → ref
            {"role": "heading"},  # no name → no ref
        ],
    }

    parser = PageParser()
    result = parser.snapshot(tree)

    assert len(result.refs) == 1
    assert list(result.refs.values())[0].name == "Title"


def test_structural_roles_never_get_refs():
    """Structural roles never get refs."""
    tree = {
        "role": "WebArea",
        "name": "Test",
        "children": [
            {"role": "group", "name": "MyGroup"},
            {"role": "list", "name": "MyList"},
            {"role": "generic"},
        ],
    }

    parser = PageParser()
    result = parser.snapshot(tree)

    assert len(result.refs) == 0


# ---------------------------------------------------------------------------
# resolve_ref
# ---------------------------------------------------------------------------


def test_resolve_ref_plain():
    assert PageParser.resolve_ref("e1") == "e1"
    assert PageParser.resolve_ref("e42") == "e42"


def test_resolve_ref_at_prefix():
    assert PageParser.resolve_ref("@e1") == "e1"


def test_resolve_ref_ref_equals():
    assert PageParser.resolve_ref("ref=e1") == "e1"


def test_resolve_ref_with_brackets():
    assert PageParser.resolve_ref("[ref=e1]") == "e1"


def test_resolve_ref_invalid():
    assert PageParser.resolve_ref("invalid") is None
    assert PageParser.resolve_ref("") is None
    assert PageParser.resolve_ref("x1") is None


def test_resolve_ref_with_whitespace():
    assert PageParser.resolve_ref("  e5  ") == "e5"
