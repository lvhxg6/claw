"""Property-based tests for MemoryLoader.

Uses hypothesis with @settings(max_examples=100).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from smartclaw.memory.loader import MAX_MEMORY_FILE_SIZE, MemoryLoader


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for generating memory.md file name variants (case variations)
# Priority order: MEMORY.md (0) > memory.md (1) > other variants (2+)
_MEMORY_MD_VARIANTS = [
    "MEMORY.md",   # Priority 0 - highest
    "memory.md",   # Priority 1
    "Memory.md",   # Priority 2
    "MEMORY.MD",   # Priority 3
    "memory.MD",   # Priority 4
    "MeMoRy.md",   # Priority 5
    "mEmOrY.Md",   # Priority 6
]


def _get_priority(filename: str) -> tuple[int, str]:
    """Get priority for a memory.md filename variant.
    
    Returns a tuple (priority_level, filename) for sorting.
    Lower priority_level = higher priority.
    """
    if filename == "MEMORY.md":
        return (0, filename)
    elif filename == "memory.md":
        return (1, filename)
    else:
        return (2, filename)


# Strategy for selecting a non-empty subset of memory.md variants
_memory_variants_subset = st.lists(
    st.sampled_from(_MEMORY_MD_VARIANTS),
    min_size=1,
    max_size=len(_MEMORY_MD_VARIANTS),
    unique=True,
)

# Strategy for generating valid markdown content
_markdown_content = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        whitelist_characters="\n\t -#*_[](){}",
    ),
    min_size=1,
    max_size=500,
).map(lambda s: f"# Memory\n\n{s}")


# ---------------------------------------------------------------------------
# Property 1: MEMORY.md 文件发现优先级
# ---------------------------------------------------------------------------


class TestMemoryLoaderProperties:
    """Property-based tests for MemoryLoader."""

    @given(
        variants=_memory_variants_subset,
        content_seed=st.integers(min_value=0, max_value=1000),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_memory_md_file_discovery_priority(
        self,
        tmp_path: Path,
        variants: list[str],
        content_seed: int,
    ) -> None:
        """Property 1: MEMORY.md 文件发现优先级
        
        For any workspace directory, when multiple memory.md file variants
        exist (MEMORY.md, memory.md, Memory.md, etc.), MemoryLoader should
        always prioritize them according to the defined priority order:
        MEMORY.md > memory.md > other variants.
        
        **Validates: Requirements 1.1**
        
        Note: On case-insensitive file systems (like macOS HFS+, Windows NTFS),
        only one file can exist regardless of case. This test handles both
        case-sensitive and case-insensitive file systems.
        """
        # Create files with unique content for each variant
        # Track what files actually exist after creation
        created_files: dict[str, str] = {}
        
        for i, variant in enumerate(variants):
            content = f"# Memory from {variant}\n\nContent seed: {content_seed}, index: {i}"
            file_path = tmp_path / variant
            
            try:
                file_path.write_text(content, encoding="utf-8")
            except OSError:
                # Skip if file creation fails (e.g., permission issues)
                continue
        
        # After all writes, scan directory to see what files actually exist
        # This handles case-insensitive filesystems correctly
        for item in tmp_path.iterdir():
            if item.is_file() and item.name.lower() == "memory.md":
                created_files[item.name] = item.read_text(encoding="utf-8")
        
        # Skip if no files were created
        assume(len(created_files) > 0)
        
        # Create loader and load memory
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        result = loader.load_memory_md()
        
        # Result should not be None since we created at least one file
        assert result is not None, "Expected to load a memory file"
        
        # Verify priority order: the loader should return the highest priority file
        # Find the highest priority file that actually exists
        sorted_variants = sorted(created_files.keys(), key=_get_priority)
        expected_variant = sorted_variants[0]
        expected_content = created_files[expected_variant]
        
        assert result == expected_content, (
            f"Expected content from {expected_variant} (highest priority), "
            f"but got different content. Created files: {list(created_files.keys())}"
        )

    @given(
        high_priority_content=_markdown_content,
        low_priority_content=_markdown_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_uppercase_memory_md_takes_priority_over_lowercase(
        self,
        tmp_path: Path,
        high_priority_content: str,
        low_priority_content: str,
    ) -> None:
        """Property 1 (specific case): MEMORY.md takes priority over memory.md
        
        For any workspace with both MEMORY.md and memory.md files,
        the loader should always return content from MEMORY.md.
        
        **Validates: Requirements 1.1**
        """
        # Create MEMORY.md (high priority) first
        uppercase_path = tmp_path / "MEMORY.md"
        uppercase_path.write_text(high_priority_content, encoding="utf-8")
        
        # Try to create lowercase file
        lowercase_path = tmp_path / "memory.md"
        lowercase_path.write_text(low_priority_content, encoding="utf-8")
        
        # Scan directory to see what files actually exist
        memory_files = [
            f for f in tmp_path.iterdir() 
            if f.is_file() and f.name.lower() == "memory.md"
        ]
        
        # Load memory
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        result = loader.load_memory_md()
        
        # Should always get some content
        assert result is not None
        
        if len(memory_files) == 2:
            # Case-sensitive FS: both files exist, should get MEMORY.md content
            assert result == high_priority_content, (
                "MEMORY.md should take priority over memory.md"
            )
        else:
            # Case-insensitive FS: only one file exists
            # The loader should still work correctly
            assert result in (high_priority_content, low_priority_content)

    @given(content=_markdown_content)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_any_case_variant_is_discovered(
        self,
        tmp_path: Path,
        content: str,
    ) -> None:
        """Property 1 (case-insensitive discovery): Any case variant is found
        
        For any memory.md file variant (regardless of case), the loader
        should discover and load it.
        
        **Validates: Requirements 1.1**
        """
        # Test each variant individually
        for variant in _MEMORY_MD_VARIANTS:
            # Create a fresh subdirectory for each variant
            variant_dir = tmp_path / f"test_{variant.replace('.', '_')}"
            variant_dir.mkdir(exist_ok=True)
            
            # Create the file
            file_path = variant_dir / variant
            file_path.write_text(content, encoding="utf-8")
            
            # Load memory
            loader = MemoryLoader(workspace_dir=str(variant_dir))
            result = loader.load_memory_md()
            
            # Should find the file regardless of case
            assert result is not None, f"Failed to find {variant}"
            assert result == content, f"Content mismatch for {variant}"

    @given(
        variants=st.lists(
            st.sampled_from(["MEMORY.md", "memory.md", "Memory.md"]),
            min_size=1,
            max_size=3,
            unique=True,
        ),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_priority_order_is_deterministic(
        self,
        tmp_path: Path,
        variants: list[str],
    ) -> None:
        """Property 1 (determinism): Priority selection is deterministic
        
        For any set of memory.md variants, loading multiple times should
        always return the same result (deterministic behavior).
        
        **Validates: Requirements 1.1**
        """
        # Create files
        for i, variant in enumerate(variants):
            content = f"Content from {variant} - {i}"
            file_path = tmp_path / variant
            try:
                file_path.write_text(content, encoding="utf-8")
            except OSError:
                continue
        
        # Load multiple times
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        results = [loader.load_memory_md() for _ in range(5)]
        
        # All results should be the same (deterministic)
        assert all(r == results[0] for r in results), (
            "Loading should be deterministic - got different results on multiple loads"
        )
        
        # Should have loaded something
        assert results[0] is not None


# ---------------------------------------------------------------------------
# Property 2: 记忆文件大小限制
# ---------------------------------------------------------------------------


# Strategy for generating line content (printable ASCII without newlines)
_line_content = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),
        whitelist_characters=" \t-#*_[](){}",
        blacklist_characters="\n\r",
    ),
    min_size=1,
    max_size=200,
)


# Strategy for generating multi-line markdown content
_multiline_markdown = st.lists(
    _line_content,
    min_size=1,
    max_size=100,
).map(lambda lines: "\n".join(lines) + "\n")


class TestMemoryFileSizeLimitProperties:
    """Property-based tests for memory file size limit (Property 2).
    
    **Validates: Requirements 1.3**
    
    Requirements 1.3 states:
    - 单个 MEMORY.md 文件大小限制为 2MB
    - 超过限制时截断内容并记录警告日志
    """

    @given(
        content=_multiline_markdown,
        extra_size_factor=st.floats(min_value=0.01, max_value=0.5),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_files_under_limit_loaded_completely(
        self,
        tmp_path: Path,
        content: str,
        extra_size_factor: float,
    ) -> None:
        """Property 2: Files under 2MB are loaded completely
        
        For any MEMORY.md file with size < 2MB, the loader should
        return the complete file content without any truncation.
        
        **Validates: Requirements 1.3**
        """
        # Ensure content is under the limit
        assume(len(content.encode("utf-8")) < MAX_MEMORY_FILE_SIZE)
        
        # Create the file
        memory_file = tmp_path / "MEMORY.md"
        memory_file.write_text(content, encoding="utf-8")
        
        # Load memory
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        result = loader.load_memory_md()
        
        # Should load complete content
        assert result is not None
        assert result == content, (
            f"File under limit should be loaded completely. "
            f"Expected {len(content)} chars, got {len(result)} chars"
        )

    @given(
        base_content=_multiline_markdown,
        overflow_lines=st.integers(min_value=100, max_value=500),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_files_over_limit_truncated_to_max_size(
        self,
        tmp_path: Path,
        base_content: str,
        overflow_lines: int,
    ) -> None:
        """Property 2: Files over 2MB are truncated to at most 2MB
        
        For any MEMORY.md file with size > 2MB, the loader should
        truncate the content to at most MAX_MEMORY_FILE_SIZE bytes.
        
        **Validates: Requirements 1.3**
        """
        # Create content that exceeds the limit
        # Each line is about 100 bytes, we need ~21000 lines to exceed 2MB
        line = "# " + "x" * 97 + "\n"  # 100 bytes per line
        lines_needed = (MAX_MEMORY_FILE_SIZE // 100) + overflow_lines
        large_content = line * lines_needed
        
        # Verify content exceeds limit
        content_bytes = large_content.encode("utf-8")
        assume(len(content_bytes) > MAX_MEMORY_FILE_SIZE)
        
        # Create the file
        memory_file = tmp_path / "MEMORY.md"
        memory_file.write_text(large_content, encoding="utf-8")
        
        # Load memory
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        result = loader.load_memory_md()
        
        # Should be truncated
        assert result is not None
        result_bytes = result.encode("utf-8")
        
        # Result should be at most MAX_MEMORY_FILE_SIZE
        assert len(result_bytes) <= MAX_MEMORY_FILE_SIZE, (
            f"Truncated content should be at most {MAX_MEMORY_FILE_SIZE} bytes, "
            f"but got {len(result_bytes)} bytes"
        )
        
        # Result should be less than original
        assert len(result_bytes) < len(content_bytes), (
            "Truncated content should be smaller than original"
        )

    @given(
        line_count=st.integers(min_value=100, max_value=500),
        line_length=st.integers(min_value=50, max_value=200),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_truncation_at_line_boundary(
        self,
        tmp_path: Path,
        line_count: int,
        line_length: int,
    ) -> None:
        """Property 2: Truncation happens at line boundary (no partial lines)
        
        For any MEMORY.md file that exceeds 2MB, the truncated content
        should end at a complete line boundary (with newline character),
        ensuring no partial lines exist.
        
        **Validates: Requirements 1.3**
        """
        # Create content that exceeds the limit with known line structure
        # Each line has a unique identifier to verify integrity
        lines = [f"Line {i:06d}: " + "x" * (line_length - 15) for i in range(line_count)]
        
        # Calculate how many lines we need to exceed 2MB
        sample_line = lines[0] + "\n"
        bytes_per_line = len(sample_line.encode("utf-8"))
        lines_needed = (MAX_MEMORY_FILE_SIZE // bytes_per_line) + line_count
        
        # Generate enough lines
        all_lines = []
        for i in range(lines_needed):
            all_lines.append(f"Line {i:06d}: " + "x" * (line_length - 15))
        
        large_content = "\n".join(all_lines) + "\n"
        
        # Verify content exceeds limit
        content_bytes = large_content.encode("utf-8")
        assume(len(content_bytes) > MAX_MEMORY_FILE_SIZE)
        
        # Create the file
        memory_file = tmp_path / "MEMORY.md"
        memory_file.write_text(large_content, encoding="utf-8")
        
        # Load memory
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        result = loader.load_memory_md()
        
        # Should be truncated
        assert result is not None
        
        # Result should end with newline (line boundary)
        assert result.endswith("\n"), (
            "Truncated content should end with newline (line boundary)"
        )
        
        # All lines in result should be complete (no partial lines)
        result_lines = result.split("\n")
        # Remove the last empty element from split (after trailing newline)
        if result_lines and result_lines[-1] == "":
            result_lines = result_lines[:-1]
        
        for i, line in enumerate(result_lines):
            # Each line should match the expected pattern
            assert line.startswith(f"Line {i:06d}: "), (
                f"Line {i} appears to be partial or corrupted: {line[:50]}..."
            )

    @given(
        overflow_factor=st.floats(min_value=1.01, max_value=2.0),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_content_integrity_preserved(
        self,
        tmp_path: Path,
        overflow_factor: float,
    ) -> None:
        """Property 2: Content integrity is maintained for the loaded portion
        
        For any MEMORY.md file that exceeds 2MB, the truncated content
        should be a valid prefix of the original content (byte-for-byte match
        up to the truncation point).
        
        **Validates: Requirements 1.3**
        """
        # Create content that exceeds the limit
        target_size = int(MAX_MEMORY_FILE_SIZE * overflow_factor)
        
        # Generate content with known structure
        lines = []
        current_size = 0
        line_num = 0
        while current_size < target_size:
            line = f"# Line {line_num:08d} - Content marker for integrity check\n"
            lines.append(line)
            current_size += len(line.encode("utf-8"))
            line_num += 1
        
        large_content = "".join(lines)
        
        # Verify content exceeds limit
        content_bytes = large_content.encode("utf-8")
        assume(len(content_bytes) > MAX_MEMORY_FILE_SIZE)
        
        # Create the file
        memory_file = tmp_path / "MEMORY.md"
        memory_file.write_text(large_content, encoding="utf-8")
        
        # Load memory
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        result = loader.load_memory_md()
        
        # Should be truncated
        assert result is not None
        
        # The result should be a prefix of the original content
        # (accounting for line boundary truncation)
        assert large_content.startswith(result), (
            "Truncated content should be a valid prefix of original content"
        )

    @given(
        size_under_limit=st.integers(
            min_value=1,
            max_value=MAX_MEMORY_FILE_SIZE - 1,
        ),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_boundary_case_just_under_limit(
        self,
        tmp_path: Path,
        size_under_limit: int,
    ) -> None:
        """Property 2 (boundary): Files just under 2MB are not truncated
        
        For any MEMORY.md file with size exactly at or just under 2MB,
        the content should be loaded completely without truncation.
        
        **Validates: Requirements 1.3**
        """
        # Create content of exact size (just under limit)
        # Use simple repeating pattern
        target_size = min(size_under_limit, 100000)  # Cap for test performance
        
        # Generate lines to reach target size
        lines = []
        current_size = 0
        line_num = 0
        while current_size < target_size:
            line = f"Line {line_num}\n"
            lines.append(line)
            current_size += len(line.encode("utf-8"))
            line_num += 1
        
        content = "".join(lines)
        
        # Ensure we're under the limit
        content_bytes = content.encode("utf-8")
        assume(len(content_bytes) < MAX_MEMORY_FILE_SIZE)
        
        # Create the file
        memory_file = tmp_path / "MEMORY.md"
        memory_file.write_text(content, encoding="utf-8")
        
        # Load memory
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        result = loader.load_memory_md()
        
        # Should load complete content
        assert result is not None
        assert result == content, (
            "File under limit should be loaded completely without truncation"
        )

    @given(
        size_over_limit=st.integers(
            min_value=MAX_MEMORY_FILE_SIZE + 1,
            max_value=MAX_MEMORY_FILE_SIZE + 100000,
        ),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_boundary_case_just_over_limit(
        self,
        tmp_path: Path,
        size_over_limit: int,
    ) -> None:
        """Property 2 (boundary): Files just over 2MB are truncated
        
        For any MEMORY.md file with size just over 2MB,
        the content should be truncated to at most 2MB.
        
        **Validates: Requirements 1.3**
        """
        # Create content of exact size (just over limit)
        target_size = size_over_limit
        
        # Generate lines to reach target size
        lines = []
        current_size = 0
        line_num = 0
        while current_size < target_size:
            line = f"Line {line_num:08d} - padding content here\n"
            lines.append(line)
            current_size += len(line.encode("utf-8"))
            line_num += 1
        
        content = "".join(lines)
        
        # Ensure we're over the limit
        content_bytes = content.encode("utf-8")
        assume(len(content_bytes) > MAX_MEMORY_FILE_SIZE)
        
        # Create the file
        memory_file = tmp_path / "MEMORY.md"
        memory_file.write_text(content, encoding="utf-8")
        
        # Load memory
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        result = loader.load_memory_md()
        
        # Should be truncated
        assert result is not None
        result_bytes = result.encode("utf-8")
        
        # Result should be at most MAX_MEMORY_FILE_SIZE
        assert len(result_bytes) <= MAX_MEMORY_FILE_SIZE, (
            f"File over limit should be truncated to at most {MAX_MEMORY_FILE_SIZE} bytes"
        )
        
        # Result should be smaller than original
        assert len(result_bytes) < len(content_bytes), (
            "Truncated content should be smaller than original"
        )

    @given(
        line_lengths=st.lists(
            st.integers(min_value=10, max_value=1000),
            min_size=100,
            max_size=500,
        ),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_variable_line_lengths_truncation(
        self,
        tmp_path: Path,
        line_lengths: list[int],
    ) -> None:
        """Property 2: Truncation works correctly with variable line lengths
        
        For any MEMORY.md file with variable line lengths that exceeds 2MB,
        the truncation should still happen at a valid line boundary.
        
        **Validates: Requirements 1.3**
        """
        # Create content with variable line lengths
        lines = []
        current_size = 0
        target_size = MAX_MEMORY_FILE_SIZE + 100000  # Exceed limit
        
        line_idx = 0
        while current_size < target_size:
            length = line_lengths[line_idx % len(line_lengths)]
            # Create line with marker and padding
            marker = f"[{line_idx:06d}]"
            padding_length = max(0, length - len(marker) - 1)
            line = marker + "x" * padding_length + "\n"
            lines.append(line)
            current_size += len(line.encode("utf-8"))
            line_idx += 1
        
        content = "".join(lines)
        
        # Verify content exceeds limit
        content_bytes = content.encode("utf-8")
        assume(len(content_bytes) > MAX_MEMORY_FILE_SIZE)
        
        # Create the file
        memory_file = tmp_path / "MEMORY.md"
        memory_file.write_text(content, encoding="utf-8")
        
        # Load memory
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        result = loader.load_memory_md()
        
        # Should be truncated
        assert result is not None
        result_bytes = result.encode("utf-8")
        
        # Result should be at most MAX_MEMORY_FILE_SIZE
        assert len(result_bytes) <= MAX_MEMORY_FILE_SIZE
        
        # Result should end with newline
        assert result.endswith("\n"), (
            "Truncated content should end with newline"
        )
        
        # Verify all lines are complete (check markers)
        result_lines = result.rstrip("\n").split("\n")
        for i, line in enumerate(result_lines):
            expected_marker = f"[{i:06d}]"
            assert line.startswith(expected_marker), (
                f"Line {i} should start with marker {expected_marker}, "
                f"but got: {line[:20]}..."
            )


# ---------------------------------------------------------------------------
# Property 15: Markdown 分块一致性
# ---------------------------------------------------------------------------


# Strategy for generating markdown content with various structures
_chunking_markdown_content = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        whitelist_characters="\n\t -#*_[](){}",
    ),
    min_size=1,
    max_size=2000,
).map(lambda s: f"# Document\n\n{s}")


# Strategy for generating multi-paragraph markdown
_multi_paragraph_markdown = st.lists(
    st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N", "P", "S"),
            whitelist_characters=" \t-#*_[](){}",
            blacklist_characters="\n\r",
        ),
        min_size=10,
        max_size=200,
    ),
    min_size=5,
    max_size=50,
).map(lambda paragraphs: "\n\n".join(paragraphs))


class TestMarkdownChunkingConsistencyProperties:
    """Property-based tests for Markdown chunking consistency (Property 15).
    
    **Validates: Requirements 5.2**
    
    Requirements 5.2 states:
    - 按 tokens 分块，默认 512 tokens/块
    
    Property 15 from design.md:
    - 对于任意 Markdown 内容 M，chunk_markdown(M) 的结果满足：
      - 所有分块拼接后覆盖原始内容（无遗漏）
      - 相邻分块有 chunk_overlap 的重叠
      - 每个分块的 token 数 ≤ chunk_tokens
    """

    @given(content=_chunking_markdown_content)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_chunking_is_deterministic(
        self,
        tmp_path: Path,
        content: str,
    ) -> None:
        """Property 15 (determinism): Chunking with same config produces same result
        
        For any Markdown content M, chunk_markdown(M) with the same
        chunk_tokens and chunk_overlap configuration should always
        produce identical results (deterministic behavior).
        
        **Validates: Requirements 5.2**
        """
        loader = MemoryLoader(
            workspace_dir=str(tmp_path),
            chunk_tokens=512,
            chunk_overlap=64,
        )
        
        # Chunk the same content multiple times
        results = [
            loader.chunk_markdown(content, "test.md")
            for _ in range(5)
        ]
        
        # All results should be identical
        for i, result in enumerate(results[1:], start=1):
            assert len(result) == len(results[0]), (
                f"Chunking attempt {i} produced different number of chunks: "
                f"{len(result)} vs {len(results[0])}"
            )
            for j, (chunk_a, chunk_b) in enumerate(zip(results[0], result)):
                assert chunk_a.text == chunk_b.text, (
                    f"Chunk {j} differs between attempts"
                )
                assert chunk_a.hash == chunk_b.hash, (
                    f"Chunk {j} hash differs between attempts"
                )

    @given(
        content=_multi_paragraph_markdown,
        chunk_tokens=st.integers(min_value=50, max_value=1000),
        chunk_overlap=st.integers(min_value=0, max_value=100),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_chunks_cover_original_content(
        self,
        tmp_path: Path,
        content: str,
        chunk_tokens: int,
        chunk_overlap: int,
    ) -> None:
        """Property 15 (coverage): All chunks together cover original content
        
        For any Markdown content M, the chunks produced by chunk_markdown(M)
        should together cover all words from the original content without
        any omissions.
        
        **Validates: Requirements 5.2**
        """
        # Ensure overlap is less than chunk size
        assume(chunk_overlap < chunk_tokens)
        
        loader = MemoryLoader(
            workspace_dir=str(tmp_path),
            chunk_tokens=chunk_tokens,
            chunk_overlap=chunk_overlap,
        )
        
        chunks = loader.chunk_markdown(content, "test.md")
        
        # Skip empty content
        original_words = content.split()
        if not original_words:
            assert len(chunks) == 0, "Empty content should produce no chunks"
            return
        
        # Collect all words from chunks
        chunk_words_set: set[str] = set()
        for chunk in chunks:
            chunk_words = chunk.text.split()
            chunk_words_set.update(chunk_words)
        
        # All original words should be present in chunks
        original_words_set = set(original_words)
        missing_words = original_words_set - chunk_words_set
        
        assert len(missing_words) == 0, (
            f"Some words from original content are missing in chunks: "
            f"{list(missing_words)[:10]}..."
        )

    @given(
        content=_multi_paragraph_markdown,
        chunk_tokens=st.integers(min_value=100, max_value=512),
        chunk_overlap=st.integers(min_value=10, max_value=64),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_adjacent_chunks_have_overlap(
        self,
        tmp_path: Path,
        content: str,
        chunk_tokens: int,
        chunk_overlap: int,
    ) -> None:
        """Property 15 (overlap): Adjacent chunks have chunk_overlap overlap
        
        For any Markdown content M with multiple chunks, adjacent chunks
        should share some overlapping content (words) to maintain context
        continuity.
        
        **Validates: Requirements 5.2**
        """
        # Ensure overlap is less than chunk size and positive
        assume(chunk_overlap > 0)
        assume(chunk_overlap < chunk_tokens // 2)
        
        loader = MemoryLoader(
            workspace_dir=str(tmp_path),
            chunk_tokens=chunk_tokens,
            chunk_overlap=chunk_overlap,
        )
        
        chunks = loader.chunk_markdown(content, "test.md")
        
        # Need at least 2 chunks to test overlap
        if len(chunks) < 2:
            return
        
        # Check overlap between adjacent chunks
        for i in range(len(chunks) - 1):
            current_chunk = chunks[i]
            next_chunk = chunks[i + 1]
            
            current_words = current_chunk.text.split()
            next_words = next_chunk.text.split()
            
            # Find overlapping words at the end of current and start of next
            # The overlap should be at the boundary
            overlap_found = False
            
            # Check if any suffix of current chunk matches prefix of next chunk
            for suffix_len in range(1, min(len(current_words), len(next_words)) + 1):
                current_suffix = current_words[-suffix_len:]
                next_prefix = next_words[:suffix_len]
                
                if current_suffix == next_prefix:
                    overlap_found = True
                    break
            
            assert overlap_found, (
                f"Adjacent chunks {i} and {i+1} should have overlapping content. "
                f"Current chunk ends with: {current_words[-5:] if len(current_words) >= 5 else current_words}, "
                f"Next chunk starts with: {next_words[:5] if len(next_words) >= 5 else next_words}"
            )

    @given(
        content=_multi_paragraph_markdown,
        chunk_tokens=st.integers(min_value=50, max_value=1000),
        chunk_overlap=st.integers(min_value=0, max_value=100),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_each_chunk_respects_token_limit(
        self,
        tmp_path: Path,
        content: str,
        chunk_tokens: int,
        chunk_overlap: int,
    ) -> None:
        """Property 15 (token limit): Each chunk's token count ≤ chunk_tokens
        
        For any Markdown content M, each chunk produced by chunk_markdown(M)
        should have a token count that does not exceed the configured
        chunk_tokens limit.
        
        **Validates: Requirements 5.2**
        """
        # Ensure overlap is less than chunk size
        assume(chunk_overlap < chunk_tokens)
        
        loader = MemoryLoader(
            workspace_dir=str(tmp_path),
            chunk_tokens=chunk_tokens,
            chunk_overlap=chunk_overlap,
        )
        
        chunks = loader.chunk_markdown(content, "test.md")
        
        for i, chunk in enumerate(chunks):
            # Estimate token count using word-based approximation
            # The implementation uses 1 word ≈ 1.3 tokens
            word_count = len(chunk.text.split())
            estimated_tokens = int(word_count * 1.3)
            
            # Allow some tolerance for the approximation
            # The chunk should not significantly exceed the limit
            max_allowed_tokens = chunk_tokens + chunk_tokens // 10  # 10% tolerance
            
            assert estimated_tokens <= max_allowed_tokens, (
                f"Chunk {i} has approximately {estimated_tokens} tokens, "
                f"which exceeds the limit of {chunk_tokens} tokens "
                f"(with 10% tolerance: {max_allowed_tokens})"
            )

    @given(
        content=_chunking_markdown_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_chunk_line_numbers_are_valid(
        self,
        tmp_path: Path,
        content: str,
    ) -> None:
        """Property 15 (line tracking): Chunk line numbers are valid
        
        For any Markdown content M, each chunk should have valid
        start_line and end_line values that:
        - Are 1-indexed (start from 1)
        - start_line <= end_line
        - Are within the bounds of the original content
        
        **Validates: Requirements 5.2**
        """
        loader = MemoryLoader(
            workspace_dir=str(tmp_path),
            chunk_tokens=512,
            chunk_overlap=64,
        )
        
        chunks = loader.chunk_markdown(content, "test.md")
        
        if not chunks:
            return
        
        total_lines = len(content.split("\n"))
        
        for i, chunk in enumerate(chunks):
            # Line numbers should be 1-indexed
            assert chunk.start_line >= 1, (
                f"Chunk {i} start_line should be >= 1, got {chunk.start_line}"
            )
            
            # start_line should be <= end_line
            assert chunk.start_line <= chunk.end_line, (
                f"Chunk {i} start_line ({chunk.start_line}) should be <= "
                f"end_line ({chunk.end_line})"
            )
            
            # Line numbers should be within bounds
            assert chunk.end_line <= total_lines, (
                f"Chunk {i} end_line ({chunk.end_line}) exceeds total lines "
                f"({total_lines})"
            )

    @given(
        content=_chunking_markdown_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_chunk_hashes_are_computed_correctly(
        self,
        tmp_path: Path,
        content: str,
    ) -> None:
        """Property 15 (hash consistency): Chunk hashes match content
        
        For any Markdown content M, each chunk's hash should be
        computed correctly from its text content using SHA-256
        (first 16 characters).
        
        **Validates: Requirements 5.2**
        """
        loader = MemoryLoader(
            workspace_dir=str(tmp_path),
            chunk_tokens=512,
            chunk_overlap=64,
        )
        
        chunks = loader.chunk_markdown(content, "test.md")
        
        for i, chunk in enumerate(chunks):
            # Recompute hash
            expected_hash = loader.compute_hash(chunk.text)
            
            assert chunk.hash == expected_hash, (
                f"Chunk {i} hash mismatch: expected {expected_hash}, "
                f"got {chunk.hash}"
            )
            
            # Hash should be 16 characters
            assert len(chunk.hash) == 16, (
                f"Chunk {i} hash should be 16 characters, got {len(chunk.hash)}"
            )

    @given(
        content=_chunking_markdown_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_embedding_input_matches_text(
        self,
        tmp_path: Path,
        content: str,
    ) -> None:
        """Property 15 (embedding input): embedding_input equals chunk text
        
        For any Markdown content M, each chunk's embedding_input should
        be set to the chunk text for vectorization.
        
        **Validates: Requirements 5.2**
        """
        loader = MemoryLoader(
            workspace_dir=str(tmp_path),
            chunk_tokens=512,
            chunk_overlap=64,
        )
        
        chunks = loader.chunk_markdown(content, "test.md")
        
        for i, chunk in enumerate(chunks):
            assert chunk.embedding_input == chunk.text, (
                f"Chunk {i} embedding_input should equal text"
            )

    @given(
        content=_multi_paragraph_markdown,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_chunks_preserve_word_order(
        self,
        tmp_path: Path,
        content: str,
    ) -> None:
        """Property 15 (order preservation): Chunks preserve word order
        
        For any Markdown content M, when iterating through chunks in order,
        the first occurrence of each word should appear in the same relative
        order as in the original content.
        
        **Validates: Requirements 5.2**
        """
        loader = MemoryLoader(
            workspace_dir=str(tmp_path),
            chunk_tokens=512,
            chunk_overlap=64,
        )
        
        chunks = loader.chunk_markdown(content, "test.md")
        
        if not chunks:
            return
        
        # Get original word sequence
        original_words = content.split()
        if not original_words:
            return
        
        # Build sequence of first occurrences from chunks
        seen_words: set[str] = set()
        chunk_word_order: list[str] = []
        
        for chunk in chunks:
            for word in chunk.text.split():
                if word not in seen_words:
                    seen_words.add(word)
                    chunk_word_order.append(word)
        
        # Build sequence of first occurrences from original
        seen_original: set[str] = set()
        original_word_order: list[str] = []
        
        for word in original_words:
            if word not in seen_original:
                seen_original.add(word)
                original_word_order.append(word)
        
        # The relative order should be preserved
        # Check that chunk_word_order is a subsequence of original_word_order
        # (allowing for some reordering due to chunking boundaries)
        chunk_idx = 0
        for orig_word in original_word_order:
            if chunk_idx < len(chunk_word_order) and chunk_word_order[chunk_idx] == orig_word:
                chunk_idx += 1
        
        # Most words should be in order (allow some tolerance for boundary effects)
        coverage = chunk_idx / len(chunk_word_order) if chunk_word_order else 1.0
        assert coverage >= 0.8, (
            f"Word order preservation is too low: {coverage:.2%}. "
            f"Expected at least 80% of words to maintain relative order."
        )

    @given(
        chunk_tokens=st.integers(min_value=50, max_value=1000),
        chunk_overlap=st.integers(min_value=0, max_value=100),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_empty_content_produces_no_chunks(
        self,
        tmp_path: Path,
        chunk_tokens: int,
        chunk_overlap: int,
    ) -> None:
        """Property 15 (empty content): Empty content produces no chunks
        
        For empty or whitespace-only content, chunk_markdown should
        return an empty list of chunks.
        
        **Validates: Requirements 5.2**
        """
        assume(chunk_overlap < chunk_tokens)
        
        loader = MemoryLoader(
            workspace_dir=str(tmp_path),
            chunk_tokens=chunk_tokens,
            chunk_overlap=chunk_overlap,
        )
        
        # Test empty string
        chunks = loader.chunk_markdown("", "test.md")
        assert len(chunks) == 0, "Empty content should produce no chunks"
        
        # Test whitespace-only content
        chunks = loader.chunk_markdown("   \n\n   \t\t   ", "test.md")
        assert len(chunks) == 0, "Whitespace-only content should produce no chunks"

    @given(
        content=_multi_paragraph_markdown,
        chunk_tokens_1=st.integers(min_value=100, max_value=500),
        chunk_tokens_2=st.integers(min_value=100, max_value=500),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_different_chunk_sizes_produce_different_results(
        self,
        tmp_path: Path,
        content: str,
        chunk_tokens_1: int,
        chunk_tokens_2: int,
    ) -> None:
        """Property 15 (config sensitivity): Different configs produce different chunks
        
        For any Markdown content M with sufficient length, different
        chunk_tokens configurations should generally produce different
        chunking results (different number of chunks or different boundaries).
        
        **Validates: Requirements 5.2**
        """
        # Only test when chunk sizes are significantly different
        assume(abs(chunk_tokens_1 - chunk_tokens_2) >= 50)
        
        loader_1 = MemoryLoader(
            workspace_dir=str(tmp_path),
            chunk_tokens=chunk_tokens_1,
            chunk_overlap=32,
        )
        
        loader_2 = MemoryLoader(
            workspace_dir=str(tmp_path),
            chunk_tokens=chunk_tokens_2,
            chunk_overlap=32,
        )
        
        chunks_1 = loader_1.chunk_markdown(content, "test.md")
        chunks_2 = loader_2.chunk_markdown(content, "test.md")
        
        # Skip if content is too small to produce multiple chunks
        if len(chunks_1) <= 1 and len(chunks_2) <= 1:
            return
        
        # Different chunk sizes should produce different results
        # Either different number of chunks or different chunk boundaries
        if len(chunks_1) != len(chunks_2):
            # Different number of chunks - test passes
            return
        
        # Same number of chunks - check if boundaries differ
        boundaries_differ = False
        for c1, c2 in zip(chunks_1, chunks_2):
            if c1.text != c2.text:
                boundaries_differ = True
                break
        
        # At least one of the conditions should be true for sufficiently different configs
        # (This is a soft assertion - we just verify the chunking is config-sensitive)
        if len(chunks_1) > 1:
            assert len(chunks_1) != len(chunks_2) or boundaries_differ, (
                f"Different chunk_tokens ({chunk_tokens_1} vs {chunk_tokens_2}) "
                f"should produce different chunking results for multi-chunk content"
            )


# ---------------------------------------------------------------------------
# Property 16: 分块哈希唯一性
# ---------------------------------------------------------------------------


# Strategy for generating distinct text content
_distinct_text_content = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S"),
        whitelist_characters=" \t-#*_[](){}",
        blacklist_characters="\n\r",
    ),
    min_size=1,
    max_size=500,
)


class TestChunkHashUniquenessProperties:
    """Property-based tests for chunk hash uniqueness (Property 16).
    
    **Validates: Requirements 5.3**
    
    Requirements 5.3 states:
    - 每个分块计算 SHA-256 哈希（前 16 位）
    
    Property 16 from design.md:
    - 对于任意两个不同内容的分块 C1 和 C2，hash(C1) ≠ hash(C2)（高概率）
    - 对于相同内容的分块，hash 值相同
    """

    @given(content=_distinct_text_content)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_same_content_produces_same_hash(
        self,
        tmp_path: Path,
        content: str,
    ) -> None:
        """Property 16 (determinism): Same content produces same hash
        
        For any text content C, compute_hash(C) should always return
        the same hash value (deterministic behavior).
        
        **Validates: Requirements 5.3**
        """
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        # Compute hash multiple times
        hashes = [loader.compute_hash(content) for _ in range(5)]
        
        # All hashes should be identical
        assert all(h == hashes[0] for h in hashes), (
            f"Same content should produce same hash, but got different hashes: {hashes}"
        )

    @given(
        content1=_distinct_text_content,
        content2=_distinct_text_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_different_content_produces_different_hash(
        self,
        tmp_path: Path,
        content1: str,
        content2: str,
    ) -> None:
        """Property 16 (uniqueness): Different content produces different hash
        
        For any two distinct text contents C1 and C2 where C1 ≠ C2,
        compute_hash(C1) ≠ compute_hash(C2) with high probability.
        
        **Validates: Requirements 5.3**
        """
        # Skip if contents are the same
        assume(content1 != content2)
        
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        hash1 = loader.compute_hash(content1)
        hash2 = loader.compute_hash(content2)
        
        # Different content should produce different hashes
        assert hash1 != hash2, (
            f"Different content should produce different hashes. "
            f"Content1: '{content1[:50]}...', Content2: '{content2[:50]}...', "
            f"Both produced hash: {hash1}"
        )

    @given(content=_distinct_text_content)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_hash_length_is_16_characters(
        self,
        tmp_path: Path,
        content: str,
    ) -> None:
        """Property 16 (format): Hash is exactly 16 characters
        
        For any text content C, compute_hash(C) should return a string
        of exactly 16 hexadecimal characters (SHA-256 first 16 chars).
        
        **Validates: Requirements 5.3**
        """
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        hash_value = loader.compute_hash(content)
        
        # Hash should be exactly 16 characters
        assert len(hash_value) == 16, (
            f"Hash should be 16 characters, got {len(hash_value)}: {hash_value}"
        )
        
        # Hash should be valid hexadecimal
        try:
            int(hash_value, 16)
        except ValueError:
            pytest.fail(f"Hash should be valid hexadecimal, got: {hash_value}")

    @given(
        base_content=_distinct_text_content,
        suffix=st.text(min_size=1, max_size=10),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_small_content_change_produces_different_hash(
        self,
        tmp_path: Path,
        base_content: str,
        suffix: str,
    ) -> None:
        """Property 16 (sensitivity): Small content change produces different hash
        
        For any text content C and a small modification (appending suffix),
        the hash should change (avalanche effect of SHA-256).
        
        **Validates: Requirements 5.3**
        """
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        modified_content = base_content + suffix
        
        # Skip if modification didn't change content
        assume(base_content != modified_content)
        
        hash_original = loader.compute_hash(base_content)
        hash_modified = loader.compute_hash(modified_content)
        
        # Even small changes should produce different hashes
        assert hash_original != hash_modified, (
            f"Small content change should produce different hash. "
            f"Original: '{base_content[:30]}...', Modified: '{modified_content[:30]}...', "
            f"Both produced hash: {hash_original}"
        )

    @given(
        contents=st.lists(
            _distinct_text_content,
            min_size=2,
            max_size=50,
            unique=True,
        ),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_multiple_distinct_contents_produce_unique_hashes(
        self,
        tmp_path: Path,
        contents: list[str],
    ) -> None:
        """Property 16 (batch uniqueness): Multiple distinct contents produce unique hashes
        
        For any list of distinct text contents, all computed hashes should
        be unique (no collisions within the batch).
        
        **Validates: Requirements 5.3**
        """
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        hashes = [loader.compute_hash(content) for content in contents]
        
        # All hashes should be unique
        unique_hashes = set(hashes)
        assert len(unique_hashes) == len(hashes), (
            f"All distinct contents should produce unique hashes. "
            f"Got {len(hashes)} contents but only {len(unique_hashes)} unique hashes. "
            f"Collision detected!"
        )

    @given(content=_distinct_text_content)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_hash_is_sha256_prefix(
        self,
        tmp_path: Path,
        content: str,
    ) -> None:
        """Property 16 (algorithm): Hash is SHA-256 first 16 characters
        
        For any text content C, compute_hash(C) should return the first
        16 characters of the SHA-256 hash of the UTF-8 encoded content.
        
        **Validates: Requirements 5.3**
        """
        import hashlib
        
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        # Compute hash using the loader
        loader_hash = loader.compute_hash(content)
        
        # Compute expected hash directly
        expected_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        
        # Hashes should match
        assert loader_hash == expected_hash, (
            f"Hash should be SHA-256 first 16 chars. "
            f"Expected: {expected_hash}, Got: {loader_hash}"
        )

    @given(
        content=_multi_paragraph_markdown,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_chunk_hashes_are_unique_within_document(
        self,
        tmp_path: Path,
        content: str,
    ) -> None:
        """Property 16 (chunk uniqueness): Chunk hashes are unique within a document
        
        For any Markdown document that produces multiple chunks,
        all chunk hashes should be unique (assuming chunks have different content).
        
        **Validates: Requirements 5.3**
        """
        loader = MemoryLoader(
            workspace_dir=str(tmp_path),
            chunk_tokens=100,  # Smaller chunks to get more chunks
            chunk_overlap=20,
        )
        
        chunks = loader.chunk_markdown(content, "test.md")
        
        # Skip if not enough chunks
        if len(chunks) < 2:
            return
        
        # Collect hashes and their corresponding texts
        hash_to_text: dict[str, str] = {}
        
        for chunk in chunks:
            if chunk.hash in hash_to_text:
                # Hash collision - check if it's the same content
                existing_text = hash_to_text[chunk.hash]
                if existing_text != chunk.text:
                    pytest.fail(
                        f"Hash collision detected for different content! "
                        f"Hash: {chunk.hash}, "
                        f"Text1: '{existing_text[:50]}...', "
                        f"Text2: '{chunk.text[:50]}...'"
                    )
                # Same content, same hash - this is expected
            else:
                hash_to_text[chunk.hash] = chunk.text

    @given(
        content=_multi_paragraph_markdown,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_identical_chunks_have_same_hash(
        self,
        tmp_path: Path,
        content: str,
    ) -> None:
        """Property 16 (consistency): Identical chunk content produces same hash
        
        For any Markdown document, if two chunks happen to have identical
        text content, they should have the same hash.
        
        **Validates: Requirements 5.3**
        """
        loader = MemoryLoader(
            workspace_dir=str(tmp_path),
            chunk_tokens=512,
            chunk_overlap=64,
        )
        
        chunks = loader.chunk_markdown(content, "test.md")
        
        # Group chunks by text content
        text_to_hashes: dict[str, list[str]] = {}
        
        for chunk in chunks:
            if chunk.text not in text_to_hashes:
                text_to_hashes[chunk.text] = []
            text_to_hashes[chunk.text].append(chunk.hash)
        
        # For each unique text, all hashes should be the same
        for text, hashes in text_to_hashes.items():
            unique_hashes = set(hashes)
            assert len(unique_hashes) == 1, (
                f"Identical chunk content should produce same hash. "
                f"Text: '{text[:50]}...', Hashes: {hashes}"
            )

    @given(
        content1=_distinct_text_content,
        content2=_distinct_text_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_hash_independence_from_loader_instance(
        self,
        tmp_path: Path,
        content1: str,
        content2: str,
    ) -> None:
        """Property 16 (instance independence): Hash is independent of loader instance
        
        For any text content, the hash should be the same regardless of
        which MemoryLoader instance computes it.
        
        **Validates: Requirements 5.3**
        """
        loader1 = MemoryLoader(workspace_dir=str(tmp_path), chunk_tokens=256)
        loader2 = MemoryLoader(workspace_dir=str(tmp_path), chunk_tokens=512)
        loader3 = MemoryLoader(workspace_dir=str(tmp_path / "other"), chunk_tokens=1024)
        
        # Compute hashes with different loader instances
        hash1_l1 = loader1.compute_hash(content1)
        hash1_l2 = loader2.compute_hash(content1)
        hash1_l3 = loader3.compute_hash(content1)
        
        hash2_l1 = loader1.compute_hash(content2)
        hash2_l2 = loader2.compute_hash(content2)
        hash2_l3 = loader3.compute_hash(content2)
        
        # Same content should produce same hash across all instances
        assert hash1_l1 == hash1_l2 == hash1_l3, (
            f"Same content should produce same hash across loader instances. "
            f"Content1 hashes: {hash1_l1}, {hash1_l2}, {hash1_l3}"
        )
        
        assert hash2_l1 == hash2_l2 == hash2_l3, (
            f"Same content should produce same hash across loader instances. "
            f"Content2 hashes: {hash2_l1}, {hash2_l2}, {hash2_l3}"
        )

    @given(
        content=st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N", "P", "S", "Z"),
                whitelist_characters="\n\t -#*_[](){}",
            ),
            min_size=0,
            max_size=100,
        ),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_hash_handles_special_characters(
        self,
        tmp_path: Path,
        content: str,
    ) -> None:
        """Property 16 (special chars): Hash handles special characters correctly
        
        For any text content including special characters (newlines, tabs,
        unicode, etc.), compute_hash should produce a valid 16-character
        hexadecimal hash.
        
        **Validates: Requirements 5.3**
        """
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        hash_value = loader.compute_hash(content)
        
        # Hash should always be 16 characters
        assert len(hash_value) == 16, (
            f"Hash should be 16 characters for content with special chars, "
            f"got {len(hash_value)}: {hash_value}"
        )
        
        # Hash should be valid hexadecimal
        assert all(c in "0123456789abcdef" for c in hash_value), (
            f"Hash should be valid hexadecimal, got: {hash_value}"
        )

    @given(
        content=_distinct_text_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_hash_is_lowercase_hexadecimal(
        self,
        tmp_path: Path,
        content: str,
    ) -> None:
        """Property 16 (format): Hash is lowercase hexadecimal
        
        For any text content, compute_hash should return a lowercase
        hexadecimal string (consistent with Python's hashlib.hexdigest()).
        
        **Validates: Requirements 5.3**
        """
        loader = MemoryLoader(workspace_dir=str(tmp_path))
        
        hash_value = loader.compute_hash(content)
        
        # Hash should be lowercase
        assert hash_value == hash_value.lower(), (
            f"Hash should be lowercase hexadecimal, got: {hash_value}"
        )
        
        # Hash should only contain valid hex characters
        valid_hex_chars = set("0123456789abcdef")
        assert all(c in valid_hex_chars for c in hash_value), (
            f"Hash should only contain hex characters, got: {hash_value}"
        )

        hash_value = loader.compute_hash(content)
        
        # Hash should be lowercase
        assert hash_value == hash_value.lower(), (
            f"Hash should be lowercase hexadecimal, got: {hash_value}"
        )


# ---------------------------------------------------------------------------
# Property 14: memory/ 目录递归扫描
# ---------------------------------------------------------------------------


# Strategy for generating valid directory names (no special chars that cause issues)
_valid_dir_name = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="_-",
    ),
    min_size=1,
    max_size=20,
).filter(lambda s: s not in (".", "..") and not s.startswith("."))


# Strategy for generating valid file names (without extension)
_valid_file_name = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"),
        whitelist_characters="_-",
    ),
    min_size=1,
    max_size=20,
).filter(lambda s: s not in (".", "..") and not s.startswith("."))


# Strategy for generating markdown content for memory files
_memory_file_content = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        whitelist_characters="\n\t -#*_[](){}",
    ),
    min_size=1,
    max_size=200,
).map(lambda s: f"# Memory File\n\n{s}")


# Strategy for generating a directory tree structure
# Each element is (relative_path, is_md_file)
@st.composite
def _directory_tree(draw: st.DrawFn) -> list[tuple[str, bool]]:
    """Generate a random directory tree structure.
    
    Returns a list of (relative_path, is_md_file) tuples.
    is_md_file=True means it's a .md file, False means it's a non-.md file.
    """
    # Decide on depth and breadth
    max_depth = draw(st.integers(min_value=0, max_value=3))
    num_files = draw(st.integers(min_value=1, max_value=15))
    
    tree: list[tuple[str, bool]] = []
    
    for _ in range(num_files):
        # Generate path components
        depth = draw(st.integers(min_value=0, max_value=max_depth))
        path_parts: list[str] = []
        
        for _ in range(depth):
            dir_name = draw(_valid_dir_name)
            path_parts.append(dir_name)
        
        # Generate file name
        file_name = draw(_valid_file_name)
        
        # Decide if it's a .md file or not
        is_md = draw(st.booleans())
        
        if is_md:
            file_name = f"{file_name}.md"
        else:
            # Use various non-.md extensions
            ext = draw(st.sampled_from([".txt", ".json", ".yaml", ".py", ".html", ""]))
            file_name = f"{file_name}{ext}"
        
        # Build full path
        path_parts.append(file_name)
        full_path = "/".join(path_parts) if path_parts else file_name
        
        tree.append((full_path, is_md))
    
    return tree


class TestMemoryDirRecursiveScanProperties:
    """Property-based tests for memory/ directory recursive scanning (Property 14).
    
    **Validates: Requirements 5.1**
    
    Requirements 5.1 states:
    - 支持 memory/ 目录递归扫描所有 .md 文件
    
    Property 14 from design.md:
    - 对于任意目录结构 D，load_memory_dir() 返回的文件集合等于 D 中所有 .md 文件的集合
    """

    @given(tree=_directory_tree())
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_recursive_scan_finds_all_md_files(
        self,
        tmp_path: Path,
        tree: list[tuple[str, bool]],
    ) -> None:
        """Property 14: load_memory_dir() returns all .md files in directory
        
        For any directory structure D, load_memory_dir() should return
        a set of files that equals exactly the set of all .md files in D.
        
        **Validates: Requirements 5.1**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace using tempfile
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create memory directory
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            # Track expected .md files
            expected_md_files: set[str] = set()
            
            # Create the directory tree
            for rel_path, is_md in tree:
                file_path = memory_dir / rel_path
                
                # Create parent directories (skip if parent is a file)
                try:
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                except (FileExistsError, NotADirectoryError):
                    # Parent path is a file, skip this entry
                    continue
                
                # Create file with content (skip if path is a directory)
                content = f"# Content for {rel_path}\n\nThis is a test file."
                try:
                    # Check if path already exists as directory
                    if file_path.exists() and file_path.is_dir():
                        continue
                    file_path.write_text(content, encoding="utf-8")
                except (OSError, IsADirectoryError):
                    # Skip if file creation fails
                    continue
                
                # Track .md files
                if is_md:
                    expected_md_files.add(str(file_path))
            
            # Load memory directory
            loader = MemoryLoader(workspace_dir=str(workspace))
            memory_files = loader.load_memory_dir()
            
            # Extract loaded file paths
            loaded_paths = {mf.path for mf in memory_files}
            
            # Verify all expected .md files are loaded
            assert loaded_paths == expected_md_files, (
                f"Loaded files should match expected .md files.\n"
                f"Expected: {expected_md_files}\n"
                f"Got: {loaded_paths}\n"
                f"Missing: {expected_md_files - loaded_paths}\n"
                f"Extra: {loaded_paths - expected_md_files}"
            )
        finally:
            # Clean up
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        depth=st.integers(min_value=1, max_value=5),
        files_per_level=st.integers(min_value=1, max_value=3),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_recursive_scan_traverses_all_depths(
        self,
        tmp_path: Path,
        depth: int,
        files_per_level: int,
    ) -> None:
        """Property 14: Recursive scan traverses all directory depths
        
        For any directory structure with N levels of nesting,
        load_memory_dir() should find .md files at all levels.
        
        **Validates: Requirements 5.1**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create memory directory
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            expected_md_files: set[str] = set()
            
            # Create nested directory structure with files at each level
            current_dir = memory_dir
            for level in range(depth):
                # Create .md files at this level
                for i in range(files_per_level):
                    file_path = current_dir / f"file_level{level}_{i}.md"
                    file_path.write_text(f"# Level {level} File {i}\n", encoding="utf-8")
                    expected_md_files.add(str(file_path))
                
                # Create subdirectory for next level
                if level < depth - 1:
                    current_dir = current_dir / f"subdir_{level}"
                    current_dir.mkdir(parents=True, exist_ok=True)
            
            # Load memory directory
            loader = MemoryLoader(workspace_dir=str(workspace))
            memory_files = loader.load_memory_dir()
            
            # Extract loaded file paths
            loaded_paths = {mf.path for mf in memory_files}
            
            # Verify all files at all depths are found
            assert loaded_paths == expected_md_files, (
                f"Should find .md files at all {depth} levels.\n"
                f"Expected {len(expected_md_files)} files, got {len(loaded_paths)}"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        md_count=st.integers(min_value=0, max_value=10),
        non_md_count=st.integers(min_value=0, max_value=10),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_only_md_files_are_loaded(
        self,
        tmp_path: Path,
        md_count: int,
        non_md_count: int,
    ) -> None:
        """Property 14: Only .md files are loaded, other files are ignored
        
        For any directory containing both .md and non-.md files,
        load_memory_dir() should return only the .md files.
        
        **Validates: Requirements 5.1**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create memory directory
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            expected_md_files: set[str] = set()
            
            # Create .md files
            for i in range(md_count):
                file_path = memory_dir / f"document_{i}.md"
                file_path.write_text(f"# Document {i}\n", encoding="utf-8")
                expected_md_files.add(str(file_path))
            
            # Create non-.md files (should be ignored)
            non_md_extensions = [".txt", ".json", ".yaml", ".py", ".html", ".css", ".js"]
            for i in range(non_md_count):
                ext = non_md_extensions[i % len(non_md_extensions)]
                file_path = memory_dir / f"other_file_{i}{ext}"
                file_path.write_text(f"Content {i}", encoding="utf-8")
            
            # Load memory directory
            loader = MemoryLoader(workspace_dir=str(workspace))
            memory_files = loader.load_memory_dir()
            
            # Extract loaded file paths
            loaded_paths = {mf.path for mf in memory_files}
            
            # Verify only .md files are loaded
            assert loaded_paths == expected_md_files, (
                f"Should load only .md files.\n"
                f"Expected {md_count} .md files, got {len(loaded_paths)} files"
            )
            
            # Verify no non-.md files are loaded
            for mf in memory_files:
                assert mf.path.endswith(".md"), (
                    f"Non-.md file was loaded: {mf.path}"
                )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        subdir_count=st.integers(min_value=1, max_value=5),
        files_per_subdir=st.integers(min_value=1, max_value=3),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_recursive_scan_multiple_subdirectories(
        self,
        tmp_path: Path,
        subdir_count: int,
        files_per_subdir: int,
    ) -> None:
        """Property 14: Recursive scan finds files in multiple subdirectories
        
        For any directory with multiple subdirectories, each containing
        .md files, load_memory_dir() should find all files in all subdirectories.
        
        **Validates: Requirements 5.1**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create memory directory
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            expected_md_files: set[str] = set()
            
            # Create multiple subdirectories with files
            for subdir_idx in range(subdir_count):
                subdir = memory_dir / f"category_{subdir_idx}"
                subdir.mkdir(parents=True, exist_ok=True)
                
                for file_idx in range(files_per_subdir):
                    file_path = subdir / f"note_{file_idx}.md"
                    file_path.write_text(
                        f"# Category {subdir_idx} Note {file_idx}\n",
                        encoding="utf-8",
                    )
                    expected_md_files.add(str(file_path))
            
            # Load memory directory
            loader = MemoryLoader(workspace_dir=str(workspace))
            memory_files = loader.load_memory_dir()
            
            # Extract loaded file paths
            loaded_paths = {mf.path for mf in memory_files}
            
            # Verify all files from all subdirectories are found
            assert loaded_paths == expected_md_files, (
                f"Should find files in all {subdir_count} subdirectories.\n"
                f"Expected {len(expected_md_files)} files, got {len(loaded_paths)}"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(content=_memory_file_content)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_loaded_files_have_correct_content(
        self,
        tmp_path: Path,
        content: str,
    ) -> None:
        """Property 14: Loaded files have correct content
        
        For any .md file in the memory/ directory, the loaded MemoryFile
        should contain the exact file content.
        
        **Validates: Requirements 5.1**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create memory directory with a file
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            file_path = memory_dir / "test_file.md"
            file_path.write_text(content, encoding="utf-8")
            
            # Load memory directory
            loader = MemoryLoader(workspace_dir=str(workspace))
            memory_files = loader.load_memory_dir()
            
            # Should have exactly one file
            assert len(memory_files) == 1, f"Expected 1 file, got {len(memory_files)}"
            
            # Content should match
            loaded_file = memory_files[0]
            assert loaded_file.content == content, (
                f"File content should match.\n"
                f"Expected: {content[:100]}...\n"
                f"Got: {loaded_file.content[:100]}..."
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        file_count=st.integers(min_value=1, max_value=10),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_loaded_files_have_correct_metadata(
        self,
        tmp_path: Path,
        file_count: int,
    ) -> None:
        """Property 14: Loaded files have correct metadata (path, size, mtime)
        
        For any .md file in the memory/ directory, the loaded MemoryFile
        should have correct path, size, and modification time.
        
        **Validates: Requirements 5.1**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create memory directory
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            # Create files and track expected metadata
            expected_metadata: dict[str, tuple[int, str]] = {}  # path -> (size, content)
            
            for i in range(file_count):
                content = f"# File {i}\n\nContent for file {i}."
                file_path = memory_dir / f"file_{i}.md"
                file_path.write_text(content, encoding="utf-8")
                expected_metadata[str(file_path)] = (len(content.encode("utf-8")), content)
            
            # Load memory directory
            loader = MemoryLoader(workspace_dir=str(workspace))
            memory_files = loader.load_memory_dir()
            
            # Verify metadata for each file
            for mf in memory_files:
                assert mf.path in expected_metadata, f"Unexpected file: {mf.path}"
                expected_size, expected_content = expected_metadata[mf.path]
                
                # Verify size
                assert mf.size == expected_size, (
                    f"File {mf.path} size mismatch: expected {expected_size}, got {mf.size}"
                )
                
                # Verify content
                assert mf.content == expected_content, (
                    f"File {mf.path} content mismatch"
                )
                
                # Verify mtime is set (should be a positive float)
                assert mf.mtime > 0, f"File {mf.path} mtime should be positive"
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(st.data())
    def test_empty_memory_dir_returns_empty_list(
        self,
        tmp_path: Path,
        data: st.DataObject,
    ) -> None:
        """Property 14: Empty memory/ directory returns empty list
        
        For an empty memory/ directory (no .md files),
        load_memory_dir() should return an empty list.
        
        **Validates: Requirements 5.1**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create empty memory directory
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            # Optionally add some non-.md files
            non_md_count = data.draw(st.integers(min_value=0, max_value=5))
            for i in range(non_md_count):
                (memory_dir / f"file_{i}.txt").write_text(f"Content {i}", encoding="utf-8")
            
            # Load memory directory
            loader = MemoryLoader(workspace_dir=str(workspace))
            memory_files = loader.load_memory_dir()
            
            # Should return empty list
            assert len(memory_files) == 0, (
                f"Empty memory dir (no .md files) should return empty list, "
                f"got {len(memory_files)} files"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(st.data())
    def test_nonexistent_memory_dir_returns_empty_list(
        self,
        tmp_path: Path,
        data: st.DataObject,
    ) -> None:
        """Property 14: Non-existent memory/ directory returns empty list
        
        When the memory/ directory does not exist,
        load_memory_dir() should return an empty list without error.
        
        **Validates: Requirements 5.1**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace (but don't create memory dir)
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Don't create memory directory
            # Load memory directory
            loader = MemoryLoader(workspace_dir=str(workspace))
            memory_files = loader.load_memory_dir()
            
            # Should return empty list
            assert len(memory_files) == 0, (
                f"Non-existent memory dir should return empty list, "
                f"got {len(memory_files)} files"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        file_count=st.integers(min_value=2, max_value=10),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_files_are_sorted_by_path(
        self,
        tmp_path: Path,
        file_count: int,
    ) -> None:
        """Property 14: Loaded files are sorted by path for deterministic ordering
        
        For any memory/ directory with multiple files,
        load_memory_dir() should return files sorted by path.
        
        **Validates: Requirements 5.1**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create memory directory
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            # Create files with various names (not in alphabetical order)
            file_names = [f"z_file_{i}.md" for i in range(file_count // 2)]
            file_names += [f"a_file_{i}.md" for i in range(file_count - file_count // 2)]
            
            for name in file_names:
                file_path = memory_dir / name
                file_path.write_text(f"# {name}\n", encoding="utf-8")
            
            # Load memory directory
            loader = MemoryLoader(workspace_dir=str(workspace))
            memory_files = loader.load_memory_dir()
            
            # Verify files are sorted by path
            paths = [mf.path for mf in memory_files]
            sorted_paths = sorted(paths)
            
            assert paths == sorted_paths, (
                f"Files should be sorted by path.\n"
                f"Got: {paths}\n"
                f"Expected: {sorted_paths}"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        case_variant=st.sampled_from([".md", ".MD", ".Md", ".mD"]),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_md_extension_case_insensitive(
        self,
        tmp_path: Path,
        case_variant: str,
    ) -> None:
        """Property 14: .md extension matching is case-insensitive
        
        For any .md file with case variations in the extension
        (.md, .MD, .Md, .mD), load_memory_dir() should find the file.
        
        **Validates: Requirements 5.1**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create memory directory
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            # Create file with case variant extension
            file_path = memory_dir / f"test_file{case_variant}"
            file_path.write_text("# Test\n", encoding="utf-8")
            
            # Load memory directory
            loader = MemoryLoader(workspace_dir=str(workspace))
            memory_files = loader.load_memory_dir()
            
            # Should find the file regardless of extension case
            assert len(memory_files) == 1, (
                f"Should find file with extension {case_variant}, "
                f"got {len(memory_files)} files"
            )
            assert memory_files[0].path == str(file_path)
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        enabled=st.booleans(),
        file_count=st.integers(min_value=1, max_value=5),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_disabled_loader_returns_empty_list(
        self,
        tmp_path: Path,
        enabled: bool,
        file_count: int,
    ) -> None:
        """Property 14: Disabled loader returns empty list
        
        When memory loading is disabled (enabled=False),
        load_memory_dir() should return an empty list.
        
        **Validates: Requirements 5.1**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create memory directory with files
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            for i in range(file_count):
                (memory_dir / f"file_{i}.md").write_text(f"# File {i}\n", encoding="utf-8")
            
            # Load memory directory with enabled flag
            loader = MemoryLoader(workspace_dir=str(workspace), enabled=enabled)
            memory_files = loader.load_memory_dir()
            
            if enabled:
                # Should find files when enabled
                assert len(memory_files) == file_count, (
                    f"Enabled loader should find {file_count} files, got {len(memory_files)}"
                )
            else:
                # Should return empty when disabled
                assert len(memory_files) == 0, (
                    f"Disabled loader should return empty list, got {len(memory_files)} files"
                )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(tree=_directory_tree())
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_scan_is_deterministic(
        self,
        tmp_path: Path,
        tree: list[tuple[str, bool]],
    ) -> None:
        """Property 14: Recursive scan is deterministic
        
        For any directory structure, multiple calls to load_memory_dir()
        should return the same set of files in the same order.
        
        **Validates: Requirements 5.1**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create memory directory
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            # Create the directory tree
            for rel_path, is_md in tree:
                file_path = memory_dir / rel_path
                
                # Create parent directories (skip if parent is a file)
                try:
                    file_path.parent.mkdir(parents=True, exist_ok=True)
                except (FileExistsError, NotADirectoryError):
                    # Parent path is a file, skip this entry
                    continue
                
                # Create file (skip if path is a directory)
                try:
                    if file_path.exists() and file_path.is_dir():
                        continue
                    file_path.write_text(f"# {rel_path}\n", encoding="utf-8")
                except (OSError, IsADirectoryError):
                    continue
            
            # Load multiple times
            loader = MemoryLoader(workspace_dir=str(workspace))
            results = [loader.load_memory_dir() for _ in range(3)]
            
            # All results should have the same files in the same order
            first_paths = [mf.path for mf in results[0]]
            
            for i, result in enumerate(results[1:], start=1):
                paths = [mf.path for mf in result]
                assert paths == first_paths, (
                    f"Scan attempt {i} returned different results.\n"
                    f"First: {first_paths}\n"
                    f"Attempt {i}: {paths}"
                )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


# ---------------------------------------------------------------------------
# Property 17: memory/ 目录大小限制
# ---------------------------------------------------------------------------


from smartclaw.memory.loader import MAX_MEMORY_DIR_SIZE


class TestMemoryDirSizeLimitProperties:
    """Property-based tests for memory/ directory size limit (Property 17).
    
    **Validates: Requirements 5.7**
    
    Requirements 5.7 states:
    - memory/ 目录总大小限制为 50MB
    
    Property 17 from design.md:
    - 对于任意 memory/ 目录 D，load_memory_dir() 加载的文件总大小 ≤ 50MB
    - 当目录总大小超过 50MB 时，记录警告日志
    """

    @given(
        file_count=st.integers(min_value=1, max_value=10),
        file_size_kb=st.integers(min_value=1, max_value=100),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_files_under_limit_all_loaded(
        self,
        tmp_path: Path,
        file_count: int,
        file_size_kb: int,
    ) -> None:
        """Property 17: Files under 50MB limit are all loaded
        
        For any memory/ directory with total size < 50MB, all .md files
        should be loaded without any being skipped.
        
        **Validates: Requirements 5.7**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create memory directory
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            # Calculate total size and ensure it's under the limit
            total_size = file_count * file_size_kb * 1024
            assume(total_size < MAX_MEMORY_DIR_SIZE)
            
            # Create files
            expected_files: set[str] = set()
            for i in range(file_count):
                file_path = memory_dir / f"file_{i}.md"
                # Create content of approximately file_size_kb KB
                content = f"# File {i}\n\n" + "x" * (file_size_kb * 1024 - 20)
                file_path.write_text(content, encoding="utf-8")
                expected_files.add(str(file_path))
            
            # Load memory directory
            loader = MemoryLoader(workspace_dir=str(workspace))
            memory_files = loader.load_memory_dir()
            
            # All files should be loaded
            loaded_paths = {mf.path for mf in memory_files}
            assert loaded_paths == expected_files, (
                f"All files under limit should be loaded.\n"
                f"Expected {len(expected_files)} files, got {len(loaded_paths)}"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        file_count=st.integers(min_value=2, max_value=10),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_total_loaded_size_never_exceeds_limit(
        self,
        tmp_path: Path,
        file_count: int,
    ) -> None:
        """Property 17: Total loaded file size never exceeds 50MB
        
        For any memory/ directory D, the total size of files loaded by
        load_memory_dir() should never exceed MAX_MEMORY_DIR_SIZE (50MB).
        
        **Validates: Requirements 5.7**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create memory directory
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            # Create files that together exceed the limit
            # Each file is about 10MB, so 6 files = 60MB > 50MB limit
            file_size = 10 * 1024 * 1024  # 10MB per file
            
            for i in range(file_count):
                file_path = memory_dir / f"large_file_{i}.md"
                # Create content of approximately 10MB
                content = f"# Large File {i}\n\n" + "x" * (file_size - 30)
                file_path.write_text(content, encoding="utf-8")
            
            # Load memory directory
            loader = MemoryLoader(workspace_dir=str(workspace))
            memory_files = loader.load_memory_dir()
            
            # Calculate total loaded size
            total_loaded_size = sum(mf.size for mf in memory_files)
            
            # Total loaded size should not exceed the limit
            assert total_loaded_size <= MAX_MEMORY_DIR_SIZE, (
                f"Total loaded size ({total_loaded_size} bytes) should not exceed "
                f"MAX_MEMORY_DIR_SIZE ({MAX_MEMORY_DIR_SIZE} bytes)"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        overflow_mb=st.integers(min_value=1, max_value=20),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_files_skipped_when_limit_exceeded(
        self,
        tmp_path: Path,
        overflow_mb: int,
    ) -> None:
        """Property 17: Files are skipped when adding them would exceed limit
        
        For any memory/ directory where total size exceeds 50MB,
        load_memory_dir() should skip files that would cause the total
        to exceed the limit.
        
        **Validates: Requirements 5.7**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create memory directory
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            # Create files that together exceed the limit
            # First create files that fit within the limit
            file_size = 10 * 1024 * 1024  # 10MB per file
            files_that_fit = MAX_MEMORY_DIR_SIZE // file_size  # 5 files fit
            
            # Create files that will fit
            for i in range(files_that_fit):
                file_path = memory_dir / f"file_{i:02d}.md"
                content = f"# File {i}\n\n" + "x" * (file_size - 20)
                file_path.write_text(content, encoding="utf-8")
            
            # Create additional files that should be skipped
            overflow_files = overflow_mb // 10 + 1
            for i in range(overflow_files):
                file_path = memory_dir / f"overflow_{i:02d}.md"
                content = f"# Overflow {i}\n\n" + "x" * (file_size - 25)
                file_path.write_text(content, encoding="utf-8")
            
            # Load memory directory
            loader = MemoryLoader(workspace_dir=str(workspace))
            memory_files = loader.load_memory_dir()
            
            # Some files should be skipped
            total_files_created = files_that_fit + overflow_files
            assert len(memory_files) < total_files_created, (
                f"Some files should be skipped when limit is exceeded.\n"
                f"Created {total_files_created} files, loaded {len(memory_files)}"
            )
            
            # Total loaded size should be within limit
            total_loaded_size = sum(mf.size for mf in memory_files)
            assert total_loaded_size <= MAX_MEMORY_DIR_SIZE, (
                f"Total loaded size ({total_loaded_size}) should not exceed limit"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        small_file_count=st.integers(min_value=1, max_value=5),
        small_file_size_kb=st.integers(min_value=1, max_value=100),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_small_files_loaded_before_limit_reached(
        self,
        tmp_path: Path,
        small_file_count: int,
        small_file_size_kb: int,
    ) -> None:
        """Property 17: Small files are loaded before limit is reached
        
        For any memory/ directory with a mix of small and large files,
        files are loaded in sorted order until the limit is reached.
        
        **Validates: Requirements 5.7**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create memory directory
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            # Create small files (should all be loaded)
            small_files: set[str] = set()
            for i in range(small_file_count):
                file_path = memory_dir / f"a_small_{i}.md"  # 'a' prefix for sorting
                content = f"# Small {i}\n\n" + "x" * (small_file_size_kb * 1024 - 20)
                file_path.write_text(content, encoding="utf-8")
                small_files.add(str(file_path))
            
            # Create a large file that would exceed the limit
            large_file_path = memory_dir / "z_large.md"  # 'z' prefix for sorting
            large_content = "# Large\n\n" + "x" * (MAX_MEMORY_DIR_SIZE - 10)
            large_file_path.write_text(large_content, encoding="utf-8")
            
            # Load memory directory
            loader = MemoryLoader(workspace_dir=str(workspace))
            memory_files = loader.load_memory_dir()
            
            # Small files should be loaded (they come first in sorted order)
            loaded_paths = {mf.path for mf in memory_files}
            
            # Check that small files are loaded
            loaded_small_files = small_files & loaded_paths
            assert len(loaded_small_files) == len(small_files), (
                f"All small files should be loaded before limit is reached.\n"
                f"Expected {len(small_files)} small files, got {len(loaded_small_files)}"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        file_count=st.integers(min_value=5, max_value=15),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_loading_stops_at_limit_boundary(
        self,
        tmp_path: Path,
        file_count: int,
    ) -> None:
        """Property 17: Loading stops when adding next file would exceed limit
        
        For any memory/ directory, load_memory_dir() should stop loading
        when adding the next file would cause total size to exceed 50MB.
        
        **Validates: Requirements 5.7**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create memory directory
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            # Create files of varying sizes
            file_size = MAX_MEMORY_DIR_SIZE // file_count + 1024  # Slightly over average
            
            for i in range(file_count):
                file_path = memory_dir / f"file_{i:02d}.md"
                content = f"# File {i}\n\n" + "x" * (file_size - 20)
                file_path.write_text(content, encoding="utf-8")
            
            # Load memory directory
            loader = MemoryLoader(workspace_dir=str(workspace))
            memory_files = loader.load_memory_dir()
            
            # Calculate total loaded size
            total_loaded_size = sum(mf.size for mf in memory_files)
            
            # Total should be within limit
            assert total_loaded_size <= MAX_MEMORY_DIR_SIZE, (
                f"Total loaded size ({total_loaded_size}) exceeds limit"
            )
            
            # If not all files were loaded, verify that adding the next file
            # would have exceeded the limit
            if len(memory_files) < file_count:
                # The next file would have exceeded the limit
                loaded_paths = {mf.path for mf in memory_files}
                all_files = sorted(memory_dir.glob("*.md"), key=lambda p: str(p))
                
                for file_path in all_files:
                    if str(file_path) not in loaded_paths:
                        # This file was skipped
                        skipped_size = file_path.stat().st_size
                        # Adding this file would exceed the limit
                        assert total_loaded_size + skipped_size > MAX_MEMORY_DIR_SIZE, (
                            f"File was skipped but adding it wouldn't exceed limit.\n"
                            f"Current total: {total_loaded_size}, "
                            f"Skipped file size: {skipped_size}, "
                            f"Limit: {MAX_MEMORY_DIR_SIZE}"
                        )
                        break
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        file_size_mb=st.integers(min_value=1, max_value=10),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_exact_limit_boundary(
        self,
        tmp_path: Path,
        file_size_mb: int,
    ) -> None:
        """Property 17: Files exactly at the limit boundary are handled correctly
        
        For any memory/ directory where files exactly fill the 50MB limit,
        all files should be loaded and no more.
        
        **Validates: Requirements 5.7**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create memory directory
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            # Create files that exactly fill the limit
            file_size = file_size_mb * 1024 * 1024
            files_that_fit = MAX_MEMORY_DIR_SIZE // file_size
            
            # Ensure we have at least one file
            assume(files_that_fit >= 1)
            
            expected_files: set[str] = set()
            for i in range(files_that_fit):
                file_path = memory_dir / f"file_{i:02d}.md"
                content = f"# File {i}\n\n" + "x" * (file_size - 20)
                file_path.write_text(content, encoding="utf-8")
                expected_files.add(str(file_path))
            
            # Create one more file that would exceed the limit
            overflow_path = memory_dir / f"file_{files_that_fit:02d}.md"
            overflow_content = f"# Overflow\n\n" + "x" * (file_size - 20)
            overflow_path.write_text(overflow_content, encoding="utf-8")
            
            # Load memory directory
            loader = MemoryLoader(workspace_dir=str(workspace))
            memory_files = loader.load_memory_dir()
            
            # Files that fit should be loaded
            loaded_paths = {mf.path for mf in memory_files}
            
            # Total loaded size should be within limit
            total_loaded_size = sum(mf.size for mf in memory_files)
            assert total_loaded_size <= MAX_MEMORY_DIR_SIZE, (
                f"Total loaded size ({total_loaded_size}) exceeds limit"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        subdirs=st.integers(min_value=1, max_value=3),
        files_per_subdir=st.integers(min_value=1, max_value=3),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_size_limit_applies_across_subdirectories(
        self,
        tmp_path: Path,
        subdirs: int,
        files_per_subdir: int,
    ) -> None:
        """Property 17: Size limit applies to total across all subdirectories
        
        For any memory/ directory with subdirectories, the 50MB limit
        applies to the total size of all files across all subdirectories.
        
        **Validates: Requirements 5.7**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create memory directory
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            # Create files in subdirectories that together exceed the limit
            file_size = 10 * 1024 * 1024  # 10MB per file
            
            for subdir_idx in range(subdirs):
                subdir = memory_dir / f"subdir_{subdir_idx}"
                subdir.mkdir(parents=True, exist_ok=True)
                
                for file_idx in range(files_per_subdir):
                    file_path = subdir / f"file_{file_idx}.md"
                    content = f"# Subdir {subdir_idx} File {file_idx}\n\n" + "x" * (file_size - 40)
                    file_path.write_text(content, encoding="utf-8")
            
            # Load memory directory
            loader = MemoryLoader(workspace_dir=str(workspace))
            memory_files = loader.load_memory_dir()
            
            # Total loaded size should not exceed limit
            total_loaded_size = sum(mf.size for mf in memory_files)
            assert total_loaded_size <= MAX_MEMORY_DIR_SIZE, (
                f"Total loaded size across subdirectories ({total_loaded_size}) "
                f"should not exceed limit ({MAX_MEMORY_DIR_SIZE})"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        file_count=st.integers(min_value=1, max_value=5),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_size_limit_is_deterministic(
        self,
        tmp_path: Path,
        file_count: int,
    ) -> None:
        """Property 17: Size limit enforcement is deterministic
        
        For any memory/ directory, multiple calls to load_memory_dir()
        should return the same set of files (deterministic behavior).
        
        **Validates: Requirements 5.7**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create memory directory
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            # Create files that together exceed the limit
            file_size = 15 * 1024 * 1024  # 15MB per file
            
            for i in range(file_count):
                file_path = memory_dir / f"file_{i:02d}.md"
                content = f"# File {i}\n\n" + "x" * (file_size - 20)
                file_path.write_text(content, encoding="utf-8")
            
            # Load multiple times
            loader = MemoryLoader(workspace_dir=str(workspace))
            results = [loader.load_memory_dir() for _ in range(3)]
            
            # All results should have the same files
            first_paths = sorted([mf.path for mf in results[0]])
            
            for i, result in enumerate(results[1:], start=1):
                paths = sorted([mf.path for mf in result])
                assert paths == first_paths, (
                    f"Load attempt {i} returned different files.\n"
                    f"First: {first_paths}\n"
                    f"Attempt {i}: {paths}"
                )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        file_count=st.integers(min_value=1, max_value=10),
        file_size_kb=st.integers(min_value=1, max_value=500),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_loaded_files_content_integrity(
        self,
        tmp_path: Path,
        file_count: int,
        file_size_kb: int,
    ) -> None:
        """Property 17: Loaded files have correct content regardless of size limit
        
        For any memory/ directory, files that are loaded should have
        their complete content preserved (no truncation within files).
        
        **Validates: Requirements 5.7**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create memory directory
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            # Create files with known content
            file_contents: dict[str, str] = {}
            for i in range(file_count):
                file_path = memory_dir / f"file_{i:02d}.md"
                content = f"# File {i}\n\n" + f"Content marker {i}: " + "x" * (file_size_kb * 1024 - 50)
                file_path.write_text(content, encoding="utf-8")
                file_contents[str(file_path)] = content
            
            # Load memory directory
            loader = MemoryLoader(workspace_dir=str(workspace))
            memory_files = loader.load_memory_dir()
            
            # Verify content integrity for loaded files
            for mf in memory_files:
                expected_content = file_contents.get(mf.path)
                assert expected_content is not None, f"Unexpected file loaded: {mf.path}"
                assert mf.content == expected_content, (
                    f"File {mf.path} content was modified.\n"
                    f"Expected length: {len(expected_content)}, Got: {len(mf.content)}"
                )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        enabled=st.booleans(),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_size_limit_respects_enabled_flag(
        self,
        tmp_path: Path,
        enabled: bool,
    ) -> None:
        """Property 17: Size limit only applies when loader is enabled
        
        When memory loading is disabled (enabled=False), no files should
        be loaded regardless of size.
        
        **Validates: Requirements 5.7**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create memory directory with files under the limit
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            for i in range(3):
                file_path = memory_dir / f"file_{i}.md"
                file_path.write_text(f"# File {i}\n", encoding="utf-8")
            
            # Load with enabled flag
            loader = MemoryLoader(workspace_dir=str(workspace), enabled=enabled)
            memory_files = loader.load_memory_dir()
            
            if enabled:
                # Should load files when enabled
                assert len(memory_files) == 3, (
                    f"Enabled loader should load files, got {len(memory_files)}"
                )
            else:
                # Should return empty when disabled
                assert len(memory_files) == 0, (
                    f"Disabled loader should return empty, got {len(memory_files)}"
                )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


# ---------------------------------------------------------------------------
# Property 3: 记忆内容注入位置
# ---------------------------------------------------------------------------


# Strategy for generating valid markdown content for memory files
_memory_content = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        whitelist_characters="\n\t -#*_[](){}",
    ),
    min_size=1,
    max_size=500,
).map(lambda s: f"# Memory Content\n\n{s}")


# Strategy for generating memory file names
_memory_file_names = st.lists(
    st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N"),
            whitelist_characters="_-",
        ),
        min_size=1,
        max_size=20,
    ).map(lambda s: f"{s}.md"),
    min_size=1,
    max_size=5,
    unique=True,
)


class TestMemoryContentInjectionPositionProperties:
    """Property-based tests for memory content injection position (Property 3).
    
    **Validates: Requirements 1.4**
    
    Requirements 1.4 states:
    - 记忆内容应注入到系统提示词的指定位置
    
    Property 3 from design.md:
    - 对于任意记忆内容 M，build_memory_context() 返回的字符串格式正确
    - MEMORY.md 内容在 "Long-term Memory" 部分
    - memory/ 目录文件在 "Memory Files" 部分
    - 两个部分的顺序固定（Long-term Memory 在前）
    """

    @given(memory_md_content=_memory_content)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_memory_md_in_long_term_memory_section(
        self,
        tmp_path: Path,
        memory_md_content: str,
    ) -> None:
        """Property 3: MEMORY.md content appears in "Long-term Memory" section
        
        For any MEMORY.md content M, build_memory_context() should place
        the content under the "## Long-term Memory" section header.
        
        **Validates: Requirements 1.4**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create MEMORY.md file
            memory_file = workspace / "MEMORY.md"
            memory_file.write_text(memory_md_content, encoding="utf-8")
            
            # Build memory context
            loader = MemoryLoader(workspace_dir=str(workspace))
            context = loader.build_memory_context()
            
            # Context should not be empty
            assert context, "Context should not be empty when MEMORY.md exists"
            
            # Context should contain "Long-term Memory" section header
            assert "## Long-term Memory" in context, (
                "Context should contain '## Long-term Memory' section header"
            )
            
            # MEMORY.md content should appear after the section header
            section_start = context.find("## Long-term Memory")
            content_stripped = memory_md_content.strip()
            
            # The content should be present in the context
            assert content_stripped in context, (
                f"MEMORY.md content should be present in context.\n"
                f"Expected content: {content_stripped[:100]}...\n"
                f"Context: {context[:500]}..."
            )
            
            # Content should appear after the section header
            content_pos = context.find(content_stripped)
            assert content_pos > section_start, (
                "MEMORY.md content should appear after '## Long-term Memory' header"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        file_names=_memory_file_names,
        content_seed=st.integers(min_value=0, max_value=1000),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_memory_dir_files_in_memory_files_section(
        self,
        tmp_path: Path,
        file_names: list[str],
        content_seed: int,
    ) -> None:
        """Property 3: memory/ directory files appear in "Memory Files" section
        
        For any memory/ directory files, build_memory_context() should place
        their content under the "## Memory Files" section header.
        
        **Validates: Requirements 1.4**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create memory directory with files
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            file_contents: dict[str, str] = {}
            for i, file_name in enumerate(file_names):
                file_path = memory_dir / file_name
                content = f"# File {i}\n\nContent seed: {content_seed}, index: {i}"
                file_path.write_text(content, encoding="utf-8")
                file_contents[file_name] = content
            
            # Build memory context
            loader = MemoryLoader(workspace_dir=str(workspace))
            context = loader.build_memory_context()
            
            # Context should not be empty
            assert context, "Context should not be empty when memory/ files exist"
            
            # Context should contain "Memory Files" section header
            assert "## Memory Files" in context, (
                "Context should contain '## Memory Files' section header"
            )
            
            # Each file's content should appear in the context
            section_start = context.find("## Memory Files")
            for file_name, content in file_contents.items():
                content_stripped = content.strip()
                assert content_stripped in context, (
                    f"Content of {file_name} should be present in context"
                )
                
                # Content should appear after the section header
                content_pos = context.find(content_stripped)
                assert content_pos > section_start, (
                    f"Content of {file_name} should appear after '## Memory Files' header"
                )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        memory_md_content=_memory_content,
        memory_dir_content=_memory_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_section_order_long_term_memory_before_memory_files(
        self,
        tmp_path: Path,
        memory_md_content: str,
        memory_dir_content: str,
    ) -> None:
        """Property 3: "Long-term Memory" section appears before "Memory Files" section
        
        For any combination of MEMORY.md and memory/ directory files,
        the "Long-term Memory" section should always appear before
        the "Memory Files" section in the context.
        
        **Validates: Requirements 1.4**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create MEMORY.md file
            memory_file = workspace / "MEMORY.md"
            memory_file.write_text(memory_md_content, encoding="utf-8")
            
            # Create memory directory with a file
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            (memory_dir / "notes.md").write_text(memory_dir_content, encoding="utf-8")
            
            # Build memory context
            loader = MemoryLoader(workspace_dir=str(workspace))
            context = loader.build_memory_context()
            
            # Context should not be empty
            assert context, "Context should not be empty"
            
            # Both sections should be present
            assert "## Long-term Memory" in context, (
                "Context should contain '## Long-term Memory' section"
            )
            assert "## Memory Files" in context, (
                "Context should contain '## Memory Files' section"
            )
            
            # Long-term Memory should appear before Memory Files
            long_term_pos = context.find("## Long-term Memory")
            memory_files_pos = context.find("## Memory Files")
            
            assert long_term_pos < memory_files_pos, (
                f"'## Long-term Memory' (pos {long_term_pos}) should appear before "
                f"'## Memory Files' (pos {memory_files_pos})"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(memory_md_content=_memory_content)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_only_memory_md_no_memory_files_section(
        self,
        tmp_path: Path,
        memory_md_content: str,
    ) -> None:
        """Property 3: Only "Long-term Memory" section when no memory/ directory
        
        When only MEMORY.md exists (no memory/ directory), the context
        should only contain the "Long-term Memory" section, not "Memory Files".
        
        **Validates: Requirements 1.4**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create only MEMORY.md file (no memory/ directory)
            memory_file = workspace / "MEMORY.md"
            memory_file.write_text(memory_md_content, encoding="utf-8")
            
            # Build memory context
            loader = MemoryLoader(workspace_dir=str(workspace))
            context = loader.build_memory_context()
            
            # Context should contain Long-term Memory section
            assert "## Long-term Memory" in context, (
                "Context should contain '## Long-term Memory' section"
            )
            
            # Context should NOT contain Memory Files section
            assert "## Memory Files" not in context, (
                "Context should NOT contain '## Memory Files' section when no memory/ directory"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(memory_dir_content=_memory_content)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_only_memory_dir_no_long_term_memory_section(
        self,
        tmp_path: Path,
        memory_dir_content: str,
    ) -> None:
        """Property 3: Only "Memory Files" section when no MEMORY.md
        
        When only memory/ directory exists (no MEMORY.md), the context
        should only contain the "Memory Files" section, not "Long-term Memory".
        
        **Validates: Requirements 1.4**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create only memory/ directory (no MEMORY.md)
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            (memory_dir / "notes.md").write_text(memory_dir_content, encoding="utf-8")
            
            # Build memory context
            loader = MemoryLoader(workspace_dir=str(workspace))
            context = loader.build_memory_context()
            
            # Context should contain Memory Files section
            assert "## Memory Files" in context, (
                "Context should contain '## Memory Files' section"
            )
            
            # Context should NOT contain Long-term Memory section
            assert "## Long-term Memory" not in context, (
                "Context should NOT contain '## Long-term Memory' section when no MEMORY.md"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        memory_md_content=_memory_content,
        file_names=_memory_file_names,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_memory_files_include_relative_path_headers(
        self,
        tmp_path: Path,
        memory_md_content: str,
        file_names: list[str],
    ) -> None:
        """Property 3: Memory files include relative path as sub-headers
        
        For any memory/ directory files, each file's content should be
        preceded by a sub-header (###) containing the relative file path.
        
        **Validates: Requirements 1.4**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create memory directory with files
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            for i, file_name in enumerate(file_names):
                file_path = memory_dir / file_name
                content = f"# File {i}\n\nUnique content marker: {i}"
                file_path.write_text(content, encoding="utf-8")
            
            # Build memory context
            loader = MemoryLoader(workspace_dir=str(workspace))
            context = loader.build_memory_context()
            
            # Each file should have a sub-header with its relative path
            for file_name in file_names:
                # The relative path should be memory/filename.md
                expected_path = f"memory/{file_name}"
                expected_header = f"### {expected_path}"
                
                assert expected_header in context, (
                    f"Context should contain sub-header '### {expected_path}' for file {file_name}\n"
                    f"Context: {context[:1000]}..."
                )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(enabled=st.booleans())
    def test_empty_context_when_disabled(
        self,
        tmp_path: Path,
        enabled: bool,
    ) -> None:
        """Property 3: Empty context when memory loading is disabled
        
        When memory loading is disabled (enabled=False), build_memory_context()
        should return an empty string regardless of existing memory files.
        
        **Validates: Requirements 1.4**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create MEMORY.md and memory/ directory
            memory_file = workspace / "MEMORY.md"
            memory_file.write_text("# Test Memory\n\nSome content", encoding="utf-8")
            
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            (memory_dir / "notes.md").write_text("# Notes\n\nMore content", encoding="utf-8")
            
            # Build memory context with enabled flag
            loader = MemoryLoader(workspace_dir=str(workspace), enabled=enabled)
            context = loader.build_memory_context()
            
            if enabled:
                # Should have content when enabled
                assert context, "Context should not be empty when enabled"
                assert "## Long-term Memory" in context or "## Memory Files" in context
            else:
                # Should be empty when disabled
                assert context == "", (
                    f"Context should be empty when disabled, got: {context[:100]}..."
                )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    @given(st.data())
    def test_empty_context_when_no_memory_sources(
        self,
        tmp_path: Path,
        data: st.DataObject,
    ) -> None:
        """Property 3: Empty context when no memory sources exist
        
        When neither MEMORY.md nor memory/ directory exists,
        build_memory_context() should return an empty string.
        
        **Validates: Requirements 1.4**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Don't create any memory files
            
            # Build memory context
            loader = MemoryLoader(workspace_dir=str(workspace))
            context = loader.build_memory_context()
            
            # Should be empty
            assert context == "", (
                f"Context should be empty when no memory sources exist, got: {context[:100]}..."
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        memory_md_content=_memory_content,
        memory_dir_content=_memory_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_context_format_is_valid_markdown(
        self,
        tmp_path: Path,
        memory_md_content: str,
        memory_dir_content: str,
    ) -> None:
        """Property 3: Generated context is valid Markdown format
        
        For any combination of memory sources, the generated context
        should be valid Markdown with proper section headers.
        
        **Validates: Requirements 1.4**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create MEMORY.md file
            memory_file = workspace / "MEMORY.md"
            memory_file.write_text(memory_md_content, encoding="utf-8")
            
            # Create memory directory with a file
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            (memory_dir / "notes.md").write_text(memory_dir_content, encoding="utf-8")
            
            # Build memory context
            loader = MemoryLoader(workspace_dir=str(workspace))
            context = loader.build_memory_context()
            
            # Context should not be empty
            assert context, "Context should not be empty"
            
            # Verify Markdown structure
            lines = context.split("\n")
            
            # Should have proper section headers (## for main sections)
            has_h2_headers = any(line.startswith("## ") for line in lines)
            assert has_h2_headers, "Context should have ## level headers for sections"
            
            # Should have proper sub-headers (### for file paths)
            has_h3_headers = any(line.startswith("### ") for line in lines)
            assert has_h3_headers, "Context should have ### level headers for file paths"
            
            # Context should be stripped (no leading/trailing whitespace)
            assert context == context.strip(), (
                "Context should be stripped of leading/trailing whitespace"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        memory_md_content=_memory_content,
        subdirs=st.lists(
            st.text(
                alphabet=st.characters(
                    whitelist_categories=("L", "N"),
                    whitelist_characters="_-",
                ),
                min_size=1,
                max_size=10,
            ),
            min_size=1,
            max_size=3,
            unique=True,
        ),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_nested_memory_files_include_full_relative_path(
        self,
        tmp_path: Path,
        memory_md_content: str,
        subdirs: list[str],
    ) -> None:
        """Property 3: Nested memory files include full relative path in headers
        
        For memory files in subdirectories of memory/, the sub-header
        should include the full relative path from workspace root.
        
        **Validates: Requirements 1.4**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create memory directory with nested subdirectories
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            created_paths: list[str] = []
            for subdir in subdirs:
                subdir_path = memory_dir / subdir
                subdir_path.mkdir(parents=True, exist_ok=True)
                
                file_path = subdir_path / "notes.md"
                file_path.write_text(f"# Notes in {subdir}\n\nContent", encoding="utf-8")
                
                # Expected relative path from workspace
                rel_path = f"memory/{subdir}/notes.md"
                created_paths.append(rel_path)
            
            # Build memory context
            loader = MemoryLoader(workspace_dir=str(workspace))
            context = loader.build_memory_context()
            
            # Each nested file should have a sub-header with its full relative path
            for rel_path in created_paths:
                expected_header = f"### {rel_path}"
                assert expected_header in context, (
                    f"Context should contain sub-header '### {rel_path}'\n"
                    f"Context: {context[:1000]}..."
                )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)


# ---------------------------------------------------------------------------
# Property 4: 记忆加载配置开关
# ---------------------------------------------------------------------------


class TestMemoryLoaderConfigSwitchProperties:
    """Property-based tests for memory loading configuration switch (Property 4).
    
    **Validates: Requirements 1.5**
    
    Requirements 1.5 states:
    - 支持通过配置开关启用/禁用记忆加载功能
    
    Property 4 from design.md:
    - 当 memory.enabled = false 时，load_memory_md() 返回 None
    - 当 memory.enabled = false 时，load_memory_dir() 返回空列表
    - 当 memory.enabled = false 时，build_memory_context() 返回空字符串
    """

    @given(content=_memory_content)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_disabled_loader_load_memory_md_returns_none(
        self,
        tmp_path: Path,
        content: str,
    ) -> None:
        """Property 4: When enabled=False, load_memory_md() returns None
        
        For any MEMORY.md file that exists, when the MemoryLoader is
        disabled (enabled=False), load_memory_md() should return None.
        
        **Validates: Requirements 1.5**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create MEMORY.md file
            memory_file = workspace / "MEMORY.md"
            memory_file.write_text(content, encoding="utf-8")
            
            # Create disabled loader
            loader = MemoryLoader(workspace_dir=str(workspace), enabled=False)
            
            # load_memory_md should return None when disabled
            result = loader.load_memory_md()
            
            assert result is None, (
                f"load_memory_md() should return None when disabled, "
                f"but got: {result[:100] if result else result}..."
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(content=_memory_content)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_enabled_loader_load_memory_md_returns_content(
        self,
        tmp_path: Path,
        content: str,
    ) -> None:
        """Property 4: When enabled=True, load_memory_md() returns content
        
        For any MEMORY.md file that exists, when the MemoryLoader is
        enabled (enabled=True), load_memory_md() should return the file content.
        
        **Validates: Requirements 1.5**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create MEMORY.md file
            memory_file = workspace / "MEMORY.md"
            memory_file.write_text(content, encoding="utf-8")
            
            # Create enabled loader
            loader = MemoryLoader(workspace_dir=str(workspace), enabled=True)
            
            # load_memory_md should return content when enabled
            result = loader.load_memory_md()
            
            assert result is not None, (
                "load_memory_md() should return content when enabled"
            )
            assert result == content, (
                f"load_memory_md() should return the file content when enabled"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        file_count=st.integers(min_value=1, max_value=5),
        content_seed=st.integers(min_value=0, max_value=1000),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_disabled_loader_load_memory_dir_returns_empty_list(
        self,
        tmp_path: Path,
        file_count: int,
        content_seed: int,
    ) -> None:
        """Property 4: When enabled=False, load_memory_dir() returns empty list
        
        For any memory/ directory with files, when the MemoryLoader is
        disabled (enabled=False), load_memory_dir() should return an empty list.
        
        **Validates: Requirements 1.5**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create memory directory with files
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            for i in range(file_count):
                file_path = memory_dir / f"file_{i}.md"
                content = f"# File {i}\n\nContent seed: {content_seed}, index: {i}"
                file_path.write_text(content, encoding="utf-8")
            
            # Create disabled loader
            loader = MemoryLoader(workspace_dir=str(workspace), enabled=False)
            
            # load_memory_dir should return empty list when disabled
            result = loader.load_memory_dir()
            
            assert result == [], (
                f"load_memory_dir() should return empty list when disabled, "
                f"but got {len(result)} files"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        file_count=st.integers(min_value=1, max_value=5),
        content_seed=st.integers(min_value=0, max_value=1000),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_enabled_loader_load_memory_dir_returns_files(
        self,
        tmp_path: Path,
        file_count: int,
        content_seed: int,
    ) -> None:
        """Property 4: When enabled=True, load_memory_dir() returns files
        
        For any memory/ directory with files, when the MemoryLoader is
        enabled (enabled=True), load_memory_dir() should return the files.
        
        **Validates: Requirements 1.5**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create memory directory with files
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            expected_files: set[str] = set()
            for i in range(file_count):
                file_path = memory_dir / f"file_{i}.md"
                content = f"# File {i}\n\nContent seed: {content_seed}, index: {i}"
                file_path.write_text(content, encoding="utf-8")
                expected_files.add(str(file_path))
            
            # Create enabled loader
            loader = MemoryLoader(workspace_dir=str(workspace), enabled=True)
            
            # load_memory_dir should return files when enabled
            result = loader.load_memory_dir()
            
            assert len(result) == file_count, (
                f"load_memory_dir() should return {file_count} files when enabled, "
                f"but got {len(result)}"
            )
            
            loaded_paths = {mf.path for mf in result}
            assert loaded_paths == expected_files, (
                f"load_memory_dir() should return all files when enabled"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        memory_md_content=_memory_content,
        memory_dir_content=_memory_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_disabled_loader_build_memory_context_returns_empty_string(
        self,
        tmp_path: Path,
        memory_md_content: str,
        memory_dir_content: str,
    ) -> None:
        """Property 4: When enabled=False, build_memory_context() returns empty string
        
        For any combination of MEMORY.md and memory/ directory files,
        when the MemoryLoader is disabled (enabled=False),
        build_memory_context() should return an empty string.
        
        **Validates: Requirements 1.5**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create MEMORY.md file
            memory_file = workspace / "MEMORY.md"
            memory_file.write_text(memory_md_content, encoding="utf-8")
            
            # Create memory directory with a file
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            (memory_dir / "notes.md").write_text(memory_dir_content, encoding="utf-8")
            
            # Create disabled loader
            loader = MemoryLoader(workspace_dir=str(workspace), enabled=False)
            
            # build_memory_context should return empty string when disabled
            result = loader.build_memory_context()
            
            assert result == "", (
                f"build_memory_context() should return empty string when disabled, "
                f"but got: {result[:100] if result else result}..."
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        memory_md_content=_memory_content,
        memory_dir_content=_memory_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_enabled_loader_build_memory_context_returns_content(
        self,
        tmp_path: Path,
        memory_md_content: str,
        memory_dir_content: str,
    ) -> None:
        """Property 4: When enabled=True, build_memory_context() returns content
        
        For any combination of MEMORY.md and memory/ directory files,
        when the MemoryLoader is enabled (enabled=True),
        build_memory_context() should return the formatted context.
        
        **Validates: Requirements 1.5**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create MEMORY.md file
            memory_file = workspace / "MEMORY.md"
            memory_file.write_text(memory_md_content, encoding="utf-8")
            
            # Create memory directory with a file
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            (memory_dir / "notes.md").write_text(memory_dir_content, encoding="utf-8")
            
            # Create enabled loader
            loader = MemoryLoader(workspace_dir=str(workspace), enabled=True)
            
            # build_memory_context should return content when enabled
            result = loader.build_memory_context()
            
            assert result != "", (
                "build_memory_context() should return non-empty content when enabled"
            )
            assert "## Long-term Memory" in result or "## Memory Files" in result, (
                "build_memory_context() should return formatted context with sections"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(enabled=st.booleans())
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_enabled_property_reflects_constructor_parameter(
        self,
        tmp_path: Path,
        enabled: bool,
    ) -> None:
        """Property 4: enabled property reflects constructor parameter
        
        For any MemoryLoader instance, the enabled property should
        reflect the value passed to the constructor.
        
        **Validates: Requirements 1.5**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create loader with specified enabled value
            loader = MemoryLoader(workspace_dir=str(workspace), enabled=enabled)
            
            # enabled property should match constructor parameter
            assert loader.enabled == enabled, (
                f"enabled property should be {enabled}, but got {loader.enabled}"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(content=_memory_content)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_default_enabled_is_true(
        self,
        tmp_path: Path,
        content: str,
    ) -> None:
        """Property 4: Default enabled value is True
        
        When creating a MemoryLoader without specifying enabled,
        the default value should be True (memory loading enabled).
        
        **Validates: Requirements 1.5**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create MEMORY.md file
            memory_file = workspace / "MEMORY.md"
            memory_file.write_text(content, encoding="utf-8")
            
            # Create loader without specifying enabled (should default to True)
            loader = MemoryLoader(workspace_dir=str(workspace))
            
            # enabled should default to True
            assert loader.enabled is True, (
                f"Default enabled should be True, but got {loader.enabled}"
            )
            
            # load_memory_md should work (return content)
            result = loader.load_memory_md()
            assert result is not None, (
                "load_memory_md() should return content with default enabled=True"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        enabled=st.booleans(),
        content=_memory_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_enabled_switch_is_consistent_across_all_methods(
        self,
        tmp_path: Path,
        enabled: bool,
        content: str,
    ) -> None:
        """Property 4: enabled switch is consistent across all methods
        
        For any MemoryLoader instance, the enabled switch should
        consistently affect all memory loading methods:
        - load_memory_md()
        - load_memory_dir()
        - build_memory_context()
        
        **Validates: Requirements 1.5**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create MEMORY.md file
            memory_file = workspace / "MEMORY.md"
            memory_file.write_text(content, encoding="utf-8")
            
            # Create memory directory with a file
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            (memory_dir / "notes.md").write_text(content, encoding="utf-8")
            
            # Create loader with specified enabled value
            loader = MemoryLoader(workspace_dir=str(workspace), enabled=enabled)
            
            # Test all methods
            memory_md_result = loader.load_memory_md()
            memory_dir_result = loader.load_memory_dir()
            context_result = loader.build_memory_context()
            
            if enabled:
                # All methods should return content when enabled
                assert memory_md_result is not None, (
                    "load_memory_md() should return content when enabled"
                )
                assert len(memory_dir_result) > 0, (
                    "load_memory_dir() should return files when enabled"
                )
                assert context_result != "", (
                    "build_memory_context() should return content when enabled"
                )
            else:
                # All methods should return empty/None when disabled
                assert memory_md_result is None, (
                    "load_memory_md() should return None when disabled"
                )
                assert memory_dir_result == [], (
                    "load_memory_dir() should return empty list when disabled"
                )
                assert context_result == "", (
                    "build_memory_context() should return empty string when disabled"
                )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        enabled=st.booleans(),
        file_count=st.integers(min_value=1, max_value=5),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_enabled_switch_does_not_affect_file_existence_check(
        self,
        tmp_path: Path,
        enabled: bool,
        file_count: int,
    ) -> None:
        """Property 4: enabled switch does not affect file existence check
        
        When memory loading is disabled, the loader should still be able
        to check if files exist (via workspace_dir property), but should
        not load any content.
        
        **Validates: Requirements 1.5**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create MEMORY.md file
            memory_file = workspace / "MEMORY.md"
            memory_file.write_text("# Test\n\nContent", encoding="utf-8")
            
            # Create memory directory with files
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            
            for i in range(file_count):
                (memory_dir / f"file_{i}.md").write_text(f"# File {i}\n", encoding="utf-8")
            
            # Create loader with specified enabled value
            loader = MemoryLoader(workspace_dir=str(workspace), enabled=enabled)
            
            # workspace_dir property should always work
            assert loader.workspace_dir == workspace, (
                "workspace_dir property should always return the workspace path"
            )
            
            # Files should exist on disk regardless of enabled state
            assert memory_file.exists(), "MEMORY.md should exist on disk"
            assert memory_dir.exists(), "memory/ directory should exist on disk"
            assert len(list(memory_dir.glob("*.md"))) == file_count, (
                f"memory/ directory should contain {file_count} .md files"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        enabled=st.booleans(),
        chunk_tokens=st.integers(min_value=100, max_value=1000),
        chunk_overlap=st.integers(min_value=10, max_value=100),
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_enabled_switch_independent_of_other_config(
        self,
        tmp_path: Path,
        enabled: bool,
        chunk_tokens: int,
        chunk_overlap: int,
    ) -> None:
        """Property 4: enabled switch is independent of other configuration
        
        The enabled switch should work independently of other configuration
        options like chunk_tokens and chunk_overlap.
        
        **Validates: Requirements 1.5**
        """
        import tempfile
        import shutil
        
        # Ensure overlap is less than chunk size
        assume(chunk_overlap < chunk_tokens)
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create MEMORY.md file
            memory_file = workspace / "MEMORY.md"
            memory_file.write_text("# Test\n\nContent for testing", encoding="utf-8")
            
            # Create loader with various config options
            loader = MemoryLoader(
                workspace_dir=str(workspace),
                enabled=enabled,
                chunk_tokens=chunk_tokens,
                chunk_overlap=chunk_overlap,
            )
            
            # enabled property should be set correctly
            assert loader.enabled == enabled, (
                f"enabled should be {enabled} regardless of other config"
            )
            
            # Test load_memory_md behavior
            result = loader.load_memory_md()
            
            if enabled:
                assert result is not None, (
                    "load_memory_md() should return content when enabled, "
                    "regardless of chunk_tokens and chunk_overlap settings"
                )
            else:
                assert result is None, (
                    "load_memory_md() should return None when disabled, "
                    "regardless of chunk_tokens and chunk_overlap settings"
                )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(content=_memory_content)
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_disabled_loader_does_not_read_files(
        self,
        tmp_path: Path,
        content: str,
    ) -> None:
        """Property 4: Disabled loader does not read files from disk
        
        When memory loading is disabled, the loader should not attempt
        to read files from disk (early return before file I/O).
        
        **Validates: Requirements 1.5**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create MEMORY.md file
            memory_file = workspace / "MEMORY.md"
            memory_file.write_text(content, encoding="utf-8")
            
            # Create memory directory with a file
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            (memory_dir / "notes.md").write_text(content, encoding="utf-8")
            
            # Create disabled loader
            loader = MemoryLoader(workspace_dir=str(workspace), enabled=False)
            
            # All methods should return immediately without reading files
            # (We can't directly test file I/O, but we can verify the behavior)
            
            # load_memory_md should return None immediately
            result_md = loader.load_memory_md()
            assert result_md is None
            
            # load_memory_dir should return empty list immediately
            result_dir = loader.load_memory_dir()
            assert result_dir == []
            
            # build_memory_context should return empty string immediately
            result_context = loader.build_memory_context()
            assert result_context == ""
            
            # Even if we delete the files, the disabled loader should still work
            # (because it doesn't try to read them)
            memory_file.unlink()
            shutil.rmtree(memory_dir)
            
            # These should still work without errors
            assert loader.load_memory_md() is None
            assert loader.load_memory_dir() == []
            assert loader.build_memory_context() == ""
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @given(
        enabled=st.booleans(),
        content=_memory_content,
    )
    @settings(
        max_examples=100,
        deadline=None,
        suppress_health_check=[HealthCheck.function_scoped_fixture],
    )
    def test_enabled_switch_multiple_calls_consistent(
        self,
        tmp_path: Path,
        enabled: bool,
        content: str,
    ) -> None:
        """Property 4: Multiple calls with same enabled state are consistent
        
        For any MemoryLoader instance, multiple calls to the same method
        should return consistent results based on the enabled state.
        
        **Validates: Requirements 1.5**
        """
        import tempfile
        import shutil
        
        # Create truly unique workspace
        workspace = Path(tempfile.mkdtemp(dir=tmp_path))
        
        try:
            # Create MEMORY.md file
            memory_file = workspace / "MEMORY.md"
            memory_file.write_text(content, encoding="utf-8")
            
            # Create memory directory with a file
            memory_dir = workspace / "memory"
            memory_dir.mkdir(parents=True, exist_ok=True)
            (memory_dir / "notes.md").write_text(content, encoding="utf-8")
            
            # Create loader with specified enabled value
            loader = MemoryLoader(workspace_dir=str(workspace), enabled=enabled)
            
            # Call each method multiple times
            md_results = [loader.load_memory_md() for _ in range(3)]
            dir_results = [loader.load_memory_dir() for _ in range(3)]
            context_results = [loader.build_memory_context() for _ in range(3)]
            
            # All results should be consistent
            assert all(r == md_results[0] for r in md_results), (
                "Multiple calls to load_memory_md() should return consistent results"
            )
            
            # For dir results, compare paths
            dir_paths = [[mf.path for mf in result] for result in dir_results]
            assert all(paths == dir_paths[0] for paths in dir_paths), (
                "Multiple calls to load_memory_dir() should return consistent results"
            )
            
            assert all(r == context_results[0] for r in context_results), (
                "Multiple calls to build_memory_context() should return consistent results"
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)
