"""Memory loader for MEMORY.md and memory/ directory files.

This module provides the MemoryLoader class for loading long-term memory
from MEMORY.md files and the memory/ directory in the workspace.
"""

from dataclasses import dataclass, field
from pathlib import Path
import hashlib
import structlog

logger = structlog.get_logger(component="memory.loader")

# File size limits
MAX_MEMORY_FILE_SIZE = 2 * 1024 * 1024  # 2MB
MAX_MEMORY_DIR_SIZE = 50 * 1024 * 1024  # 50MB


@dataclass
class MemoryChunk:
    """Memory chunk data structure.
    
    Represents a chunk of text from a memory file, used for
    vectorization and retrieval.
    """
    file_path: str          # Source file path
    start_line: int         # Start line number (1-indexed)
    end_line: int           # End line number (1-indexed)
    text: str               # Chunk text content
    hash: str               # Content hash (SHA-256 first 16 chars)
    embedding_input: str    # Text input for vectorization


@dataclass
class MemoryFile:
    """Memory file metadata.
    
    Represents a loaded memory file with its content and chunks.
    """
    path: str               # File path
    mtime: float            # Modification time
    size: int               # File size in bytes
    content: str            # File content
    chunks: list[MemoryChunk] = field(default_factory=list)


class MemoryLoader:
    """Memory loader for MEMORY.md and memory/ directory files.
    
    Loads Markdown files from the workspace for long-term memory support.
    Supports case-insensitive file name lookup, file size limits, and
    content truncation.
    
    Attributes:
        workspace_dir: The workspace directory path.
        chunk_tokens: Number of tokens per chunk (default 512).
        chunk_overlap: Number of overlapping tokens between chunks (default 64).
        enabled: Whether memory loading is enabled.
    """

    def __init__(
        self,
        workspace_dir: str,
        chunk_tokens: int = 512,
        chunk_overlap: int = 64,
        enabled: bool = True,
    ) -> None:
        """Initialize the MemoryLoader.
        
        Args:
            workspace_dir: Path to the workspace directory.
            chunk_tokens: Number of tokens per chunk.
            chunk_overlap: Number of overlapping tokens between chunks.
            enabled: Whether memory loading is enabled.
        """
        self._workspace_dir = Path(workspace_dir).expanduser().resolve()
        self._chunk_tokens = chunk_tokens
        self._chunk_overlap = chunk_overlap
        self._enabled = enabled
        self._cache: dict[str, MemoryFile] = {}

    @property
    def workspace_dir(self) -> Path:
        """Get the workspace directory path."""
        return self._workspace_dir

    @property
    def enabled(self) -> bool:
        """Check if memory loading is enabled."""
        return self._enabled

    def load_memory_md(self) -> str | None:
        """Load MEMORY.md file content.
        
        Scans the workspace root directory for MEMORY.md or memory.md file
        (case-insensitive, uppercase version takes priority).
        
        Returns:
            File content string, or None if file does not exist.
            
        Notes:
            - Uppercase MEMORY.md takes priority over lowercase memory.md
            - File size is limited to 2MB, content is truncated if exceeded
            - Logs warning when file is truncated
            - Logs INFO when file is loaded successfully
            - Silently skips if file does not exist (returns None)
        """
        if not self._enabled:
            logger.debug("memory_loader_disabled", workspace=str(self._workspace_dir))
            return None

        # Find MEMORY.md file (case-insensitive, uppercase priority)
        memory_file_path = self._find_memory_md_file()
        if memory_file_path is None:
            logger.debug(
                "memory_md_not_found",
                workspace=str(self._workspace_dir),
            )
            return None

        # Read file content with size limit
        try:
            file_size = memory_file_path.stat().st_size
            
            # Check file size limit
            if file_size > MAX_MEMORY_FILE_SIZE:
                logger.warning(
                    "memory_md_truncated",
                    path=str(memory_file_path),
                    original_size=file_size,
                    max_size=MAX_MEMORY_FILE_SIZE,
                )
                # Read only up to the limit
                with memory_file_path.open("r", encoding="utf-8") as f:
                    content = f.read(MAX_MEMORY_FILE_SIZE)
                # Truncate at last complete line to maintain valid Markdown
                content = self._truncate_at_line_boundary(content)
            else:
                content = memory_file_path.read_text(encoding="utf-8")

            logger.info(
                "memory_md_loaded",
                path=str(memory_file_path),
                size=len(content),
            )
            return content

        except PermissionError:
            logger.warning(
                "memory_md_permission_denied",
                path=str(memory_file_path),
            )
            return None
        except UnicodeDecodeError:
            logger.warning(
                "memory_md_decode_error",
                path=str(memory_file_path),
            )
            return None
        except OSError as e:
            logger.warning(
                "memory_md_read_error",
                path=str(memory_file_path),
                error=str(e),
            )
            return None

    def _find_memory_md_file(self) -> Path | None:
        """Find MEMORY.md file in workspace (case-insensitive, uppercase priority).
        
        Returns:
            Path to the memory file, or None if not found.
            
        Notes:
            On case-insensitive file systems (like macOS), we need to check
            the actual file name to determine priority.
        """
        if not self._workspace_dir.exists():
            return None

        # Collect all matching files with their actual names
        matching_files: list[Path] = []
        try:
            for item in self._workspace_dir.iterdir():
                if item.is_file() and item.name.lower() == "memory.md":
                    matching_files.append(item)
        except PermissionError:
            logger.warning(
                "workspace_permission_denied",
                workspace=str(self._workspace_dir),
            )
            return None

        if not matching_files:
            return None

        # Sort by priority: exact "MEMORY.md" first, then "memory.md", then others
        def priority_key(path: Path) -> tuple[int, str]:
            name = path.name
            if name == "MEMORY.md":
                return (0, name)
            elif name == "memory.md":
                return (1, name)
            else:
                return (2, name)

        matching_files.sort(key=priority_key)
        return matching_files[0]

    def _truncate_at_line_boundary(self, content: str) -> str:
        """Truncate content at the last complete line boundary.
        
        Args:
            content: The content to truncate.
            
        Returns:
            Content truncated at the last newline character.
        """
        if not content:
            return content
        
        # Find the last newline
        last_newline = content.rfind("\n")
        if last_newline == -1:
            # No newline found, return as-is
            return content
        
        return content[:last_newline + 1]

    def compute_hash(self, text: str) -> str:
        """Compute content hash (SHA-256 first 16 characters).
        
        Args:
            text: The text to hash.
            
        Returns:
            First 16 characters of the SHA-256 hash.
        """
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def load_memory_dir(self) -> list[MemoryFile]:
        """Scan memory/ directory for all .md files recursively.
        
        Scans the `<workspace>/memory/` directory recursively for all `.md` files.
        Tracks total size and stops loading when the 50MB limit is exceeded.
        
        Returns:
            List of MemoryFile objects with path, mtime, size, and content.
            
        Notes:
            - Recursively scans all subdirectories
            - Total directory size is limited to 50MB (MAX_MEMORY_DIR_SIZE)
            - When limit is exceeded, logs warning and skips remaining files
            - Handles permission errors and other OS errors gracefully
            - Files are sorted by path for deterministic ordering
            - Logs INFO when scanning completes with file count and total size
        """
        if not self._enabled:
            logger.debug("memory_loader_disabled", workspace=str(self._workspace_dir))
            return []

        memory_dir = self._workspace_dir / "memory"
        
        if not memory_dir.exists():
            logger.debug(
                "memory_dir_not_found",
                path=str(memory_dir),
            )
            return []

        if not memory_dir.is_dir():
            logger.warning(
                "memory_dir_not_directory",
                path=str(memory_dir),
            )
            return []

        # Collect all .md files recursively
        md_files: list[Path] = []
        try:
            md_files = self._scan_md_files_recursive(memory_dir)
        except PermissionError:
            logger.warning(
                "memory_dir_permission_denied",
                path=str(memory_dir),
            )
            return []
        except OSError as e:
            logger.warning(
                "memory_dir_scan_error",
                path=str(memory_dir),
                error=str(e),
            )
            return []

        if not md_files:
            logger.debug(
                "memory_dir_no_md_files",
                path=str(memory_dir),
            )
            return []

        # Sort files by path for deterministic ordering
        md_files.sort(key=lambda p: str(p))

        # Load files with size limit tracking
        memory_files: list[MemoryFile] = []
        total_size = 0
        skipped_count = 0
        limit_exceeded = False

        for file_path in md_files:
            # Get file stats
            try:
                stat = file_path.stat()
                file_size = stat.st_size
                file_mtime = stat.st_mtime
            except PermissionError:
                logger.warning(
                    "memory_file_permission_denied",
                    path=str(file_path),
                )
                continue
            except OSError as e:
                logger.warning(
                    "memory_file_stat_error",
                    path=str(file_path),
                    error=str(e),
                )
                continue

            # Check if adding this file would exceed the limit
            if total_size + file_size > MAX_MEMORY_DIR_SIZE:
                if not limit_exceeded:
                    # Log warning only once when limit is first exceeded
                    logger.warning(
                        "memory_dir_size_limit_exceeded",
                        path=str(memory_dir),
                        current_size=total_size,
                        file_size=file_size,
                        max_size=MAX_MEMORY_DIR_SIZE,
                        skipping_file=str(file_path),
                    )
                    limit_exceeded = True
                skipped_count += 1
                continue

            # Read file content
            try:
                content = file_path.read_text(encoding="utf-8")
            except PermissionError:
                logger.warning(
                    "memory_file_read_permission_denied",
                    path=str(file_path),
                )
                continue
            except UnicodeDecodeError:
                logger.warning(
                    "memory_file_decode_error",
                    path=str(file_path),
                )
                continue
            except OSError as e:
                logger.warning(
                    "memory_file_read_error",
                    path=str(file_path),
                    error=str(e),
                )
                continue

            # Create MemoryFile object
            memory_file = MemoryFile(
                path=str(file_path),
                mtime=file_mtime,
                size=file_size,
                content=content,
            )
            memory_files.append(memory_file)
            total_size += file_size

        # Log summary
        if skipped_count > 0:
            logger.warning(
                "memory_dir_files_skipped",
                path=str(memory_dir),
                skipped_count=skipped_count,
                loaded_count=len(memory_files),
                total_size=total_size,
            )
        
        logger.info(
            "memory_dir_loaded",
            path=str(memory_dir),
            file_count=len(memory_files),
            total_size=total_size,
        )

        return memory_files

    def _scan_md_files_recursive(self, directory: Path) -> list[Path]:
        """Recursively scan directory for .md files.
        
        Args:
            directory: The directory to scan.
            
        Returns:
            List of Path objects for all .md files found.
            
        Raises:
            PermissionError: If directory cannot be accessed.
            OSError: If other OS error occurs during scanning.
        """
        md_files: list[Path] = []
        
        try:
            for item in directory.iterdir():
                if item.is_file() and item.suffix.lower() == ".md":
                    md_files.append(item)
                elif item.is_dir():
                    # Recursively scan subdirectories
                    try:
                        md_files.extend(self._scan_md_files_recursive(item))
                    except PermissionError:
                        logger.warning(
                            "memory_subdir_permission_denied",
                            path=str(item),
                        )
                        # Continue scanning other directories
                    except OSError as e:
                        logger.warning(
                            "memory_subdir_scan_error",
                            path=str(item),
                            error=str(e),
                        )
                        # Continue scanning other directories
        except PermissionError:
            raise
        except OSError:
            raise

        return md_files

    def chunk_markdown(self, content: str, file_path: str) -> list[MemoryChunk]:
        """Chunk Markdown content by tokens.
        
        Splits content into overlapping chunks based on token count.
        Uses word-based approximation for token counting (1 word ≈ 1.3 tokens).
        
        Args:
            content: Markdown text content.
            file_path: Source file path.
            
        Returns:
            List of MemoryChunk objects with computed hashes and line tracking.
            
        Notes:
            - Chunks are created with overlap to maintain context continuity
            - Each chunk tracks its start and end line numbers (1-indexed)
            - Hash is computed using SHA-256 (first 16 characters)
            - embedding_input is set to the chunk text for vectorization
        """
        if not content:
            return []
        
        # Split content into lines for line number tracking
        lines = content.split("\n")
        
        # Tokenize content using word-based approximation
        # We'll track words with their line numbers
        word_line_map: list[tuple[str, int]] = []  # (word, line_number)
        
        for line_idx, line in enumerate(lines):
            line_num = line_idx + 1  # 1-indexed
            words = line.split()
            for word in words:
                word_line_map.append((word, line_num))
            # Add newline marker to preserve line structure
            if line_idx < len(lines) - 1:
                word_line_map.append(("\n", line_num))
        
        if not word_line_map:
            # Content has no words (empty or whitespace only)
            return []
        
        # Convert token counts to word counts (approximation: 1 word ≈ 1.3 tokens)
        # So chunk_tokens=512 ≈ 394 words, chunk_overlap=64 ≈ 49 words
        words_per_chunk = max(1, int(self._chunk_tokens / 1.3))
        overlap_words = max(0, int(self._chunk_overlap / 1.3))
        
        chunks: list[MemoryChunk] = []
        start_idx = 0
        
        while start_idx < len(word_line_map):
            # Calculate end index for this chunk
            end_idx = min(start_idx + words_per_chunk, len(word_line_map))
            
            # Extract words for this chunk
            chunk_words = word_line_map[start_idx:end_idx]
            
            # Build chunk text
            chunk_text_parts: list[str] = []
            for word, _ in chunk_words:
                if word == "\n":
                    chunk_text_parts.append("\n")
                else:
                    if chunk_text_parts and chunk_text_parts[-1] != "\n":
                        chunk_text_parts.append(" ")
                    chunk_text_parts.append(word)
            
            chunk_text = "".join(chunk_text_parts).strip()
            
            if not chunk_text:
                # Skip empty chunks
                start_idx = end_idx
                continue
            
            # Determine start and end line numbers
            start_line = chunk_words[0][1]
            end_line = chunk_words[-1][1]
            
            # Compute hash
            chunk_hash = self.compute_hash(chunk_text)
            
            # Create chunk
            chunk = MemoryChunk(
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
                text=chunk_text,
                hash=chunk_hash,
                embedding_input=chunk_text,
            )
            chunks.append(chunk)
            
            # Move to next chunk with overlap
            if end_idx >= len(word_line_map):
                break
            
            # Calculate next start position with overlap
            step = words_per_chunk - overlap_words
            if step <= 0:
                step = 1  # Ensure progress
            start_idx += step
        
        logger.debug(
            "markdown_chunked",
            file_path=file_path,
            content_length=len(content),
            chunk_count=len(chunks),
            chunk_tokens=self._chunk_tokens,
            chunk_overlap=self._chunk_overlap,
        )
        
        return chunks

    def build_memory_context(self) -> str:
        """Build memory context string for system prompt injection.
        
        Returns:
            Formatted memory context string.
        """
        # TODO: Implement in task 2.10
        return ""
