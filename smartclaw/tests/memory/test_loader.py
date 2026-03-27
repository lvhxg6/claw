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
    MAX_MEMORY_DIR_SIZE,
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


class TestChunkMarkdown:
    """Tests for chunk_markdown() method."""

    def test_chunk_markdown_empty_content(self, tmp_path: Path) -> None:
        """Should return empty list for empty content."""
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.chunk_markdown("", "/path/to/file.md")
        
        assert result == []

    def test_chunk_markdown_whitespace_only(self, tmp_path: Path) -> None:
        """Should return empty list for whitespace-only content."""
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.chunk_markdown("   \n\n   \t  ", "/path/to/file.md")
        
        assert result == []

    def test_chunk_markdown_single_line(self, tmp_path: Path) -> None:
        """Should create single chunk for short content."""
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        content = "# Hello World"
        
        result = loader.chunk_markdown(content, "/path/to/file.md")
        
        assert len(result) == 1
        assert result[0].text == "# Hello World"
        assert result[0].start_line == 1
        assert result[0].end_line == 1
        assert result[0].file_path == "/path/to/file.md"
        assert len(result[0].hash) == 16
        assert result[0].embedding_input == result[0].text

    def test_chunk_markdown_multiple_lines(self, tmp_path: Path) -> None:
        """Should track line numbers correctly for multi-line content."""
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        content = "# Title\n\nParagraph one.\n\nParagraph two."
        
        result = loader.chunk_markdown(content, "/path/to/file.md")
        
        assert len(result) >= 1
        # First chunk should start at line 1
        assert result[0].start_line == 1

    def test_chunk_markdown_creates_overlapping_chunks(self, tmp_path: Path) -> None:
        """Should create overlapping chunks for large content."""
        # Use small chunk size to force multiple chunks
        loader = MemoryLoader(
            workspace_dir=str(tmp_path),
            chunk_tokens=50,  # Small chunk size
            chunk_overlap=10,  # Some overlap
        )
        # Create content with many words
        words = ["word" + str(i) for i in range(100)]
        content = " ".join(words)
        
        result = loader.chunk_markdown(content, "/path/to/file.md")
        
        # Should have multiple chunks
        assert len(result) > 1
        
        # Each chunk should have valid hash
        for chunk in result:
            assert len(chunk.hash) == 16
            assert chunk.file_path == "/path/to/file.md"

    def test_chunk_markdown_hash_uniqueness(self, tmp_path: Path) -> None:
        """Should compute unique hashes for different chunks."""
        loader = MemoryLoader(
            workspace_dir=str(tmp_path),
            chunk_tokens=50,
            chunk_overlap=0,  # No overlap for distinct chunks
        )
        # Create content with distinct sections
        content = "Section A content here.\n\nSection B different content.\n\nSection C more content."
        
        result = loader.chunk_markdown(content, "/path/to/file.md")
        
        if len(result) > 1:
            # Hashes should be different for different content
            hashes = [chunk.hash for chunk in result]
            # At least some hashes should be unique
            assert len(set(hashes)) > 1 or len(result) == 1

    def test_chunk_markdown_hash_deterministic(self, tmp_path: Path) -> None:
        """Should produce same hash for same content."""
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        content = "# Test Content\n\nSome text here."
        
        result1 = loader.chunk_markdown(content, "/path/to/file.md")
        result2 = loader.chunk_markdown(content, "/path/to/file.md")
        
        assert len(result1) == len(result2)
        for c1, c2 in zip(result1, result2):
            assert c1.hash == c2.hash
            assert c1.text == c2.text

    def test_chunk_markdown_respects_chunk_tokens_config(self, tmp_path: Path) -> None:
        """Should respect chunk_tokens configuration."""
        # Create loader with very small chunk size
        loader = MemoryLoader(
            workspace_dir=str(tmp_path),
            chunk_tokens=20,  # Very small
            chunk_overlap=0,
        )
        # Create content with many words
        content = " ".join(["word"] * 100)
        
        result = loader.chunk_markdown(content, "/path/to/file.md")
        
        # Should create multiple chunks due to small chunk size
        assert len(result) > 1

    def test_chunk_markdown_respects_chunk_overlap_config(self, tmp_path: Path) -> None:
        """Should respect chunk_overlap configuration."""
        # Create loader with overlap
        loader = MemoryLoader(
            workspace_dir=str(tmp_path),
            chunk_tokens=30,
            chunk_overlap=15,  # 50% overlap
        )
        # Create content with many words
        words = ["word" + str(i) for i in range(50)]
        content = " ".join(words)
        
        result = loader.chunk_markdown(content, "/path/to/file.md")
        
        # With overlap, we should have more chunks than without
        loader_no_overlap = MemoryLoader(
            workspace_dir=str(tmp_path),
            chunk_tokens=30,
            chunk_overlap=0,
        )
        result_no_overlap = loader_no_overlap.chunk_markdown(content, "/path/to/file.md")
        
        # More chunks with overlap (due to smaller step size)
        assert len(result) >= len(result_no_overlap)

    def test_chunk_markdown_unicode_content(self, tmp_path: Path) -> None:
        """Should handle Unicode content correctly."""
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        content = "# 中文标题\n\n这是一段中文内容。\n\n日本語のテキスト。"
        
        result = loader.chunk_markdown(content, "/path/to/file.md")
        
        assert len(result) >= 1
        # Should preserve Unicode content
        full_text = " ".join(chunk.text for chunk in result)
        assert "中文" in full_text or "中文标题" in result[0].text

    def test_chunk_markdown_preserves_line_structure(self, tmp_path: Path) -> None:
        """Should preserve line structure in chunks."""
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        content = "Line 1\nLine 2\nLine 3"
        
        result = loader.chunk_markdown(content, "/path/to/file.md")
        
        assert len(result) >= 1
        # Check that newlines are preserved in the text
        chunk_text = result[0].text
        assert "Line 1" in chunk_text
        assert "Line 2" in chunk_text

    def test_chunk_markdown_embedding_input_equals_text(self, tmp_path: Path) -> None:
        """Should set embedding_input equal to text."""
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        content = "# Test\n\nSome content here."
        
        result = loader.chunk_markdown(content, "/path/to/file.md")
        
        for chunk in result:
            assert chunk.embedding_input == chunk.text

    def test_chunk_markdown_line_numbers_are_one_indexed(self, tmp_path: Path) -> None:
        """Should use 1-indexed line numbers."""
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        content = "First line\nSecond line\nThird line"
        
        result = loader.chunk_markdown(content, "/path/to/file.md")
        
        assert len(result) >= 1
        # First chunk should start at line 1, not 0
        assert result[0].start_line >= 1
        assert result[0].end_line >= result[0].start_line

    def test_chunk_markdown_large_content(self, tmp_path: Path) -> None:
        """Should handle large content efficiently."""
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        # Create large content
        lines = [f"Line {i}: " + "x" * 50 for i in range(1000)]
        content = "\n".join(lines)
        
        result = loader.chunk_markdown(content, "/path/to/file.md")
        
        # Should create multiple chunks
        assert len(result) > 1
        
        # All chunks should have valid data
        for chunk in result:
            assert chunk.text
            assert len(chunk.hash) == 16
            assert chunk.start_line >= 1
            assert chunk.end_line >= chunk.start_line


class TestLoadMemoryDir:
    """Tests for load_memory_dir() method."""

    def test_load_memory_dir_not_exists(self, tmp_path: Path) -> None:
        """Should return empty list when memory/ directory does not exist."""
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.load_memory_dir()
        
        assert result == []

    def test_load_memory_dir_empty(self, tmp_path: Path) -> None:
        """Should return empty list when memory/ directory is empty."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.load_memory_dir()
        
        assert result == []

    def test_load_memory_dir_single_file(self, tmp_path: Path) -> None:
        """Should load single .md file from memory/ directory."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        content = "# Test Memory\n\nSome content here."
        (memory_dir / "test.md").write_text(content)
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.load_memory_dir()
        
        assert len(result) == 1
        assert result[0].content == content
        assert result[0].path == str(memory_dir / "test.md")
        assert result[0].size == len(content.encode("utf-8"))
        assert result[0].mtime > 0

    def test_load_memory_dir_multiple_files(self, tmp_path: Path) -> None:
        """Should load multiple .md files from memory/ directory."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "file1.md").write_text("# File 1")
        (memory_dir / "file2.md").write_text("# File 2")
        (memory_dir / "file3.md").write_text("# File 3")
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.load_memory_dir()
        
        assert len(result) == 3
        contents = {f.content for f in result}
        assert "# File 1" in contents
        assert "# File 2" in contents
        assert "# File 3" in contents

    def test_load_memory_dir_recursive(self, tmp_path: Path) -> None:
        """Should recursively scan subdirectories for .md files."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "root.md").write_text("# Root")
        
        subdir1 = memory_dir / "subdir1"
        subdir1.mkdir()
        (subdir1 / "sub1.md").write_text("# Sub 1")
        
        subdir2 = memory_dir / "subdir2"
        subdir2.mkdir()
        (subdir2 / "sub2.md").write_text("# Sub 2")
        
        nested = subdir1 / "nested"
        nested.mkdir()
        (nested / "nested.md").write_text("# Nested")
        
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.load_memory_dir()
        
        assert len(result) == 4
        contents = {f.content for f in result}
        assert "# Root" in contents
        assert "# Sub 1" in contents
        assert "# Sub 2" in contents
        assert "# Nested" in contents

    def test_load_memory_dir_only_md_files(self, tmp_path: Path) -> None:
        """Should only load .md files, ignoring other file types."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "valid.md").write_text("# Valid")
        (memory_dir / "readme.txt").write_text("Not markdown")
        (memory_dir / "data.json").write_text('{"key": "value"}')
        (memory_dir / "script.py").write_text("print('hello')")
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.load_memory_dir()
        
        assert len(result) == 1
        assert result[0].content == "# Valid"

    def test_load_memory_dir_case_insensitive_extension(self, tmp_path: Path) -> None:
        """Should load .MD files (case-insensitive extension)."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "lower.md").write_text("# Lower")
        (memory_dir / "upper.MD").write_text("# Upper")
        (memory_dir / "mixed.Md").write_text("# Mixed")
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.load_memory_dir()
        
        assert len(result) == 3
        contents = {f.content for f in result}
        assert "# Lower" in contents
        assert "# Upper" in contents
        assert "# Mixed" in contents

    def test_load_memory_dir_disabled(self, tmp_path: Path) -> None:
        """Should return empty list when loader is disabled."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "test.md").write_text("# Test")
        loader = MemoryLoader(workspace_dir=str(tmp_path), enabled=False)
        
        result = loader.load_memory_dir()
        
        assert result == []

    def test_load_memory_dir_unicode_content(self, tmp_path: Path) -> None:
        """Should handle Unicode content correctly."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        content = "# 中文标题\n\n这是中文内容。\n\n日本語テキスト。"
        (memory_dir / "unicode.md").write_text(content, encoding="utf-8")
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.load_memory_dir()
        
        assert len(result) == 1
        assert result[0].content == content

    def test_load_memory_dir_sorted_by_path(self, tmp_path: Path) -> None:
        """Should return files sorted by path for deterministic ordering."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "z_last.md").write_text("# Z")
        (memory_dir / "a_first.md").write_text("# A")
        (memory_dir / "m_middle.md").write_text("# M")
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.load_memory_dir()
        
        assert len(result) == 3
        paths = [f.path for f in result]
        assert paths == sorted(paths)

    def test_load_memory_dir_not_a_directory(self, tmp_path: Path) -> None:
        """Should return empty list when memory is a file, not a directory."""
        # Create a file named 'memory' instead of a directory
        (tmp_path / "memory").write_text("I am a file")
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.load_memory_dir()
        
        assert result == []

    def test_load_memory_dir_empty_file(self, tmp_path: Path) -> None:
        """Should handle empty .md files."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "empty.md").write_text("")
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.load_memory_dir()
        
        assert len(result) == 1
        assert result[0].content == ""
        assert result[0].size == 0


class TestLoadMemoryDirSizeLimit:
    """Tests for memory/ directory size limit (50MB)."""

    def test_load_memory_dir_within_limit(self, tmp_path: Path) -> None:
        """Should load all files when total size is within limit."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        # Create several small files
        for i in range(10):
            (memory_dir / f"file{i}.md").write_text(f"# File {i}\n" + "x" * 1000)
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.load_memory_dir()
        
        assert len(result) == 10

    def test_load_memory_dir_exceeds_limit_stops_loading(self, tmp_path: Path) -> None:
        """Should stop loading files when 50MB limit is exceeded."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        
        # Create files that will exceed the limit
        # Each file is ~10MB, so after 5 files we exceed 50MB
        file_size = 10 * 1024 * 1024  # 10MB
        content = "x" * file_size
        
        for i in range(7):  # 7 files * 10MB = 70MB > 50MB limit
            (memory_dir / f"file{i:02d}.md").write_text(content)
        
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.load_memory_dir()
        
        # Should load only files up to 50MB limit
        total_size = sum(f.size for f in result)
        assert total_size <= MAX_MEMORY_DIR_SIZE
        # Should have loaded 5 files (50MB) and skipped the rest
        assert len(result) == 5

    def test_load_memory_dir_size_limit_boundary(self, tmp_path: Path) -> None:
        """Should handle files at the exact boundary of the limit."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        
        # Create files that exactly fill the limit
        file_size = MAX_MEMORY_DIR_SIZE // 2
        content = "x" * file_size
        
        (memory_dir / "file1.md").write_text(content)
        (memory_dir / "file2.md").write_text(content)
        (memory_dir / "file3.md").write_text("# Small file")  # This should be skipped
        
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.load_memory_dir()
        
        # Should load exactly 2 files (filling the limit)
        assert len(result) == 2
        total_size = sum(f.size for f in result)
        assert total_size <= MAX_MEMORY_DIR_SIZE

    def test_load_memory_dir_single_large_file_exceeds_limit(self, tmp_path: Path) -> None:
        """Should skip file if it alone exceeds the limit."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        
        # Create a file larger than 50MB
        large_content = "x" * (MAX_MEMORY_DIR_SIZE + 1024)
        (memory_dir / "huge.md").write_text(large_content)
        
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.load_memory_dir()
        
        # Should skip the huge file
        assert len(result) == 0

    def test_load_memory_dir_mixed_sizes_respects_limit(self, tmp_path: Path) -> None:
        """Should load files in order until limit is reached."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        
        # Create files with different sizes
        # Files are sorted by path, so a_small loads first
        # a_small (1KB) + b_medium (~50MB - 2KB) = ~50MB - 1KB, leaving room for nothing more
        small_size = 1000
        medium_size = MAX_MEMORY_DIR_SIZE - small_size - 100  # Leave 100 bytes margin
        extra_size = 200  # This will exceed the limit
        
        (memory_dir / "a_small.md").write_text("x" * small_size)
        (memory_dir / "b_medium.md").write_text("x" * medium_size)
        (memory_dir / "c_extra.md").write_text("x" * extra_size)  # Should be skipped
        
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        result = loader.load_memory_dir()
        
        # Should load a_small and b_medium, skip c_extra
        assert len(result) == 2
        paths = [f.path for f in result]
        assert any("a_small.md" in p for p in paths)
        assert any("b_medium.md" in p for p in paths)
        # Verify c_extra was skipped
        assert not any("c_extra.md" in p for p in paths)
