"""Property-based tests for EditFileTool and AppendFileTool.

Tests Properties 1–4 and 10 from the design document.
"""

from __future__ import annotations

import asyncio
import pathlib
import tempfile

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from smartclaw.security.path_policy import PathPolicy
from smartclaw.tools.edit import AppendFileTool, EditFileTool, replace_single_occurrence

_safe_name = st.from_regex(r"[a-zA-Z][a-zA-Z0-9_]{0,15}", fullmatch=True)
_content = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z"), max_codepoint=127),
    min_size=1,
    max_size=200,
)


# Feature: smartclaw-tools-supplement, Property 1: Edit file single-replacement round-trip
@settings(max_examples=100)
@given(prefix=_content, old=_content, suffix=_content, new=_content)
def test_edit_single_replacement_roundtrip(prefix: str, old: str, suffix: str, new: str) -> None:
    if old in prefix or old in suffix:
        return
    content = prefix + old + suffix
    if content.count(old) != 1:
        return
    result = replace_single_occurrence(content, old, new)
    assert result == prefix + new + suffix


# Feature: smartclaw-tools-supplement, Property 2: Edit file rejects non-unique matches
@settings(max_examples=100)
@given(old=_content)
def test_edit_rejects_not_found(old: str) -> None:
    content = "completely different text that has nothing in common"
    if old in content:
        return
    with pytest.raises(ValueError, match="not found"):
        replace_single_occurrence(content, old, "replacement")


@settings(max_examples=100)
@given(old=st.text(min_size=1, max_size=10))
def test_edit_rejects_ambiguous(old: str) -> None:
    content = old + "---" + old + "---" + old
    count = content.count(old)
    if count <= 1:
        return
    with pytest.raises(ValueError, match=f"{count} times"):
        replace_single_occurrence(content, old, "replacement")


# Feature: smartclaw-tools-supplement, Property 3: PathPolicy enforcement
@settings(max_examples=100)
@given(filename=_safe_name)
def test_edit_append_policy_enforcement(filename: str) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = pathlib.Path(tmp_dir)
        denied_path = str(tmp_path / filename)
        policy = PathPolicy(denied_patterns=[f"{tmp_path.resolve()}/**"])

        edit_tool = EditFileTool(path_policy=policy)
        result = asyncio.run(edit_tool._arun(path=denied_path, old_text="a", new_text="b"))
        assert "Access denied" in result

        append_tool = AppendFileTool(path_policy=policy)
        result = asyncio.run(append_tool._arun(path=denied_path, content="test"))
        assert "Access denied" in result


# Feature: smartclaw-tools-supplement, Property 4: Append preserves existing content
@settings(max_examples=100)
@given(original=_content, suffix=_content)
def test_append_preserves_content(original: str, suffix: str) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        filepath = pathlib.Path(tmp_dir) / "test_append.txt"
        filepath.write_text(original, encoding="utf-8")

        tool = AppendFileTool(path_policy=PathPolicy())
        asyncio.run(tool._arun(path=str(filepath), content=suffix))

        assert filepath.read_text(encoding="utf-8") == original + suffix


# Feature: smartclaw-tools-supplement, Property 10: _safe_run catches all exceptions
@settings(max_examples=100)
@given(msg=st.text(min_size=1, max_size=100))
def test_safe_run_catches_exceptions(msg: str) -> None:
    tool = EditFileTool(path_policy=PathPolicy())

    async def _failing() -> str:
        raise RuntimeError(msg)

    result = asyncio.run(tool._safe_run(_failing()))
    assert result.startswith("Error:")
