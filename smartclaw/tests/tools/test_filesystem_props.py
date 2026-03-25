"""Property-based tests for filesystem tools.

Uses hypothesis with @settings(max_examples=100).
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from smartclaw.security.path_policy import PathPolicy
from smartclaw.tools.filesystem import (
    TRUNCATION_SUFFIX,
    ListDirectoryTool,
    ReadFileTool,
    WriteFileTool,
)

# Resolved tmp dir
_resolved_tmp = str(pathlib.Path(tempfile.gettempdir()).resolve())

# Safe filename strategy
_safe_name = st.from_regex(r"[a-zA-Z][a-zA-Z0-9_]{0,15}", fullmatch=True)

# Text content strategy (printable ASCII to avoid encoding issues)
_content = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z"), max_codepoint=127),
    min_size=0,
    max_size=500,
)


def _permissive_policy(base: pathlib.Path) -> PathPolicy:
    resolved = str(base.resolve())
    return PathPolicy(allowed_patterns=[resolved, f"{resolved}/**"])


# ---------------------------------------------------------------------------
# Property 7: Filesystem write/read round-trip
# ---------------------------------------------------------------------------


# Feature: smartclaw-tool-system, Property 7: Filesystem write/read round-trip
@given(name=_safe_name, content=_content)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_write_read_roundtrip(name: str, content: str, tmp_path: pathlib.Path) -> None:
    """For any valid path and string content, writing then reading returns
    the original content.

    **Validates: Requirements 3.1, 3.3**
    """
    policy = _permissive_policy(tmp_path)
    writer = WriteFileTool(path_policy=policy)
    reader = ReadFileTool(path_policy=policy)

    fpath = str(tmp_path / f"{name}.txt")
    await writer._arun(path=fpath, content=content)
    result = await reader._arun(path=fpath)
    assert result == content


# ---------------------------------------------------------------------------
# Property 8: Filesystem error contains path
# ---------------------------------------------------------------------------


# Feature: smartclaw-tool-system, Property 8: Filesystem error contains path
@given(name=_safe_name)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_error_contains_path(name: str, tmp_path: pathlib.Path) -> None:
    """For any non-existent file path, read_file returns a string containing
    the path. Same for non-existent directory with list_directory.

    **Validates: Requirements 3.2, 3.6**
    """
    policy = _permissive_policy(tmp_path)
    reader = ReadFileTool(path_policy=policy)
    lister = ListDirectoryTool(path_policy=policy)

    missing_file = str(tmp_path / f"missing_{name}.txt")
    missing_dir = str(tmp_path / f"missing_dir_{name}")

    read_result = await reader._arun(path=missing_file)
    assert missing_file in read_result

    list_result = await lister._arun(path=missing_dir)
    assert missing_dir in list_result


# ---------------------------------------------------------------------------
# Property 9: Filesystem policy enforcement
# ---------------------------------------------------------------------------


# Feature: smartclaw-tool-system, Property 9: Filesystem policy enforcement
@given(name=_safe_name)
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_policy_enforcement(name: str) -> None:
    """For any path denied by PathPolicy, all filesystem tools return the
    error string without performing I/O.

    **Validates: Requirements 3.7**
    """
    # Policy that denies everything under /denied_area
    policy = PathPolicy(
        allowed_patterns=["/allowed_only/**"],
        denied_patterns=[],
    )
    denied_path = f"/denied_area/{name}.txt"

    reader = ReadFileTool(path_policy=policy)
    writer = WriteFileTool(path_policy=policy)
    lister = ListDirectoryTool(path_policy=policy)

    for tool_fn in [
        lambda: reader._arun(path=denied_path),
        lambda: writer._arun(path=denied_path, content="x"),
        lambda: lister._arun(path=denied_path),
    ]:
        result = await tool_fn()
        assert "Error:" in result
        assert "Access denied" in result


# ---------------------------------------------------------------------------
# Property 10: Filesystem read truncation
# ---------------------------------------------------------------------------


# Feature: smartclaw-tool-system, Property 10: Filesystem read truncation
@given(
    name=_safe_name,
    max_bytes=st.integers(min_value=10, max_value=200),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_read_truncation(name: str, max_bytes: int, tmp_path: pathlib.Path) -> None:
    """For any file exceeding max_bytes, read_file returns content of at most
    max_bytes length with a truncation suffix.

    **Validates: Requirements 3.8, 3.9**
    """
    policy = _permissive_policy(tmp_path)
    reader = ReadFileTool(path_policy=policy)

    # Create a file larger than max_bytes
    content = "A" * (max_bytes + 100)
    fpath = tmp_path / f"{name}.txt"
    fpath.write_text(content)

    result = await reader._arun(path=str(fpath), max_bytes=max_bytes)
    # The result should contain the truncation suffix
    assert TRUNCATION_SUFFIX in result
    # The content portion (before suffix) should be at most max_bytes
    content_part = result[: result.index(TRUNCATION_SUFFIX)]
    assert len(content_part) <= max_bytes
