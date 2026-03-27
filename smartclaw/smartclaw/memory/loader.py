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
        """Scan memory/ directory for all .md files.
        
        Returns:
            List of MemoryFile objects.
        """
        # TODO: Implement in task 2.7
        return []

    def chunk_markdown(self, content: str, file_path: str) -> list[MemoryChunk]:
        """Chunk Markdown content.
        
        Args:
            content: Markdown text content.
            file_path: Source file path.
            
        Returns:
            List of MemoryChunk objects.
        """
        # TODO: Implement in task 2.4
        return []

    def build_memory_context(self) -> str:
        """Build memory context string for system prompt injection.
        
        Returns:
            Formatted memory context string.
        """
        # TODO: Implement in task 2.10
        return ""
