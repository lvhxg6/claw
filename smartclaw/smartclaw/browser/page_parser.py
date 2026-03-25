"""Page Parser — Accessibility Tree extraction and Element Reference mapping.

Converts Playwright's ``page.accessibility.snapshot()`` output into
LLM-consumable structured text with ``eN`` element references.

Reference: OpenClaw ``src/browser/pw-role-snapshot.ts``.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Role classification constants (OpenClaw snapshot-roles.ts)
# ---------------------------------------------------------------------------

INTERACTIVE_ROLES: frozenset[str] = frozenset({
    "button", "checkbox", "combobox", "link", "listbox",
    "menuitem", "menuitemcheckbox", "menuitemradio", "option",
    "radio", "searchbox", "slider", "spinbutton", "switch",
    "tab", "textbox", "treeitem",
})

CONTENT_ROLES: frozenset[str] = frozenset({
    "article", "cell", "columnheader", "gridcell", "heading",
    "listitem", "main", "navigation", "region", "rowheader",
})

STRUCTURAL_ROLES: frozenset[str] = frozenset({
    "application", "directory", "document", "generic", "grid",
    "group", "ignored", "list", "menu", "menubar", "none",
    "presentation", "row", "rowgroup", "table", "tablist",
    "toolbar", "tree", "treegrid",
})

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoleRef:
    """Single Element Reference role information.

    Corresponds to OpenClaw's ``RoleRef`` type.
    """

    role: str
    name: str | None = None
    nth: int | None = None


# ref string → RoleRef
RoleRefMap = dict[str, RoleRef]


@dataclass
class SnapshotResult:
    """Page snapshot result."""

    snapshot: str  # Formatted A11y Tree text
    refs: RoleRefMap = field(default_factory=dict)  # element ref mapping


# ---------------------------------------------------------------------------
# Ref parsing regex
# ---------------------------------------------------------------------------

_REF_PATTERN = re.compile(r"^\[?(?:ref=|@)?e(\d+)\]?$")
_SNAPSHOT_REF_PATTERN = re.compile(r"\[ref=(e\d+)\]")
_SNAPSHOT_NTH_PATTERN = re.compile(r"\[nth=(\d+)\]")
_SNAPSHOT_LINE_PATTERN = re.compile(
    r'^(\s*)-\s+'           # indentation + bullet
    r'(\w+)'                # role
    r'(?:\s+"([^"]*)")?'    # optional quoted name
    r'(.*?)$'               # rest (ref, nth annotations)
)


# ---------------------------------------------------------------------------
# PageParser
# ---------------------------------------------------------------------------


class PageParser:
    """Accessibility Tree parser.

    Extracts a structured snapshot from Playwright's
    ``page.accessibility.snapshot()``, assigning ``eN`` references to
    interactive elements and named content elements.
    """

    def snapshot(
        self,
        raw_tree: dict[str, Any] | None,
        *,
        compact: bool = False,
        interactive_only: bool = False,
    ) -> SnapshotResult:
        """Extract an A11y Tree snapshot.

        Args:
            raw_tree: Raw accessibility tree dict from
                ``page.accessibility.snapshot()`` (or *None* for empty pages).
            compact: Remove unnamed structural elements and empty branches.
            interactive_only: Include only interactive elements.

        Returns:
            ``SnapshotResult`` with formatted text and ref mapping.
        """
        if raw_tree is None:
            return SnapshotResult(snapshot="(empty)", refs={})

        # Phase 1: flatten tree into a list of (depth, role, name, children_flag)
        flat_nodes: list[dict[str, Any]] = []
        self._flatten(raw_tree, 0, flat_nodes)

        if not flat_nodes:
            return SnapshotResult(snapshot="(empty)", refs={})

        # Phase 2: determine which nodes need refs
        ref_counter = 0
        refs: RoleRefMap = {}

        # Count (role, name) occurrences for nth disambiguation
        role_name_counts: Counter[tuple[str, str | None]] = Counter()
        for node in flat_nodes:
            role = node["role"]
            name = node.get("name")
            if self._needs_ref(role, name):
                role_name_counts[(role, name)] += 1

        # Track nth assignment per (role, name)
        role_name_nth_tracker: dict[tuple[str, str | None], int] = {}

        # Phase 3: assign refs and build annotated nodes
        annotated: list[dict[str, Any]] = []
        for node in flat_nodes:
            role = node["role"]
            name = node.get("name")
            depth = node["depth"]

            ref_str: str | None = None
            nth: int | None = None

            if self._needs_ref(role, name):
                ref_counter += 1
                ref_str = f"e{ref_counter}"

                key = (role, name)
                if role_name_counts[key] > 1:
                    nth = role_name_nth_tracker.get(key, 0)
                    role_name_nth_tracker[key] = nth + 1

                refs[ref_str] = RoleRef(role=role, name=name, nth=nth)

            annotated.append({
                "depth": depth,
                "role": role,
                "name": name,
                "ref": ref_str,
                "nth": nth,
                "has_children": node.get("has_children", False),
            })

        # Phase 4: apply filters
        if interactive_only:
            annotated = [n for n in annotated if n["role"] in INTERACTIVE_ROLES]
            # Rebuild refs to only include kept nodes
            kept_refs = {n["ref"] for n in annotated if n["ref"]}
            refs = {k: v for k, v in refs.items() if k in kept_refs}

        if compact:
            annotated = self._apply_compact(annotated, refs)

        # Phase 5: format output
        lines: list[str] = []
        for node in annotated:
            indent = "  " * node["depth"]
            parts = [f"{indent}- {node['role']}"]

            if node["name"] is not None:
                parts.append(f' "{node["name"]}"')

            if node["ref"]:
                parts.append(f" [ref={node['ref']}]")

            if node["nth"] is not None:
                parts.append(f" [nth={node['nth']}]")

            lines.append("".join(parts))

        snapshot_text = "\n".join(lines) if lines else "(empty)"
        return SnapshotResult(snapshot=snapshot_text, refs=refs)

    @staticmethod
    def resolve_ref(ref: str) -> str | None:
        """Parse a ref string (supports ``'e1'``, ``'@e1'``, ``'ref=e1'`` formats).

        Returns:
            The normalized ref string (e.g. ``'e1'``), or *None* if invalid.
        """
        match = _REF_PATTERN.match(ref.strip())
        if match:
            return f"e{match.group(1)}"
        return None

    @staticmethod
    def parse_snapshot_text(snapshot_text: str) -> RoleRefMap:
        """Re-parse a formatted snapshot text to extract the RoleRefMap.

        Used for round-trip verification (Property 7).
        """
        refs: RoleRefMap = {}
        for line in snapshot_text.splitlines():
            line_match = _SNAPSHOT_LINE_PATTERN.match(line)
            if not line_match:
                continue

            role = line_match.group(2)
            name = line_match.group(3)  # may be None
            rest = line_match.group(4)

            ref_match = _SNAPSHOT_REF_PATTERN.search(rest)
            if not ref_match:
                continue

            ref_str = ref_match.group(1)
            nth_match = _SNAPSHOT_NTH_PATTERN.search(rest)
            nth = int(nth_match.group(1)) if nth_match else None

            refs[ref_str] = RoleRef(role=role, name=name, nth=nth)

        return refs

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _flatten(
        self,
        node: dict[str, Any],
        depth: int,
        out: list[dict[str, Any]],
    ) -> None:
        """Recursively flatten an A11y tree node into a flat list."""
        role = node.get("role", "")
        name = node.get("name")
        children = node.get("children", [])

        # Skip the root "WebArea" / "RootWebArea" wrapper — just process children
        if role in ("WebArea", "RootWebArea") and depth == 0:
            for child in children:
                self._flatten(child, depth, out)
            return

        out.append({
            "role": role,
            "name": name if name else None,
            "depth": depth,
            "has_children": bool(children),
        })

        for child in children:
            self._flatten(child, depth + 1, out)

    @staticmethod
    def _needs_ref(role: str, name: str | None) -> bool:
        """Determine whether a node should receive an element reference."""
        if role in INTERACTIVE_ROLES:
            return True
        return bool(role in CONTENT_ROLES and name)

    def _apply_compact(
        self,
        nodes: list[dict[str, Any]],
        refs: RoleRefMap,
    ) -> list[dict[str, Any]]:
        """Remove unnamed structural elements that have no descendants with refs.

        A structural node without a name is kept only if at least one of its
        descendants (determined by depth) has a ref.
        """
        ref_set = set(refs.keys())
        result: list[dict[str, Any]] = []

        for i, node in enumerate(nodes):
            role = node["role"]
            name = node["name"]

            # Keep non-structural nodes
            if role not in STRUCTURAL_ROLES:
                result.append(node)
                continue

            # Keep named structural nodes
            if name is not None:
                result.append(node)
                continue

            # Unnamed structural: keep only if a descendant has a ref
            if self._has_descendant_with_ref(nodes, i, ref_set):
                result.append(node)

        return result

    @staticmethod
    def _has_descendant_with_ref(
        nodes: list[dict[str, Any]],
        index: int,
        ref_set: set[str],
    ) -> bool:
        """Check if any descendant of nodes[index] has a ref."""
        parent_depth = nodes[index]["depth"]
        for j in range(index + 1, len(nodes)):
            if nodes[j]["depth"] <= parent_depth:
                break
            if nodes[j].get("ref") and nodes[j]["ref"] in ref_set:
                return True
        return False
