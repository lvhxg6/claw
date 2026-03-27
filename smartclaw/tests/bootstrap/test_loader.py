"""Unit tests for BootstrapLoader.

Tests the BootstrapLoader class for loading SOUL.md, USER.md, and TOOLS.md
bootstrap files from workspace and global directories.
"""

import pytest
from pathlib import Path

from smartclaw.bootstrap.loader import (
    BootstrapFile,
    BootstrapFileType,
    BootstrapLoader,
    MAX_BOOTSTRAP_FILE_SIZE,
)


class TestBootstrapFileType:
    """Tests for BootstrapFileType enum."""

    def test_soul_value(self):
        """SOUL type should have value 'SOUL.md'."""
        assert BootstrapFileType.SOUL.value == "SOUL.md"

    def test_user_value(self):
        """USER type should have value 'USER.md'."""
        assert BootstrapFileType.USER.value == "USER.md"

    def test_tools_value(self):
        """TOOLS type should have value 'TOOLS.md'."""
        assert BootstrapFileType.TOOLS.value == "TOOLS.md"

    def test_all_types_count(self):
        """Should have exactly 3 bootstrap file types."""
        assert len(BootstrapFileType) == 3


class TestBootstrapFile:
    """Tests for BootstrapFile dataclass."""

    def test_create_bootstrap_file(self):
        """Should create BootstrapFile with all fields."""
        bf = BootstrapFile(
            file_type=BootstrapFileType.SOUL,
            path="/test/SOUL.md",
            source="workspace",
            content="# Soul Content",
            mtime=1234567890.0,
            size=14,
        )
        assert bf.file_type == BootstrapFileType.SOUL
        assert bf.path == "/test/SOUL.md"
        assert bf.source == "workspace"
        assert bf.content == "# Soul Content"
        assert bf.mtime == 1234567890.0
        assert bf.size == 14


class TestBootstrapLoaderInit:
    """Tests for BootstrapLoader initialization."""

    def test_init_with_workspace_dir(self, tmp_path: Path):
        """Should initialize with workspace directory."""
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        assert loader.workspace_dir == tmp_path
        assert loader.enabled is True

    def test_init_without_workspace_dir(self):
        """Should initialize without workspace directory."""
        loader = BootstrapLoader()
        assert loader.workspace_dir is None
        assert loader.global_dir == Path.home() / ".smartclaw"

    def test_init_with_custom_global_dir(self, tmp_path: Path):
        """Should initialize with custom global directory."""
        global_dir = tmp_path / "custom_global"
        loader = BootstrapLoader(global_dir=str(global_dir))
        assert loader.global_dir == global_dir

    def test_init_disabled(self, tmp_path: Path):
        """Should initialize in disabled state."""
        loader = BootstrapLoader(workspace_dir=str(tmp_path), enabled=False)
        assert loader.enabled is False

    def test_init_expands_tilde(self):
        """Should expand ~ in paths."""
        loader = BootstrapLoader(global_dir="~/.smartclaw")
        assert "~" not in str(loader.global_dir)
        assert loader.global_dir == Path.home() / ".smartclaw"


class TestBootstrapLoaderLoadFile:
    """Tests for BootstrapLoader.load_file() method."""

    def test_load_file_not_exists(self, tmp_path: Path):
        """Should return None when file does not exist."""
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        result = loader.load_file(BootstrapFileType.SOUL)
        assert result is None

    def test_load_file_from_workspace(self, tmp_path: Path):
        """Should load file from workspace directory."""
        soul_content = "# Agent Soul\n\nI am helpful."
        (tmp_path / "SOUL.md").write_text(soul_content)
        
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        result = loader.load_file(BootstrapFileType.SOUL)
        
        assert result is not None
        assert result.file_type == BootstrapFileType.SOUL
        assert result.content == soul_content
        assert result.source == "workspace"
        assert result.size == len(soul_content.encode("utf-8"))

    def test_load_file_from_global(self, tmp_path: Path):
        """Should load file from global directory when not in workspace."""
        global_dir = tmp_path / "global"
        global_dir.mkdir()
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        
        user_content = "# User Info\n\nName: Test User"
        (global_dir / "USER.md").write_text(user_content)
        
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        result = loader.load_file(BootstrapFileType.USER)
        
        assert result is not None
        assert result.file_type == BootstrapFileType.USER
        assert result.content == user_content
        assert result.source == "global"

    def test_load_file_workspace_priority(self, tmp_path: Path):
        """Workspace file should take priority over global file.
        
        Validates: Requirements 2.1, 2.3
        """
        global_dir = tmp_path / "global"
        global_dir.mkdir()
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        
        # Create both workspace and global files
        (workspace_dir / "TOOLS.md").write_text("# Workspace Tools")
        (global_dir / "TOOLS.md").write_text("# Global Tools")
        
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        result = loader.load_file(BootstrapFileType.TOOLS)
        
        assert result is not None
        assert result.content == "# Workspace Tools"
        assert result.source == "workspace"

    def test_load_file_disabled(self, tmp_path: Path):
        """Should return None when loader is disabled.
        
        Validates: Requirements 2.9
        """
        (tmp_path / "SOUL.md").write_text("# Soul")
        
        loader = BootstrapLoader(workspace_dir=str(tmp_path), enabled=False)
        result = loader.load_file(BootstrapFileType.SOUL)
        
        assert result is None

    def test_load_file_too_large(self, tmp_path: Path):
        """Should reject file exceeding size limit.
        
        Validates: Requirements 2.4
        """
        # Create a file larger than 512KB
        large_content = "x" * (MAX_BOOTSTRAP_FILE_SIZE + 1)
        (tmp_path / "SOUL.md").write_text(large_content)
        
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        result = loader.load_file(BootstrapFileType.SOUL)
        
        assert result is None

    def test_load_file_exactly_at_limit(self, tmp_path: Path):
        """Should accept file exactly at size limit."""
        # Create a file exactly at 512KB
        content = "x" * MAX_BOOTSTRAP_FILE_SIZE
        (tmp_path / "SOUL.md").write_text(content)
        
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        result = loader.load_file(BootstrapFileType.SOUL)
        
        assert result is not None
        assert len(result.content) == MAX_BOOTSTRAP_FILE_SIZE

    def test_load_file_binary_content(self, tmp_path: Path):
        """Should reject file with binary content (null bytes).
        
        Validates: Requirements 2.9
        """
        # Create a file with null bytes
        (tmp_path / "SOUL.md").write_bytes(b"# Soul\x00Binary")
        
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        result = loader.load_file(BootstrapFileType.SOUL)
        
        assert result is None

    def test_load_file_permission_denied(self, tmp_path: Path):
        """Should handle permission denied gracefully."""
        soul_file = tmp_path / "SOUL.md"
        soul_file.write_text("# Soul")
        soul_file.chmod(0o000)
        
        try:
            loader = BootstrapLoader(workspace_dir=str(tmp_path))
            result = loader.load_file(BootstrapFileType.SOUL)
            # Should return None without raising exception
            assert result is None
        finally:
            # Restore permissions for cleanup
            soul_file.chmod(0o644)

    def test_load_file_unicode_content(self, tmp_path: Path):
        """Should handle Unicode content correctly."""
        unicode_content = "# 代理人格\n\n我是一个有帮助的助手。🤖"
        (tmp_path / "SOUL.md").write_text(unicode_content, encoding="utf-8")
        
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        result = loader.load_file(BootstrapFileType.SOUL)
        
        assert result is not None
        assert result.content == unicode_content


class TestBootstrapLoaderCache:
    """Tests for BootstrapLoader caching mechanism."""

    def test_cache_hit(self, tmp_path: Path):
        """Should return cached content on second load."""
        (tmp_path / "SOUL.md").write_text("# Soul")
        
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        
        # First load
        result1 = loader.load_file(BootstrapFileType.SOUL)
        # Second load (should hit cache)
        result2 = loader.load_file(BootstrapFileType.SOUL)
        
        assert result1 is not None
        assert result2 is not None
        assert result1.content == result2.content
        assert result1.mtime == result2.mtime

    def test_cache_invalidation_on_mtime_change(self, tmp_path: Path):
        """Should reload file when mtime changes.
        
        Validates: Requirements 2.5
        """
        soul_file = tmp_path / "SOUL.md"
        soul_file.write_text("# Original Soul")
        
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        
        # First load
        result1 = loader.load_file(BootstrapFileType.SOUL)
        assert result1 is not None
        assert result1.content == "# Original Soul"
        
        # Modify file (this changes mtime)
        import time
        time.sleep(0.01)  # Ensure mtime changes
        soul_file.write_text("# Updated Soul")
        
        # Second load (should detect mtime change and reload)
        result2 = loader.load_file(BootstrapFileType.SOUL)
        assert result2 is not None
        assert result2.content == "# Updated Soul"

    def test_invalidate_cache_specific_type(self, tmp_path: Path):
        """Should invalidate cache for specific file type."""
        (tmp_path / "SOUL.md").write_text("# Soul")
        (tmp_path / "USER.md").write_text("# User")
        
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        
        # Load both files
        loader.load_file(BootstrapFileType.SOUL)
        loader.load_file(BootstrapFileType.USER)
        
        # Invalidate only SOUL cache
        loader.invalidate_cache(BootstrapFileType.SOUL)
        
        # SOUL should be reloaded, USER should still be cached
        assert BootstrapFileType.SOUL not in loader._cache
        assert BootstrapFileType.USER in loader._cache

    def test_invalidate_cache_all(self, tmp_path: Path):
        """Should invalidate all cache entries."""
        (tmp_path / "SOUL.md").write_text("# Soul")
        (tmp_path / "USER.md").write_text("# User")
        
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        
        # Load both files
        loader.load_file(BootstrapFileType.SOUL)
        loader.load_file(BootstrapFileType.USER)
        
        # Invalidate all cache
        loader.invalidate_cache()
        
        assert len(loader._cache) == 0


class TestBootstrapLoaderLoadAll:
    """Tests for BootstrapLoader.load_all() method."""

    def test_load_all_empty(self, tmp_path: Path):
        """Should return empty dict when no files exist."""
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        result = loader.load_all()
        assert result == {}

    def test_load_all_single_file(self, tmp_path: Path):
        """Should load single available file."""
        (tmp_path / "SOUL.md").write_text("# Soul")
        
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        result = loader.load_all()
        
        assert len(result) == 1
        assert BootstrapFileType.SOUL in result
        assert result[BootstrapFileType.SOUL].content == "# Soul"

    def test_load_all_multiple_files(self, tmp_path: Path):
        """Should load all available files."""
        (tmp_path / "SOUL.md").write_text("# Soul")
        (tmp_path / "USER.md").write_text("# User")
        (tmp_path / "TOOLS.md").write_text("# Tools")
        
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        result = loader.load_all()
        
        assert len(result) == 3
        assert BootstrapFileType.SOUL in result
        assert BootstrapFileType.USER in result
        assert BootstrapFileType.TOOLS in result

    def test_load_all_disabled(self, tmp_path: Path):
        """Should return empty dict when disabled."""
        (tmp_path / "SOUL.md").write_text("# Soul")
        
        loader = BootstrapLoader(workspace_dir=str(tmp_path), enabled=False)
        result = loader.load_all()
        
        assert result == {}

    def test_load_all_mixed_sources(self, tmp_path: Path):
        """Should load files from both workspace and global."""
        global_dir = tmp_path / "global"
        global_dir.mkdir()
        workspace_dir = tmp_path / "workspace"
        workspace_dir.mkdir()
        
        # SOUL in workspace, USER in global
        (workspace_dir / "SOUL.md").write_text("# Workspace Soul")
        (global_dir / "USER.md").write_text("# Global User")
        
        loader = BootstrapLoader(
            workspace_dir=str(workspace_dir),
            global_dir=str(global_dir),
        )
        result = loader.load_all()
        
        assert len(result) == 2
        assert result[BootstrapFileType.SOUL].source == "workspace"
        assert result[BootstrapFileType.USER].source == "global"


class TestBootstrapLoaderContentGetters:
    """Tests for content getter methods."""

    def test_get_soul_content(self, tmp_path: Path):
        """Should return SOUL.md content."""
        (tmp_path / "SOUL.md").write_text("# Soul Content")
        
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        content = loader.get_soul_content()
        
        assert content == "# Soul Content"

    def test_get_soul_content_not_found(self, tmp_path: Path):
        """Should return empty string when SOUL.md not found."""
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        content = loader.get_soul_content()
        
        assert content == ""

    def test_get_user_content(self, tmp_path: Path):
        """Should return USER.md content."""
        (tmp_path / "USER.md").write_text("# User Content")
        
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        content = loader.get_user_content()
        
        assert content == "# User Content"

    def test_get_user_content_not_found(self, tmp_path: Path):
        """Should return empty string when USER.md not found."""
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        content = loader.get_user_content()
        
        assert content == ""

    def test_get_tools_content(self, tmp_path: Path):
        """Should return TOOLS.md content."""
        (tmp_path / "TOOLS.md").write_text("# Tools Content")
        
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        content = loader.get_tools_content()
        
        assert content == "# Tools Content"

    def test_get_tools_content_not_found(self, tmp_path: Path):
        """Should return empty string when TOOLS.md not found."""
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        content = loader.get_tools_content()
        
        assert content == ""


class TestBootstrapLoaderEdgeCases:
    """Tests for edge cases and error handling."""

    def test_workspace_dir_not_exists(self, tmp_path: Path):
        """Should handle non-existent workspace directory."""
        non_existent = tmp_path / "non_existent"
        
        loader = BootstrapLoader(workspace_dir=str(non_existent))
        result = loader.load_file(BootstrapFileType.SOUL)
        
        assert result is None

    def test_global_dir_not_exists(self, tmp_path: Path):
        """Should handle non-existent global directory."""
        non_existent = tmp_path / "non_existent_global"
        
        loader = BootstrapLoader(global_dir=str(non_existent))
        result = loader.load_file(BootstrapFileType.SOUL)
        
        assert result is None

    def test_path_is_directory_not_file(self, tmp_path: Path):
        """Should handle case where path is a directory."""
        # Create a directory with the same name as the file
        (tmp_path / "SOUL.md").mkdir()
        
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        result = loader.load_file(BootstrapFileType.SOUL)
        
        assert result is None

    def test_empty_file(self, tmp_path: Path):
        """Should handle empty file."""
        (tmp_path / "SOUL.md").write_text("")
        
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        result = loader.load_file(BootstrapFileType.SOUL)
        
        assert result is not None
        assert result.content == ""
        assert result.size == 0

    def test_file_with_only_whitespace(self, tmp_path: Path):
        """Should handle file with only whitespace."""
        (tmp_path / "SOUL.md").write_text("   \n\t\n   ")
        
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        result = loader.load_file(BootstrapFileType.SOUL)
        
        assert result is not None
        assert result.content == "   \n\t\n   "

    def test_cache_invalidation_on_file_deletion(self, tmp_path: Path):
        """Should handle file deletion after caching."""
        soul_file = tmp_path / "SOUL.md"
        soul_file.write_text("# Soul")
        
        loader = BootstrapLoader(workspace_dir=str(tmp_path))
        
        # First load (caches the file)
        result1 = loader.load_file(BootstrapFileType.SOUL)
        assert result1 is not None
        
        # Delete the file
        soul_file.unlink()
        
        # Second load (should detect deletion and return None)
        result2 = loader.load_file(BootstrapFileType.SOUL)
        assert result2 is None
