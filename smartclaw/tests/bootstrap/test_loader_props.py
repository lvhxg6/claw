"""Property-based tests for BootstrapLoader.

Uses hypothesis with @settings(max_examples=100).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from smartclaw.bootstrap.loader import (
    BootstrapFile,
    BootstrapFileType,
    BootstrapLoader,
    MAX_BOOTSTRAP_FILE_SIZE,
)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for generating valid bootstrap file types
_bootstrap_file_types = st.sampled_from(list(BootstrapFileType))

# Strategy for generating valid markdown content for bootstrap files
_bootstrap_content = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        whitelist_characters="\n\t -#*_[](){}",
    ),
    min_size=1,
    max_size=500,
).map(lambda s: f"# Bootstrap Content\n\n{s}")

# Strategy for generating distinct workspace and global content
_distinct_contents = st.tuples(
    st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "S", "Z"),
            whitelist_characters="\n\t -#*_[](){}",
        ),
        min_size=10,
        max_size=300,
    ).map(lambda s: f"# Workspace Content\n\n{s}"),
    st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "S", "Z"),
            whitelist_characters="\n\t -#*_[](){}",
        ),
        min_size=10,
        max_size=300,
    ).map(lambda s: f"# Global Content\n\n{s}"),
).filter(lambda pair: pair[0] != pair[1])


def _create_unique_dirs(tmp_path: Path) -> tuple[Path, Path]:
    """Create unique workspace and global directories for each test run."""
    unique_id = uuid.uuid4().hex[:8]
    workspace_dir = tmp_path / f"workspace_{unique_id}"
    global_dir = tmp_path / f"global_{unique_id}"
    workspace_dir.mkdir(parents=True, exist_ok=True)
    global_dir.mkdir(parents=True, exist_ok=True)
    return workspace_dir, global_dir


# ---------------------------------------------------------------------------
# Property 5: Bootstrap 文件优先级覆盖
# ---------------------------------------------------------------------------


class TestBootstrapFilePriorityProperties:
    """Property-based tests for Bootstrap file priority override (Property 5).
    
    **Validates: Requirements 2.1, 2.3**
    
    Requirements 2.1 states:
    - THE BootstrapLoader SHALL 支持以下 Bootstrap 文件，按优先级从高到低查找：
      工作空间级（`<workspace>/`）、全局级（`~/.smartclaw/`）
    
    Requirements 2.3 states:
    - WHEN 同一文件在多个级别存在时，THE BootstrapLoader SHALL 使用工作空间级文件覆盖全局级文件
    
    Property 5 from design.md:
    - 对于任意 Bootstrap 文件类型 T，当 workspace 和 global 目录都存在该文件时，
      load_file(T) 返回 workspace 版本
    - 当仅 global 目录存在该文件时，load_file(T) 返回 global 版本
    """

    @given(
        file_type=_bootstrap_file_types,
        contents=_distinct_contents,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_workspace_file_overrides_global_file(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        contents: tuple[str, str],
    ) -> None:
        """Property 5: Workspace file takes priority over global file
        
        For any Bootstrap file type T, when both workspace and global
        directories contain the file, load_file(T) should return the
        workspace version content.
        
        **Validates: Requirements 2.1, 2.3**
        """
        workspace_content, global_content = contents
        
        # Create unique workspace and global directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create file in both directories with different content
        filename = file_type.value
        (workspace_dir / filename).write_text(workspace_content, encoding="utf-8")
        (global_dir / filename).write_text(global_content, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Load file
        result = loader.load_file(file_type)
        
        # Should return workspace version
        assert result is not None, f"Expected to load {filename}"
        assert result.content == workspace_content, (
            f"Expected workspace content for {filename}, but got global content. "
            f"Workspace content starts with: {workspace_content[:50]}... "
            f"Got content starts with: {result.content[:50]}..."
        )
        assert result.source == "workspace", (
            f"Expected source to be 'workspace', but got '{result.source}'"
        )

    @given(
        file_type=_bootstrap_file_types,
        global_content=_bootstrap_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_global_file_loaded_when_workspace_missing(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        global_content: str,
    ) -> None:
        """Property 5: Global file is loaded when workspace file is missing
        
        For any Bootstrap file type T, when only the global directory
        contains the file (workspace directory is empty or doesn't have it),
        load_file(T) should return the global version content.
        
        **Validates: Requirements 2.1, 2.3**
        """
        # Create unique workspace and global directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create file only in global directory
        filename = file_type.value
        (global_dir / filename).write_text(global_content, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Load file
        result = loader.load_file(file_type)
        
        # Should return global version
        assert result is not None, f"Expected to load {filename} from global"
        assert result.content == global_content, (
            f"Expected global content for {filename}"
        )
        assert result.source == "global", (
            f"Expected source to be 'global', but got '{result.source}'"
        )

    @given(
        file_type=_bootstrap_file_types,
        workspace_content=_bootstrap_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_workspace_file_loaded_when_global_missing(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        workspace_content: str,
    ) -> None:
        """Property 5: Workspace file is loaded when global file is missing
        
        For any Bootstrap file type T, when only the workspace directory
        contains the file (global directory is empty or doesn't have it),
        load_file(T) should return the workspace version content.
        
        **Validates: Requirements 2.1, 2.3**
        """
        # Create unique workspace and global directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create file only in workspace directory
        filename = file_type.value
        (workspace_dir / filename).write_text(workspace_content, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Load file
        result = loader.load_file(file_type)
        
        # Should return workspace version
        assert result is not None, f"Expected to load {filename} from workspace"
        assert result.content == workspace_content, (
            f"Expected workspace content for {filename}"
        )
        assert result.source == "workspace", (
            f"Expected source to be 'workspace', but got '{result.source}'"
        )

    @given(file_type=_bootstrap_file_types)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_returns_none_when_file_missing_everywhere(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
    ) -> None:
        """Property 5: Returns None when file doesn't exist in any directory
        
        For any Bootstrap file type T, when neither workspace nor global
        directory contains the file, load_file(T) should return None.
        
        **Validates: Requirements 2.1, 2.3**
        """
        # Create unique empty workspace and global directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Load file
        result = loader.load_file(file_type)
        
        # Should return None
        assert result is None, (
            f"Expected None when {file_type.value} doesn't exist anywhere"
        )

    @given(
        file_types=st.lists(
            _bootstrap_file_types,
            min_size=1,
            max_size=3,
            unique=True,
        ),
        workspace_content=_bootstrap_content,
        global_content=_bootstrap_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_priority_applies_to_all_file_types(
        self,
        tmp_path: Path,
        file_types: list[BootstrapFileType],
        workspace_content: str,
        global_content: str,
    ) -> None:
        """Property 5: Priority rule applies consistently to all file types
        
        For any combination of Bootstrap file types (SOUL.md, USER.md, TOOLS.md),
        the workspace priority rule should apply consistently to each type.
        
        **Validates: Requirements 2.1, 2.3**
        """
        # Ensure contents are different
        assume(workspace_content != global_content)
        
        # Create unique workspace and global directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create files in both directories for all types
        for file_type in file_types:
            filename = file_type.value
            ws_content = f"{workspace_content}\n\n<!-- Type: {file_type.name} -->"
            gl_content = f"{global_content}\n\n<!-- Type: {file_type.name} -->"
            (workspace_dir / filename).write_text(ws_content, encoding="utf-8")
            (global_dir / filename).write_text(gl_content, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Verify priority for each file type
        for file_type in file_types:
            result = loader.load_file(file_type)
            
            assert result is not None, f"Expected to load {file_type.value}"
            assert result.source == "workspace", (
                f"Expected workspace priority for {file_type.value}, "
                f"but got source '{result.source}'"
            )
            expected_content = f"{workspace_content}\n\n<!-- Type: {file_type.name} -->"
            assert result.content == expected_content, (
                f"Expected workspace content for {file_type.value}"
            )

    @given(
        file_type=_bootstrap_file_types,
        contents=_distinct_contents,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_priority_is_deterministic(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        contents: tuple[str, str],
    ) -> None:
        """Property 5: Priority selection is deterministic
        
        For any Bootstrap file type T with files in both directories,
        loading multiple times should always return the same result
        (deterministic behavior).
        
        **Validates: Requirements 2.1, 2.3**
        """
        workspace_content, global_content = contents
        
        # Create unique workspace and global directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create file in both directories
        filename = file_type.value
        (workspace_dir / filename).write_text(workspace_content, encoding="utf-8")
        (global_dir / filename).write_text(global_content, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Load multiple times
        results = [loader.load_file(file_type) for _ in range(5)]
        
        # All results should be identical
        assert all(r is not None for r in results), "All loads should succeed"
        assert all(r.content == results[0].content for r in results), (
            "Loading should be deterministic - got different content on multiple loads"
        )
        assert all(r.source == results[0].source for r in results), (
            "Loading should be deterministic - got different source on multiple loads"
        )
        # Should always be workspace
        assert results[0].source == "workspace"

    @given(
        file_type=_bootstrap_file_types,
        global_content=_bootstrap_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_global_fallback_when_workspace_dir_not_set(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        global_content: str,
    ) -> None:
        """Property 5: Falls back to global when workspace_dir is None
        
        For any Bootstrap file type T, when workspace_dir is not set (None),
        the loader should fall back to global directory.
        
        **Validates: Requirements 2.1, 2.3**
        """
        # Create only global directory with unique name
        unique_id = uuid.uuid4().hex[:8]
        global_dir = tmp_path / f"global_{unique_id}"
        global_dir.mkdir(parents=True, exist_ok=True)
        
        # Create file in global directory
        filename = file_type.value
        (global_dir / filename).write_text(global_content, encoding="utf-8")
        
        # Create loader without workspace_dir
        loader = BootstrapLoader(
            workspace_dir=None,
            global_dir=str(global_dir),
        )
        
        # Load file
        result = loader.load_file(file_type)
        
        # Should return global version
        assert result is not None, f"Expected to load {filename} from global"
        assert result.content == global_content
        assert result.source == "global"

    @given(
        file_type=_bootstrap_file_types,
        contents=_distinct_contents,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_load_all_respects_priority(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        contents: tuple[str, str],
    ) -> None:
        """Property 5: load_all() respects workspace priority
        
        For any Bootstrap file type T, when using load_all() to load
        all bootstrap files, the priority rule should still apply.
        
        **Validates: Requirements 2.1, 2.3**
        """
        workspace_content, global_content = contents
        
        # Create unique workspace and global directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create file in both directories
        filename = file_type.value
        (workspace_dir / filename).write_text(workspace_content, encoding="utf-8")
        (global_dir / filename).write_text(global_content, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Load all files
        result = loader.load_all()
        
        # Should have the file type in result
        assert file_type in result, f"Expected {file_type.value} in load_all() result"
        
        # Should be workspace version
        assert result[file_type].content == workspace_content, (
            f"load_all() should return workspace content for {file_type.value}"
        )
        assert result[file_type].source == "workspace"

    @given(
        file_type=_bootstrap_file_types,
        workspace_content=_bootstrap_content,
        global_content=_bootstrap_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_content_getters_respect_priority(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        workspace_content: str,
        global_content: str,
    ) -> None:
        """Property 5: Content getter methods respect workspace priority
        
        For any Bootstrap file type T, the corresponding content getter
        method (get_soul_content, get_user_content, get_tools_content)
        should return workspace content when both exist.
        
        **Validates: Requirements 2.1, 2.3**
        """
        # Ensure contents are different
        assume(workspace_content != global_content)
        
        # Create unique workspace and global directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create file in both directories
        filename = file_type.value
        (workspace_dir / filename).write_text(workspace_content, encoding="utf-8")
        (global_dir / filename).write_text(global_content, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Get content using the appropriate getter
        if file_type == BootstrapFileType.SOUL:
            content = loader.get_soul_content()
        elif file_type == BootstrapFileType.USER:
            content = loader.get_user_content()
        else:  # TOOLS
            content = loader.get_tools_content()
        
        # Should return workspace content
        assert content == workspace_content, (
            f"Content getter for {file_type.value} should return workspace content"
        )


# ---------------------------------------------------------------------------
# Additional edge case tests for Property 5
# ---------------------------------------------------------------------------


class TestBootstrapFilePriorityEdgeCases:
    """Edge case tests for Bootstrap file priority (Property 5).
    
    **Validates: Requirements 2.1, 2.3**
    """

    @given(
        file_type=_bootstrap_file_types,
        workspace_content=_bootstrap_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_workspace_priority_with_nonexistent_global_dir(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        workspace_content: str,
    ) -> None:
        """Property 5 (edge case): Workspace file loads when global dir doesn't exist
        
        For any Bootstrap file type T, when the global directory doesn't
        exist at all, the workspace file should still be loaded correctly.
        
        **Validates: Requirements 2.1, 2.3**
        """
        # Create only workspace directory with unique name
        unique_id = uuid.uuid4().hex[:8]
        workspace_dir = tmp_path / f"workspace_{unique_id}"
        workspace_dir.mkdir(parents=True, exist_ok=True)
        
        # Global directory doesn't exist
        global_dir = tmp_path / f"nonexistent_global_{unique_id}"
        
        # Create file in workspace
        filename = file_type.value
        (workspace_dir / filename).write_text(workspace_content, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Load file
        result = loader.load_file(file_type)
        
        # Should return workspace version
        assert result is not None
        assert result.content == workspace_content
        assert result.source == "workspace"

    @given(
        file_type=_bootstrap_file_types,
        global_content=_bootstrap_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_global_fallback_with_nonexistent_workspace_dir(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        global_content: str,
    ) -> None:
        """Property 5 (edge case): Global file loads when workspace dir doesn't exist
        
        For any Bootstrap file type T, when the workspace directory doesn't
        exist at all, the global file should be loaded as fallback.
        
        **Validates: Requirements 2.1, 2.3**
        """
        # Create unique directories
        unique_id = uuid.uuid4().hex[:8]
        
        # Workspace directory doesn't exist
        workspace_dir = tmp_path / f"nonexistent_workspace_{unique_id}"
        
        # Create only global directory
        global_dir = tmp_path / f"global_{unique_id}"
        global_dir.mkdir(parents=True, exist_ok=True)
        
        # Create file in global
        filename = file_type.value
        (global_dir / filename).write_text(global_content, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Load file
        result = loader.load_file(file_type)
        
        # Should return global version
        assert result is not None
        assert result.content == global_content
        assert result.source == "global"

    @given(
        file_type=_bootstrap_file_types,
        contents=_distinct_contents,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_workspace_empty_file_still_takes_priority(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        contents: tuple[str, str],
    ) -> None:
        """Property 5 (edge case): Empty workspace file takes priority over global
        
        For any Bootstrap file type T, when workspace has an empty file
        and global has content, the empty workspace file should still
        take priority (empty string is valid content).
        
        **Validates: Requirements 2.1, 2.3**
        """
        _, global_content = contents
        
        # Create unique workspace and global directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create empty file in workspace, content in global
        filename = file_type.value
        (workspace_dir / filename).write_text("", encoding="utf-8")
        (global_dir / filename).write_text(global_content, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Load file
        result = loader.load_file(file_type)
        
        # Should return workspace version (empty)
        assert result is not None
        assert result.content == "", (
            "Empty workspace file should take priority over global content"
        )
        assert result.source == "workspace"

    @given(
        file_type=_bootstrap_file_types,
        workspace_content=_bootstrap_content,
        global_content=_bootstrap_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_cache_invalidation_respects_priority(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        workspace_content: str,
        global_content: str,
    ) -> None:
        """Property 5 (edge case): Cache invalidation still respects priority
        
        For any Bootstrap file type T, after cache invalidation,
        the priority rule should still apply correctly.
        
        **Validates: Requirements 2.1, 2.3**
        """
        # Ensure contents are different
        assume(workspace_content != global_content)
        
        # Create unique workspace and global directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create file in both directories
        filename = file_type.value
        (workspace_dir / filename).write_text(workspace_content, encoding="utf-8")
        (global_dir / filename).write_text(global_content, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Load file (populates cache)
        result1 = loader.load_file(file_type)
        assert result1 is not None
        assert result1.source == "workspace"
        
        # Invalidate cache
        loader.invalidate_cache(file_type)
        
        # Load again
        result2 = loader.load_file(file_type)
        
        # Should still return workspace version
        assert result2 is not None
        assert result2.content == workspace_content
        assert result2.source == "workspace"

    @given(
        file_type=_bootstrap_file_types,
        workspace_content=_bootstrap_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_unicode_content_priority(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        workspace_content: str,
    ) -> None:
        """Property 5 (edge case): Unicode content respects priority
        
        For any Bootstrap file type T with Unicode content,
        the priority rule should apply correctly.
        
        **Validates: Requirements 2.1, 2.3**
        """
        # Create unique workspace and global directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create files with Unicode content
        filename = file_type.value
        ws_unicode = f"# 工作空间内容 🚀\n\n{workspace_content}"
        gl_unicode = f"# 全局内容 🌍\n\n{workspace_content}"
        
        (workspace_dir / filename).write_text(ws_unicode, encoding="utf-8")
        (global_dir / filename).write_text(gl_unicode, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Load file
        result = loader.load_file(file_type)
        
        # Should return workspace version with Unicode
        assert result is not None
        assert result.content == ws_unicode
        assert result.source == "workspace"
        assert "工作空间" in result.content
        assert "🚀" in result.content


# ---------------------------------------------------------------------------
# Property 6: Bootstrap 文件大小限制
# ---------------------------------------------------------------------------


class TestBootstrapFileSizeLimitProperties:
    """Property-based tests for Bootstrap file size limits (Property 6).
    
    **Validates: Requirements 2.4**
    
    Requirements 2.4 states:
    - THE BootstrapLoader SHALL 对每个 Bootstrap 文件大小进行限制，最大不超过 512KB
    
    Property 6 from design.md:
    - 对于任意 Bootstrap 文件 F，当 size(F) > 512KB 时，load_file() 返回 None
    - 对于任意 Bootstrap 文件 F，当 size(F) ≤ 512KB 时，load_file() 返回文件内容
    """

    @given(
        file_type=_bootstrap_file_types,
        # Generate excess bytes beyond the limit (1 to 512KB extra)
        excess_bytes=st.integers(min_value=1, max_value=512 * 1024),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_file_exceeding_size_limit_returns_none(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        excess_bytes: int,
    ) -> None:
        """Property 6: Files exceeding 512KB size limit should return None
        
        For any Bootstrap file F, when size(F) > 512KB, load_file() should
        return None and reject the file.
        
        **Validates: Requirements 2.4**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create file that exceeds the size limit
        filename = file_type.value
        
        # Generate content that exceeds the limit
        # Start with a header, then add enough padding to exceed MAX_BOOTSTRAP_FILE_SIZE
        header = "# Large Bootstrap File\n\n"
        # Calculate padding needed: MAX_BOOTSTRAP_FILE_SIZE - header_bytes + excess_bytes
        header_bytes = len(header.encode("utf-8"))
        padding_size = MAX_BOOTSTRAP_FILE_SIZE - header_bytes + excess_bytes
        content = header + ("x" * padding_size)
        
        (workspace_dir / filename).write_text(content, encoding="utf-8")
        
        # Verify file size exceeds limit
        actual_size = (workspace_dir / filename).stat().st_size
        assert actual_size > MAX_BOOTSTRAP_FILE_SIZE, (
            f"Test setup error: file size {actual_size} should exceed {MAX_BOOTSTRAP_FILE_SIZE}"
        )
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Load file - should return None due to size limit
        result = loader.load_file(file_type)
        
        assert result is None, (
            f"Expected None for {filename} with size {actual_size} bytes "
            f"(exceeds limit of {MAX_BOOTSTRAP_FILE_SIZE} bytes), "
            f"but got content of length {len(result.content) if result else 0}"
        )

    @given(
        file_type=_bootstrap_file_types,
        # Generate file sizes within the limit (1 byte to 512KB)
        content_size=st.integers(min_value=1, max_value=10000),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_file_within_size_limit_returns_content(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        content_size: int,
    ) -> None:
        """Property 6: Files within 512KB size limit should return content
        
        For any Bootstrap file F, when size(F) ≤ 512KB, load_file() should
        return the file content.
        
        **Validates: Requirements 2.4**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create file within the size limit
        filename = file_type.value
        content = "# Bootstrap Content\n\n" + ("a" * content_size)
        
        (workspace_dir / filename).write_text(content, encoding="utf-8")
        
        # Verify file size is within limit
        actual_size = (workspace_dir / filename).stat().st_size
        assert actual_size <= MAX_BOOTSTRAP_FILE_SIZE, (
            f"Test setup error: file size {actual_size} should be within {MAX_BOOTSTRAP_FILE_SIZE}"
        )
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Load file - should return content
        result = loader.load_file(file_type)
        
        assert result is not None, (
            f"Expected content for {filename} with size {actual_size} bytes "
            f"(within limit of {MAX_BOOTSTRAP_FILE_SIZE} bytes)"
        )
        assert result.content == content, (
            f"Expected exact content match for {filename}"
        )

    @given(file_type=_bootstrap_file_types)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_file_exactly_at_size_limit_returns_content(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
    ) -> None:
        """Property 6: Files exactly at 512KB size limit should return content
        
        For any Bootstrap file F, when size(F) == 512KB exactly, load_file()
        should return the file content (boundary condition).
        
        **Validates: Requirements 2.4**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create file exactly at the size limit
        filename = file_type.value
        # Account for header and create content to reach exactly MAX_BOOTSTRAP_FILE_SIZE
        header = "# Bootstrap\n"
        padding_size = MAX_BOOTSTRAP_FILE_SIZE - len(header.encode("utf-8"))
        content = header + ("b" * padding_size)
        
        (workspace_dir / filename).write_text(content, encoding="utf-8")
        
        # Verify file size is exactly at limit
        actual_size = (workspace_dir / filename).stat().st_size
        assert actual_size == MAX_BOOTSTRAP_FILE_SIZE, (
            f"Test setup error: file size {actual_size} should be exactly {MAX_BOOTSTRAP_FILE_SIZE}"
        )
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Load file - should return content (boundary is inclusive)
        result = loader.load_file(file_type)
        
        assert result is not None, (
            f"Expected content for {filename} with size exactly at limit "
            f"({MAX_BOOTSTRAP_FILE_SIZE} bytes)"
        )
        assert result.content == content
        assert result.size == MAX_BOOTSTRAP_FILE_SIZE

    @given(file_type=_bootstrap_file_types)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_file_one_byte_over_limit_returns_none(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
    ) -> None:
        """Property 6: Files one byte over 512KB limit should return None
        
        For any Bootstrap file F, when size(F) == 512KB + 1 byte, load_file()
        should return None (boundary condition).
        
        **Validates: Requirements 2.4**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create file one byte over the size limit
        filename = file_type.value
        header = "# Bootstrap\n"
        padding_size = MAX_BOOTSTRAP_FILE_SIZE - len(header.encode("utf-8")) + 1
        content = header + ("c" * padding_size)
        
        (workspace_dir / filename).write_text(content, encoding="utf-8")
        
        # Verify file size is one byte over limit
        actual_size = (workspace_dir / filename).stat().st_size
        assert actual_size == MAX_BOOTSTRAP_FILE_SIZE + 1, (
            f"Test setup error: file size {actual_size} should be {MAX_BOOTSTRAP_FILE_SIZE + 1}"
        )
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Load file - should return None
        result = loader.load_file(file_type)
        
        assert result is None, (
            f"Expected None for {filename} with size one byte over limit "
            f"({MAX_BOOTSTRAP_FILE_SIZE + 1} bytes)"
        )

    @given(
        file_type=_bootstrap_file_types,
        workspace_excess=st.integers(min_value=1, max_value=1024),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_oversized_workspace_falls_back_to_valid_global(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        workspace_excess: int,
    ) -> None:
        """Property 6: Oversized workspace file should fall back to valid global file
        
        For any Bootstrap file type T, when workspace file exceeds size limit
        but global file is within limit, load_file(T) should return the global
        version (combining Property 5 priority with Property 6 size limit).
        
        **Validates: Requirements 2.4**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        filename = file_type.value
        
        # Create oversized file in workspace
        ws_header = "# Workspace (too large)\n"
        ws_header_bytes = len(ws_header.encode("utf-8"))
        ws_padding = MAX_BOOTSTRAP_FILE_SIZE - ws_header_bytes + workspace_excess
        ws_content = ws_header + ("w" * ws_padding)
        (workspace_dir / filename).write_text(ws_content, encoding="utf-8")
        
        # Create valid-sized file in global
        gl_content = "# Global Content (valid size)\n\nThis is valid content."
        (global_dir / filename).write_text(gl_content, encoding="utf-8")
        
        # Verify sizes
        ws_actual = (workspace_dir / filename).stat().st_size
        gl_actual = (global_dir / filename).stat().st_size
        assert ws_actual > MAX_BOOTSTRAP_FILE_SIZE
        assert gl_actual <= MAX_BOOTSTRAP_FILE_SIZE
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Load file - should fall back to global since workspace is oversized
        result = loader.load_file(file_type)
        
        assert result is not None, (
            f"Expected to load {filename} from global when workspace is oversized"
        )
        assert result.content == gl_content, (
            f"Expected global content when workspace file is oversized"
        )
        assert result.source == "global", (
            f"Expected source to be 'global' when workspace file is oversized"
        )

    @given(
        file_type=_bootstrap_file_types,
        workspace_excess=st.integers(min_value=1, max_value=1024),
        global_excess=st.integers(min_value=1, max_value=1024),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_both_oversized_returns_none(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        workspace_excess: int,
        global_excess: int,
    ) -> None:
        """Property 6: Both files oversized should return None
        
        For any Bootstrap file type T, when both workspace and global files
        exceed the size limit, load_file(T) should return None.
        
        **Validates: Requirements 2.4**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        filename = file_type.value
        
        # Create oversized files in both directories
        ws_header = "# Workspace (too large)\n"
        ws_header_bytes = len(ws_header.encode("utf-8"))
        ws_padding = MAX_BOOTSTRAP_FILE_SIZE - ws_header_bytes + workspace_excess
        ws_content = ws_header + ("w" * ws_padding)
        
        gl_header = "# Global (too large)\n"
        gl_header_bytes = len(gl_header.encode("utf-8"))
        gl_padding = MAX_BOOTSTRAP_FILE_SIZE - gl_header_bytes + global_excess
        gl_content = gl_header + ("g" * gl_padding)
        
        (workspace_dir / filename).write_text(ws_content, encoding="utf-8")
        (global_dir / filename).write_text(gl_content, encoding="utf-8")
        
        # Verify both are oversized
        assert (workspace_dir / filename).stat().st_size > MAX_BOOTSTRAP_FILE_SIZE
        assert (global_dir / filename).stat().st_size > MAX_BOOTSTRAP_FILE_SIZE
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Load file - should return None since both are oversized
        result = loader.load_file(file_type)
        
        assert result is None, (
            f"Expected None for {filename} when both workspace and global are oversized"
        )

    @given(
        file_type=_bootstrap_file_types,
        content_size=st.integers(min_value=100, max_value=5000),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_size_attribute_matches_actual_file_size(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        content_size: int,
    ) -> None:
        """Property 6: BootstrapFile.size should match actual file size
        
        For any successfully loaded Bootstrap file, the size attribute
        should accurately reflect the file's actual size in bytes.
        
        **Validates: Requirements 2.4**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create file with known content
        filename = file_type.value
        content = "# Test Content\n\n" + ("x" * content_size)
        (workspace_dir / filename).write_text(content, encoding="utf-8")
        
        # Get actual file size
        actual_size = (workspace_dir / filename).stat().st_size
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Load file
        result = loader.load_file(file_type)
        
        assert result is not None
        assert result.size == actual_size, (
            f"BootstrapFile.size ({result.size}) should match actual file size ({actual_size})"
        )

    @given(file_type=_bootstrap_file_types)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_load_all_respects_size_limit(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
    ) -> None:
        """Property 6: load_all() should respect size limits
        
        For any Bootstrap file type T, when using load_all() and the file
        exceeds the size limit, it should not be included in the result.
        
        **Validates: Requirements 2.4**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create oversized file
        filename = file_type.value
        oversized_content = "# Too Large\n" + ("x" * MAX_BOOTSTRAP_FILE_SIZE)
        (workspace_dir / filename).write_text(oversized_content, encoding="utf-8")
        
        # Verify file is oversized
        assert (workspace_dir / filename).stat().st_size > MAX_BOOTSTRAP_FILE_SIZE
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Load all files
        result = loader.load_all()
        
        # The oversized file type should not be in the result
        assert file_type not in result, (
            f"Oversized {filename} should not be included in load_all() result"
        )

    @given(
        file_type=_bootstrap_file_types,
        content_size=st.integers(min_value=100, max_value=5000),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_content_getters_respect_size_limit(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        content_size: int,
    ) -> None:
        """Property 6: Content getter methods should respect size limits
        
        For any Bootstrap file type T, when the file exceeds the size limit,
        the corresponding content getter should return empty string.
        
        **Validates: Requirements 2.4**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create oversized file
        filename = file_type.value
        oversized_content = "# Too Large\n" + ("x" * MAX_BOOTSTRAP_FILE_SIZE)
        (workspace_dir / filename).write_text(oversized_content, encoding="utf-8")
        
        # Verify file is oversized
        assert (workspace_dir / filename).stat().st_size > MAX_BOOTSTRAP_FILE_SIZE
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Get content using the appropriate getter
        if file_type == BootstrapFileType.SOUL:
            content = loader.get_soul_content()
        elif file_type == BootstrapFileType.USER:
            content = loader.get_user_content()
        else:  # TOOLS
            content = loader.get_tools_content()
        
        # Should return empty string for oversized file
        assert content == "", (
            f"Content getter for oversized {filename} should return empty string"
        )


# ---------------------------------------------------------------------------
# Edge case tests for Property 6
# ---------------------------------------------------------------------------


class TestBootstrapFileSizeLimitEdgeCases:
    """Edge case tests for Bootstrap file size limits (Property 6).
    
    **Validates: Requirements 2.4**
    """

    @given(file_type=_bootstrap_file_types)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_empty_file_within_limit(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
    ) -> None:
        """Property 6 (edge case): Empty file is within size limit
        
        For any Bootstrap file type T, an empty file (0 bytes) should
        be successfully loaded as it's within the size limit.
        
        **Validates: Requirements 2.4**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create empty file
        filename = file_type.value
        (workspace_dir / filename).write_text("", encoding="utf-8")
        
        # Verify file is empty
        assert (workspace_dir / filename).stat().st_size == 0
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Load file - should succeed
        result = loader.load_file(file_type)
        
        assert result is not None, "Empty file should be loadable"
        assert result.content == ""
        assert result.size == 0

    @given(
        file_type=_bootstrap_file_types,
        unicode_chars=st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N", "P", "S"),
                whitelist_characters="中文日本語한국어🚀🎉",
            ),
            min_size=100,
            max_size=1000,
        ),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_unicode_content_size_calculated_in_bytes(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        unicode_chars: str,
    ) -> None:
        """Property 6 (edge case): Size limit is calculated in bytes, not characters
        
        For any Bootstrap file with Unicode content, the size limit should
        be calculated based on byte size (UTF-8 encoded), not character count.
        
        **Validates: Requirements 2.4**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create file with Unicode content
        filename = file_type.value
        content = f"# Unicode Content 中文\n\n{unicode_chars}"
        (workspace_dir / filename).write_text(content, encoding="utf-8")
        
        # Get actual byte size
        actual_size = (workspace_dir / filename).stat().st_size
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Load file
        result = loader.load_file(file_type)
        
        if actual_size <= MAX_BOOTSTRAP_FILE_SIZE:
            assert result is not None, (
                f"File with {actual_size} bytes should be loadable"
            )
            assert result.size == actual_size
        else:
            assert result is None, (
                f"File with {actual_size} bytes should be rejected"
            )

    @given(file_type=_bootstrap_file_types)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_size_limit_constant_value(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
    ) -> None:
        """Property 6 (edge case): Size limit constant is 512KB
        
        Verify that MAX_BOOTSTRAP_FILE_SIZE is exactly 512KB (512 * 1024 bytes).
        
        **Validates: Requirements 2.4**
        """
        assert MAX_BOOTSTRAP_FILE_SIZE == 512 * 1024, (
            f"MAX_BOOTSTRAP_FILE_SIZE should be 512KB (524288 bytes), "
            f"but got {MAX_BOOTSTRAP_FILE_SIZE}"
        )


# ---------------------------------------------------------------------------
# Property 7: Bootstrap 文件缓存一致性
# ---------------------------------------------------------------------------


class TestBootstrapFileCacheConsistencyProperties:
    """Property-based tests for Bootstrap file cache consistency (Property 7).
    
    **Validates: Requirements 2.5**
    
    Requirements 2.5 states:
    - THE BootstrapLoader SHALL 实现文件缓存机制，基于文件修改时间（mtime）判断是否需要重新加载
    
    Property 7 from design.md:
    - 对于任意 Bootstrap 文件 F，当 mtime(F) 未变化时，load_file() 返回缓存内容
    - 对于任意 Bootstrap 文件 F，当 mtime(F) 变化时，load_file() 重新加载文件内容
    """

    @given(
        file_type=_bootstrap_file_types,
        content=_bootstrap_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_cache_returns_same_content_when_mtime_unchanged(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        content: str,
    ) -> None:
        """Property 7: Cache returns same content when mtime is unchanged
        
        For any Bootstrap file F, when mtime(F) has not changed between loads,
        load_file() should return the cached content without re-reading the file.
        
        **Validates: Requirements 2.5**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create file
        filename = file_type.value
        (workspace_dir / filename).write_text(content, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # First load (populates cache)
        result1 = loader.load_file(file_type)
        assert result1 is not None
        
        # Second load (should hit cache)
        result2 = loader.load_file(file_type)
        assert result2 is not None
        
        # Both results should have identical content and mtime
        assert result1.content == result2.content, (
            "Cache should return same content when mtime unchanged"
        )
        assert result1.mtime == result2.mtime, (
            "Cache should return same mtime when file unchanged"
        )

    @given(
        file_type=_bootstrap_file_types,
        contents=_distinct_contents,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_cache_reloads_when_mtime_changes(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        contents: tuple[str, str],
    ) -> None:
        """Property 7: Cache reloads file when mtime changes
        
        For any Bootstrap file F, when mtime(F) changes (file is modified),
        load_file() should reload the file and return the new content.
        
        **Validates: Requirements 2.5**
        """
        import time
        
        original_content, updated_content = contents
        
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create file with original content
        filename = file_type.value
        file_path = workspace_dir / filename
        file_path.write_text(original_content, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # First load (populates cache)
        result1 = loader.load_file(file_type)
        assert result1 is not None
        assert result1.content == original_content
        
        # Wait a bit to ensure mtime changes
        time.sleep(0.01)
        
        # Modify file (this changes mtime)
        file_path.write_text(updated_content, encoding="utf-8")
        
        # Second load (should detect mtime change and reload)
        result2 = loader.load_file(file_type)
        assert result2 is not None
        
        # Should return updated content
        assert result2.content == updated_content, (
            f"Cache should reload when mtime changes. "
            f"Expected updated content, but got original content."
        )
        assert result2.mtime > result1.mtime, (
            "New mtime should be greater than original mtime"
        )

    @given(
        file_type=_bootstrap_file_types,
        content=_bootstrap_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_invalidate_cache_specific_type_clears_only_that_type(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        content: str,
    ) -> None:
        """Property 7: invalidate_cache(file_type) clears only that type
        
        For any Bootstrap file type T, calling invalidate_cache(T) should
        clear only the cache for type T, leaving other types cached.
        
        **Validates: Requirements 2.5**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create files for all types
        for ft in BootstrapFileType:
            (workspace_dir / ft.value).write_text(
                f"# Content for {ft.name}\n\n{content}",
                encoding="utf-8",
            )
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Load all files (populates cache)
        for ft in BootstrapFileType:
            loader.load_file(ft)
        
        # Verify all are cached
        assert len(loader._cache) == len(BootstrapFileType)
        
        # Invalidate only the specified type
        loader.invalidate_cache(file_type)
        
        # Verify only that type was removed from cache
        assert file_type not in loader._cache, (
            f"Cache for {file_type.value} should be invalidated"
        )
        
        # Other types should still be cached
        for ft in BootstrapFileType:
            if ft != file_type:
                assert ft in loader._cache, (
                    f"Cache for {ft.value} should still exist after "
                    f"invalidating {file_type.value}"
                )

    @given(
        file_type=_bootstrap_file_types,
        content=_bootstrap_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_invalidate_cache_all_clears_entire_cache(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        content: str,
    ) -> None:
        """Property 7: invalidate_cache(None) clears entire cache
        
        For any set of cached Bootstrap files, calling invalidate_cache()
        without arguments should clear the entire cache.
        
        **Validates: Requirements 2.5**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create files for all types
        for ft in BootstrapFileType:
            (workspace_dir / ft.value).write_text(
                f"# Content for {ft.name}\n\n{content}",
                encoding="utf-8",
            )
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Load all files (populates cache)
        for ft in BootstrapFileType:
            loader.load_file(ft)
        
        # Verify all are cached
        assert len(loader._cache) == len(BootstrapFileType)
        
        # Invalidate all cache
        loader.invalidate_cache()
        
        # Verify cache is empty
        assert len(loader._cache) == 0, (
            "Cache should be empty after invalidate_cache()"
        )

    @given(
        file_type=_bootstrap_file_types,
        content=_bootstrap_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_cache_invalidated_when_file_deleted(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        content: str,
    ) -> None:
        """Property 7: Cache is invalidated when file is deleted
        
        For any cached Bootstrap file F, when F is deleted from the filesystem,
        load_file() should detect the deletion and return None.
        
        **Validates: Requirements 2.5**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create file
        filename = file_type.value
        file_path = workspace_dir / filename
        file_path.write_text(content, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # First load (populates cache)
        result1 = loader.load_file(file_type)
        assert result1 is not None
        assert result1.content == content
        
        # Delete the file
        file_path.unlink()
        
        # Second load (should detect deletion)
        result2 = loader.load_file(file_type)
        
        # Should return None since file no longer exists
        assert result2 is None, (
            "load_file() should return None when cached file is deleted"
        )

    @given(
        file_type=_bootstrap_file_types,
        content=_bootstrap_content,
        num_loads=st.integers(min_value=2, max_value=10),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_multiple_loads_return_consistent_cached_content(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        content: str,
        num_loads: int,
    ) -> None:
        """Property 7: Multiple loads return consistent cached content
        
        For any Bootstrap file F, multiple consecutive loads without file
        modification should all return the same cached content.
        
        **Validates: Requirements 2.5**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create file
        filename = file_type.value
        (workspace_dir / filename).write_text(content, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Load multiple times
        results = [loader.load_file(file_type) for _ in range(num_loads)]
        
        # All results should be non-None
        assert all(r is not None for r in results), (
            "All loads should succeed"
        )
        
        # All results should have identical content
        first_content = results[0].content
        assert all(r.content == first_content for r in results), (
            "All cached loads should return identical content"
        )
        
        # All results should have identical mtime
        first_mtime = results[0].mtime
        assert all(r.mtime == first_mtime for r in results), (
            "All cached loads should return identical mtime"
        )

    @given(
        file_type=_bootstrap_file_types,
        contents=_distinct_contents,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_cache_update_after_invalidation_and_file_change(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        contents: tuple[str, str],
    ) -> None:
        """Property 7: Cache updates correctly after invalidation and file change
        
        For any Bootstrap file F, after invalidating cache and modifying the file,
        load_file() should return the new content.
        
        **Validates: Requirements 2.5**
        """
        original_content, updated_content = contents
        
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create file with original content
        filename = file_type.value
        file_path = workspace_dir / filename
        file_path.write_text(original_content, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # First load (populates cache)
        result1 = loader.load_file(file_type)
        assert result1 is not None
        assert result1.content == original_content
        
        # Invalidate cache
        loader.invalidate_cache(file_type)
        
        # Modify file
        file_path.write_text(updated_content, encoding="utf-8")
        
        # Load again (should get new content)
        result2 = loader.load_file(file_type)
        assert result2 is not None
        
        # Should return updated content
        assert result2.content == updated_content, (
            "After cache invalidation and file change, should return new content"
        )


# ---------------------------------------------------------------------------
# Edge case tests for Property 7
# ---------------------------------------------------------------------------


class TestBootstrapFileCacheConsistencyEdgeCases:
    """Edge case tests for Bootstrap file cache consistency (Property 7).
    
    **Validates: Requirements 2.5**
    """

    @given(
        file_type=_bootstrap_file_types,
        content=_bootstrap_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_cache_handles_file_replaced_with_same_content(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        content: str,
    ) -> None:
        """Property 7 (edge case): Cache handles file replaced with same content
        
        For any Bootstrap file F, when F is replaced with a file containing
        the same content (but different mtime), load_file() should reload
        and return the same content.
        
        **Validates: Requirements 2.5**
        """
        import time
        
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create file
        filename = file_type.value
        file_path = workspace_dir / filename
        file_path.write_text(content, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # First load (populates cache)
        result1 = loader.load_file(file_type)
        assert result1 is not None
        original_mtime = result1.mtime
        
        # Wait and rewrite with same content (changes mtime)
        time.sleep(0.01)
        file_path.write_text(content, encoding="utf-8")
        
        # Second load (should detect mtime change and reload)
        result2 = loader.load_file(file_type)
        assert result2 is not None
        
        # Content should be the same
        assert result2.content == content
        
        # mtime should be different (file was rewritten)
        assert result2.mtime > original_mtime, (
            "mtime should change when file is rewritten"
        )

    @given(
        file_type=_bootstrap_file_types,
        workspace_content=_bootstrap_content,
        global_content=_bootstrap_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_cache_falls_back_to_global_when_workspace_deleted(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        workspace_content: str,
        global_content: str,
    ) -> None:
        """Property 7 (edge case): Cache falls back to global when workspace file deleted
        
        For any Bootstrap file F, when the workspace version is cached and then
        deleted, load_file() should fall back to the global version.
        
        **Validates: Requirements 2.5**
        """
        # Ensure contents are different
        assume(workspace_content != global_content)
        
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create files in both directories
        filename = file_type.value
        ws_file = workspace_dir / filename
        gl_file = global_dir / filename
        
        ws_file.write_text(workspace_content, encoding="utf-8")
        gl_file.write_text(global_content, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # First load (should get workspace version)
        result1 = loader.load_file(file_type)
        assert result1 is not None
        assert result1.content == workspace_content
        assert result1.source == "workspace"
        
        # Delete workspace file
        ws_file.unlink()
        
        # Second load (should fall back to global)
        result2 = loader.load_file(file_type)
        assert result2 is not None
        
        # Should return global content
        assert result2.content == global_content, (
            "Should fall back to global when workspace file is deleted"
        )
        assert result2.source == "global"

    @given(file_type=_bootstrap_file_types)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_invalidate_nonexistent_type_is_safe(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
    ) -> None:
        """Property 7 (edge case): Invalidating non-cached type is safe
        
        For any Bootstrap file type T that is not in the cache,
        calling invalidate_cache(T) should be a no-op (not raise an error).
        
        **Validates: Requirements 2.5**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create loader (no files, empty cache)
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Verify cache is empty
        assert len(loader._cache) == 0
        
        # Invalidate a type that's not in cache - should not raise
        loader.invalidate_cache(file_type)
        
        # Cache should still be empty
        assert len(loader._cache) == 0

    @given(
        file_type=_bootstrap_file_types,
        content=_bootstrap_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_cache_mtime_precision(
        self,
        tmp_path: Path,
        file_type: BootstrapFileType,
        content: str,
    ) -> None:
        """Property 7 (edge case): Cache mtime has sufficient precision
        
        For any Bootstrap file F, the cached mtime should match the
        filesystem mtime with sufficient precision to detect changes.
        
        **Validates: Requirements 2.5**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create file
        filename = file_type.value
        file_path = workspace_dir / filename
        file_path.write_text(content, encoding="utf-8")
        
        # Get filesystem mtime
        fs_mtime = file_path.stat().st_mtime
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Load file
        result = loader.load_file(file_type)
        assert result is not None
        
        # Cached mtime should match filesystem mtime
        assert result.mtime == fs_mtime, (
            f"Cached mtime ({result.mtime}) should match filesystem mtime ({fs_mtime})"
        )


# ---------------------------------------------------------------------------
# Property 8: SOUL.md 提示词位置
# ---------------------------------------------------------------------------


class TestSoulPromptPositionProperties:
    """Property-based tests for SOUL.md prompt position (Property 8).
    
    **Validates: Requirements 2.7**
    
    Requirements 2.7 states:
    - THE BootstrapLoader SHALL 在加载 SOUL.md 时，将内容作为系统提示词的第一部分，
      优先级高于默认 SYSTEM_PROMPT
    
    Property 8 from design.md:
    - 对于任意 SOUL.md 内容 S，get_soul_content() 返回的内容等于 S
    - SOUL.md 内容应用于系统提示词的开头位置
    """

    @given(soul_content=_bootstrap_content)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_get_soul_content_returns_exact_content(
        self,
        tmp_path: Path,
        soul_content: str,
    ) -> None:
        """Property 8: get_soul_content() returns exact SOUL.md content
        
        For any SOUL.md content S, get_soul_content() should return
        exactly S without any modification.
        
        **Validates: Requirements 2.7**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create SOUL.md file
        (workspace_dir / "SOUL.md").write_text(soul_content, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Get SOUL content
        result = loader.get_soul_content()
        
        # Should return exact content
        assert result == soul_content, (
            f"get_soul_content() should return exact SOUL.md content. "
            f"Expected: {soul_content[:100]}... Got: {result[:100]}..."
        )

    @given(soul_content=_bootstrap_content)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_get_soul_content_returns_empty_when_no_file(
        self,
        tmp_path: Path,
        soul_content: str,
    ) -> None:
        """Property 8: get_soul_content() returns empty string when SOUL.md doesn't exist
        
        For any workspace without SOUL.md, get_soul_content() should return
        an empty string, allowing the default SYSTEM_PROMPT to be used.
        
        **Validates: Requirements 2.7**
        """
        # Create unique directories (no SOUL.md file)
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Get SOUL content
        result = loader.get_soul_content()
        
        # Should return empty string
        assert result == "", (
            f"get_soul_content() should return empty string when SOUL.md doesn't exist, "
            f"but got: {result[:100]}..."
        )

    @given(
        workspace_soul=_bootstrap_content,
        global_soul=_bootstrap_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_get_soul_content_prefers_workspace_over_global(
        self,
        tmp_path: Path,
        workspace_soul: str,
        global_soul: str,
    ) -> None:
        """Property 8: get_soul_content() prefers workspace SOUL.md over global
        
        For any SOUL.md content, when both workspace and global versions exist,
        get_soul_content() should return the workspace version.
        
        **Validates: Requirements 2.7**
        """
        # Ensure contents are different
        assume(workspace_soul != global_soul)
        
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create SOUL.md in both directories
        (workspace_dir / "SOUL.md").write_text(workspace_soul, encoding="utf-8")
        (global_dir / "SOUL.md").write_text(global_soul, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Get SOUL content
        result = loader.get_soul_content()
        
        # Should return workspace version
        assert result == workspace_soul, (
            f"get_soul_content() should return workspace SOUL.md content, "
            f"not global content"
        )

    @given(global_soul=_bootstrap_content)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_get_soul_content_falls_back_to_global(
        self,
        tmp_path: Path,
        global_soul: str,
    ) -> None:
        """Property 8: get_soul_content() falls back to global when workspace missing
        
        For any SOUL.md content in global directory, when workspace doesn't have
        SOUL.md, get_soul_content() should return the global version.
        
        **Validates: Requirements 2.7**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create SOUL.md only in global directory
        (global_dir / "SOUL.md").write_text(global_soul, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Get SOUL content
        result = loader.get_soul_content()
        
        # Should return global version
        assert result == global_soul, (
            f"get_soul_content() should fall back to global SOUL.md content"
        )

    @given(soul_content=_bootstrap_content)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_soul_content_is_idempotent(
        self,
        tmp_path: Path,
        soul_content: str,
    ) -> None:
        """Property 8: get_soul_content() is idempotent
        
        For any SOUL.md content S, multiple calls to get_soul_content()
        should always return the same result.
        
        **Validates: Requirements 2.7**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create SOUL.md file
        (workspace_dir / "SOUL.md").write_text(soul_content, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Get SOUL content multiple times
        results = [loader.get_soul_content() for _ in range(5)]
        
        # All results should be identical
        assert all(r == soul_content for r in results), (
            "get_soul_content() should be idempotent - all calls should return same content"
        )

    @given(
        soul_content=st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N", "P", "S", "Z"),
                whitelist_characters="\n\t -#*_[](){}中文日本語한국어🚀🎉",
            ),
            min_size=10,
            max_size=500,
        ).map(lambda s: f"# SOUL 人格定义\n\n{s}"),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_soul_content_preserves_unicode(
        self,
        tmp_path: Path,
        soul_content: str,
    ) -> None:
        """Property 8: get_soul_content() preserves Unicode content
        
        For any SOUL.md content with Unicode characters (Chinese, Japanese,
        Korean, emojis, etc.), get_soul_content() should preserve all
        characters exactly.
        
        **Validates: Requirements 2.7**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create SOUL.md file with Unicode content
        (workspace_dir / "SOUL.md").write_text(soul_content, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Get SOUL content
        result = loader.get_soul_content()
        
        # Should preserve all Unicode characters
        assert result == soul_content, (
            f"get_soul_content() should preserve Unicode content exactly"
        )

    @given(
        soul_content=st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N", "P", "S", "Z"),
                whitelist_characters="\n\t -#*_[](){}",
            ),
            min_size=1,
            max_size=100,
        ).map(lambda s: f"# Agent Personality\n\n{s}\n\n"),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_soul_content_preserves_whitespace(
        self,
        tmp_path: Path,
        soul_content: str,
    ) -> None:
        """Property 8: get_soul_content() preserves whitespace
        
        For any SOUL.md content with various whitespace (newlines, tabs,
        trailing spaces), get_soul_content() should preserve all whitespace
        exactly as written.
        
        **Validates: Requirements 2.7**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create SOUL.md file
        (workspace_dir / "SOUL.md").write_text(soul_content, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Get SOUL content
        result = loader.get_soul_content()
        
        # Should preserve all whitespace
        assert result == soul_content, (
            f"get_soul_content() should preserve whitespace exactly"
        )

    @given(soul_content=_bootstrap_content)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_soul_content_consistent_with_load_file(
        self,
        tmp_path: Path,
        soul_content: str,
    ) -> None:
        """Property 8: get_soul_content() is consistent with load_file(SOUL)
        
        For any SOUL.md content S, get_soul_content() should return the same
        content as load_file(BootstrapFileType.SOUL).content.
        
        **Validates: Requirements 2.7**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create SOUL.md file
        (workspace_dir / "SOUL.md").write_text(soul_content, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Get content via both methods
        getter_result = loader.get_soul_content()
        load_result = loader.load_file(BootstrapFileType.SOUL)
        
        # Both should return the same content
        assert load_result is not None
        assert getter_result == load_result.content, (
            "get_soul_content() should return same content as load_file(SOUL).content"
        )


# ---------------------------------------------------------------------------
# Edge case tests for Property 8
# ---------------------------------------------------------------------------


class TestSoulPromptPositionEdgeCases:
    """Edge case tests for SOUL.md prompt position (Property 8).
    
    **Validates: Requirements 2.7**
    """

    @given(soul_content=_bootstrap_content)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_empty_soul_file_returns_empty_string(
        self,
        tmp_path: Path,
        soul_content: str,
    ) -> None:
        """Property 8 (edge case): Empty SOUL.md returns empty string
        
        For an empty SOUL.md file, get_soul_content() should return
        an empty string.
        
        **Validates: Requirements 2.7**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create empty SOUL.md file
        (workspace_dir / "SOUL.md").write_text("", encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Get SOUL content
        result = loader.get_soul_content()
        
        # Should return empty string
        assert result == "", (
            "get_soul_content() should return empty string for empty SOUL.md"
        )

    @given(soul_content=_bootstrap_content)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_soul_content_with_disabled_loader(
        self,
        tmp_path: Path,
        soul_content: str,
    ) -> None:
        """Property 8 (edge case): get_soul_content() returns empty when loader disabled
        
        For any SOUL.md content, when the loader is disabled (enabled=False),
        get_soul_content() should return an empty string.
        
        **Validates: Requirements 2.7**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create SOUL.md file
        (workspace_dir / "SOUL.md").write_text(soul_content, encoding="utf-8")
        
        # Create disabled loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
            enabled=False,
        )
        
        # Get SOUL content
        result = loader.get_soul_content()
        
        # Should return empty string when disabled
        assert result == "", (
            "get_soul_content() should return empty string when loader is disabled"
        )

    @given(soul_content=_bootstrap_content)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_soul_content_after_cache_invalidation(
        self,
        tmp_path: Path,
        soul_content: str,
    ) -> None:
        """Property 8 (edge case): get_soul_content() works after cache invalidation
        
        For any SOUL.md content, after invalidating the cache,
        get_soul_content() should still return the correct content.
        
        **Validates: Requirements 2.7**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create SOUL.md file
        (workspace_dir / "SOUL.md").write_text(soul_content, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Get SOUL content (populates cache)
        result1 = loader.get_soul_content()
        assert result1 == soul_content
        
        # Invalidate cache
        loader.invalidate_cache(BootstrapFileType.SOUL)
        
        # Get SOUL content again
        result2 = loader.get_soul_content()
        
        # Should still return correct content
        assert result2 == soul_content, (
            "get_soul_content() should work correctly after cache invalidation"
        )

    @given(
        original_soul=_bootstrap_content,
        updated_soul=_bootstrap_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_soul_content_reflects_file_updates(
        self,
        tmp_path: Path,
        original_soul: str,
        updated_soul: str,
    ) -> None:
        """Property 8 (edge case): get_soul_content() reflects file updates
        
        For any SOUL.md content, when the file is updated,
        get_soul_content() should return the updated content.
        
        **Validates: Requirements 2.7**
        """
        import time
        
        # Ensure contents are different
        assume(original_soul != updated_soul)
        
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create SOUL.md file with original content
        soul_path = workspace_dir / "SOUL.md"
        soul_path.write_text(original_soul, encoding="utf-8")
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Get original SOUL content
        result1 = loader.get_soul_content()
        assert result1 == original_soul
        
        # Wait and update file
        time.sleep(0.01)
        soul_path.write_text(updated_soul, encoding="utf-8")
        
        # Get updated SOUL content
        result2 = loader.get_soul_content()
        
        # Should return updated content
        assert result2 == updated_soul, (
            "get_soul_content() should reflect file updates"
        )

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(soul_content=_bootstrap_content)
    def test_soul_content_with_no_workspace_dir(
        self,
        tmp_path: Path,
        soul_content: str,
    ) -> None:
        """Property 8 (edge case): get_soul_content() works with no workspace_dir
        
        For any SOUL.md content in global directory, when workspace_dir is None,
        get_soul_content() should return the global content.
        
        **Validates: Requirements 2.7**
        """
        # Create only global directory
        unique_id = uuid.uuid4().hex[:8]
        global_dir = tmp_path / f"global_{unique_id}"
        global_dir.mkdir(parents=True, exist_ok=True)
        
        # Create SOUL.md in global directory
        (global_dir / "SOUL.md").write_text(soul_content, encoding="utf-8")
        
        # Create loader without workspace_dir
        loader = BootstrapLoader(
            workspace_dir=None,
            global_dir=str(global_dir),
        )
        
        # Get SOUL content
        result = loader.get_soul_content()
        
        # Should return global content
        assert result == soul_content, (
            "get_soul_content() should return global content when workspace_dir is None"
        )

    @given(soul_content=_bootstrap_content)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_oversized_soul_returns_empty_string(
        self,
        tmp_path: Path,
        soul_content: str,
    ) -> None:
        """Property 8 (edge case): Oversized SOUL.md returns empty string
        
        For a SOUL.md file exceeding the size limit (512KB),
        get_soul_content() should return an empty string.
        
        **Validates: Requirements 2.7**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create oversized SOUL.md file
        oversized_content = "# SOUL\n" + ("x" * MAX_BOOTSTRAP_FILE_SIZE)
        (workspace_dir / "SOUL.md").write_text(oversized_content, encoding="utf-8")
        
        # Verify file is oversized
        assert (workspace_dir / "SOUL.md").stat().st_size > MAX_BOOTSTRAP_FILE_SIZE
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Get SOUL content
        result = loader.get_soul_content()
        
        # Should return empty string for oversized file
        assert result == "", (
            "get_soul_content() should return empty string for oversized SOUL.md"
        )

    @given(
        global_soul=_bootstrap_content,
        excess_bytes=st.integers(min_value=1, max_value=1024),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_oversized_workspace_soul_falls_back_to_global(
        self,
        tmp_path: Path,
        global_soul: str,
        excess_bytes: int,
    ) -> None:
        """Property 8 (edge case): Oversized workspace SOUL.md falls back to global
        
        For a workspace SOUL.md exceeding the size limit but a valid global
        SOUL.md, get_soul_content() should return the global content.
        
        **Validates: Requirements 2.7**
        """
        # Create unique directories
        workspace_dir, global_dir = _create_unique_dirs(tmp_path)
        
        # Create oversized SOUL.md in workspace
        ws_header = "# Workspace SOUL (too large)\n"
        ws_header_bytes = len(ws_header.encode("utf-8"))
        ws_padding = MAX_BOOTSTRAP_FILE_SIZE - ws_header_bytes + excess_bytes
        ws_content = ws_header + ("w" * ws_padding)
        (workspace_dir / "SOUL.md").write_text(ws_content, encoding="utf-8")
        
        # Create valid SOUL.md in global
        (global_dir / "SOUL.md").write_text(global_soul, encoding="utf-8")
        
        # Verify sizes
        assert (workspace_dir / "SOUL.md").stat().st_size > MAX_BOOTSTRAP_FILE_SIZE
        assert (global_dir / "SOUL.md").stat().st_size <= MAX_BOOTSTRAP_FILE_SIZE
        
        # Create loader
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        
        # Get SOUL content
        result = loader.get_soul_content()
        
        # Should fall back to global content
        assert result == global_soul, (
            "get_soul_content() should fall back to global when workspace SOUL.md is oversized"
        )
