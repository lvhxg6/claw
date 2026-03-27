"""Unit tests for MemoryLoader.

Tests for MEMORY.md loading functionality including:
- Case-insensitive file name lookup
- File size limits and truncation
- Error handling for missing/inaccessible files
"""

import pytest
from pathlib import Path

from smartclaw.memory.loader import (
    MemoryLoader,
    MemoryChunk,
    MemoryFile,
    MAX_MEMORY_FILE_SIZE,
)


class TestMemoryLoaderInit:
    """Tests for MemoryLoader initialization."""

    def test_init_with_defaults(self, tmp_path: Path) -> None:
        """Should initialize with default values."""
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        assert loader.workspace_dir == tmp_path
        assert loader.enabled is True
        assert loader._chunk_tokens == 512
        assert loader._chunk_overlap == 64

    def test_init_with_custom_values(self, tmp_path: Path) -> None:
        """Should initialize with custom values."""
        loader = MemoryLoader(
            workspace_dir=str(tmp_path),
            chunk_tokens=256,
            chunk_overlap=32,
            enabled=False,
        )
        
        assert loader._chunk_tokens == 256
        assert loader._chunk_overlap == 32
        assert loader.enabled is False

    def test_init_expands_user_path(self) -> None:
        """Should expand ~ in workspace path."""
        loader = MemoryLoader(workspace_dir="~/test_workspace")
        
        assert "~" not in str(loader.workspace_dir)
        assert loader.workspace_dir.is_absolute()


class TestLoadMemoryMd:
    """Tests for load_memory_md() method."""

    def test_load_memory_md_not_exists(self, tmp_path: Path) -> None:
        """Should return None when MEMORY.md does not exist."""
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.load_memory_md()
        
        assert result is None

    def test_load_memory_md_uppercase(self, tmp_path: Path) -> None:
        """Should load uppercase MEMORY.md file."""
        content = "# My Memory\n\n- Fact 1\n- Fact 2"
        (tmp_path / "MEMORY.md").write_text(content)
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.load_memory_md()
        
        assert result == content

    def test_load_memory_md_lowercase(self, tmp_path: Path) -> None:
        """Should load lowercase memory.md file."""
        content = "# My Memory\n\n- Fact 1"
        (tmp_path / "memory.md").write_text(content)
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.load_memory_md()
        
        assert result == content

    def test_load_memory_md_uppercase_priority(self, tmp_path: Path) -> None:
        """Should prioritize uppercase MEMORY.md over lowercase.
        
        Note: On case-insensitive file systems (like macOS), MEMORY.md and
        memory.md are the same file. This test verifies that when both exist
        (on case-sensitive systems) or when only one exists, the loader
        correctly identifies and loads the file.
        """
        # Create uppercase file
        uppercase_content = "# Uppercase Memory"
        uppercase_path = tmp_path / "MEMORY.md"
        uppercase_path.write_text(uppercase_content)
        
        # Check if file system is case-sensitive by trying to create lowercase
        lowercase_path = tmp_path / "memory.md"
        lowercase_content = "# Lowercase Memory"
        
        # Try to create lowercase file
        lowercase_path.write_text(lowercase_content)
        
        # Check if both files exist (case-sensitive) or just one (case-insensitive)
        files = list(tmp_path.glob("*"))
        memory_files = [f for f in files if f.name.lower() == "memory.md"]
        
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        result = loader.load_memory_md()
        
        if len(memory_files) == 2:
            # Case-sensitive file system: should prefer uppercase
            assert result == uppercase_content
        else:
            # Case-insensitive file system: only one file exists
            # The last write wins, so it will be lowercase content
            # But the loader should still work correctly
            assert result is not None
            assert "Memory" in result

    def test_load_memory_md_case_insensitive(self, tmp_path: Path) -> None:
        """Should find file with mixed case (e.g., Memory.md)."""
        content = "# Mixed Case Memory"
        (tmp_path / "Memory.md").write_text(content)
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.load_memory_md()
        
        assert result == content

    def test_load_memory_md_disabled(self, tmp_path: Path) -> None:
        """Should return None when loader is disabled."""
        (tmp_path / "MEMORY.md").write_text("# Memory")
        loader = MemoryLoader(workspace_dir=str(tmp_path), enabled=False)
        
        result = loader.load_memory_md()
        
        assert result is None

    def test_load_memory_md_empty_file(self, tmp_path: Path) -> None:
        """Should return empty string for empty file."""
        (tmp_path / "MEMORY.md").write_text("")
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.load_memory_md()
        
        assert result == ""

    def test_load_memory_md_unicode_content(self, tmp_path: Path) -> None:
        """Should handle Unicode content correctly."""
        content = "# 记忆文件\n\n- 中文内容\n- 日本語\n- 한국어"
        (tmp_path / "MEMORY.md").write_text(content, encoding="utf-8")
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.load_memory_md()
        
        assert result == content

    def test_load_memory_md_workspace_not_exists(self) -> None:
        """Should return None when workspace does not exist."""
        loader = MemoryLoader(workspace_dir="/nonexistent/path/12345")
        
        result = loader.load_memory_md()
        
        assert result is None


class TestLoadMemoryMdSizeLimit:
    """Tests for file size limit and truncation."""

    def test_load_memory_md_within_limit(self, tmp_path: Path) -> None:
        """Should load file within size limit completely."""
        content = "# Memory\n" + "Line\n" * 1000
        (tmp_path / "MEMORY.md").write_text(content)
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.load_memory_md()
        
        assert result == content

    def test_load_memory_md_exceeds_limit_truncated(self, tmp_path: Path) -> None:
        """Should truncate file exceeding 2MB limit."""
        # Create content larger than 2MB
        line = "This is a test line with some content.\n"
        num_lines = (MAX_MEMORY_FILE_SIZE // len(line)) + 1000
        content = line * num_lines
        (tmp_path / "MEMORY.md").write_text(content)
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.load_memory_md()
        
        assert result is not None
        assert len(result) <= MAX_MEMORY_FILE_SIZE
        # Should end at a line boundary
        assert result.endswith("\n")

    def test_load_memory_md_truncate_at_line_boundary(self, tmp_path: Path) -> None:
        """Should truncate at line boundary to maintain valid Markdown."""
        # Create content that would be cut mid-line
        line = "A" * 100 + "\n"
        num_lines = (MAX_MEMORY_FILE_SIZE // len(line)) + 100
        content = line * num_lines
        (tmp_path / "MEMORY.md").write_text(content)
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.load_memory_md()
        
        assert result is not None
        # Should not have partial lines
        assert result.endswith("\n")
        # All lines should be complete
        lines = result.split("\n")
        for line in lines[:-1]:  # Last element is empty after split
            assert len(line) == 100 or line == ""


class TestComputeHash:
    """Tests for compute_hash() method."""

    def test_compute_hash_returns_16_chars(self, tmp_path: Path) -> None:
        """Should return 16 character hash."""
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.compute_hash("test content")
        
        assert len(result) == 16
        assert all(c in "0123456789abcdef" for c in result)

    def test_compute_hash_deterministic(self, tmp_path: Path) -> None:
        """Should return same hash for same content."""
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        content = "test content"
        
        hash1 = loader.compute_hash(content)
        hash2 = loader.compute_hash(content)
        
        assert hash1 == hash2

    def test_compute_hash_different_for_different_content(self, tmp_path: Path) -> None:
        """Should return different hash for different content."""
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        hash1 = loader.compute_hash("content 1")
        hash2 = loader.compute_hash("content 2")
        
        assert hash1 != hash2

    def test_compute_hash_empty_string(self, tmp_path: Path) -> None:
        """Should handle empty string."""
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.compute_hash("")
        
        assert len(result) == 16

    def test_compute_hash_unicode(self, tmp_path: Path) -> None:
        """Should handle Unicode content."""
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.compute_hash("中文内容 日本語 한국어")
        
        assert len(result) == 16


class TestMemoryChunkDataclass:
    """Tests for MemoryChunk dataclass."""

    def test_memory_chunk_creation(self) -> None:
        """Should create MemoryChunk with all fields."""
        chunk = MemoryChunk(
            file_path="/path/to/file.md",
            start_line=1,
            end_line=10,
            text="chunk content",
            hash="abc123def456789",
            embedding_input="chunk content for embedding",
        )
        
        assert chunk.file_path == "/path/to/file.md"
        assert chunk.start_line == 1
        assert chunk.end_line == 10
        assert chunk.text == "chunk content"
        assert chunk.hash == "abc123def456789"
        assert chunk.embedding_input == "chunk content for embedding"


class TestMemoryFileDataclass:
    """Tests for MemoryFile dataclass."""

    def test_memory_file_creation(self) -> None:
        """Should create MemoryFile with all fields."""
        chunks = [
            MemoryChunk(
                file_path="/path/to/file.md",
                start_line=1,
                end_line=5,
                text="chunk 1",
                hash="hash1",
                embedding_input="chunk 1",
            )
        ]
        memory_file = MemoryFile(
            path="/path/to/file.md",
            mtime=1234567890.0,
            size=1024,
            content="file content",
            chunks=chunks,
        )
        
        assert memory_file.path == "/path/to/file.md"
        assert memory_file.mtime == 1234567890.0
        assert memory_file.size == 1024
        assert memory_file.content == "file content"
        assert len(memory_file.chunks) == 1

    def test_memory_file_default_chunks(self) -> None:
        """Should have empty chunks list by default."""
        memory_file = MemoryFile(
            path="/path/to/file.md",
            mtime=1234567890.0,
            size=1024,
            content="file content",
        )
        
        assert memory_file.chunks == []
