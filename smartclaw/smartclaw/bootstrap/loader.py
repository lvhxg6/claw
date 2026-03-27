"""Bootstrap file loader for SOUL.md, USER.md, and TOOLS.md files.

This module provides the BootstrapLoader class for loading bootstrap files
that define Agent identity and behavior. Supports multi-level directory
lookup (workspace > global) with file size limits.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import structlog

logger = structlog.get_logger(component="bootstrap.loader")

# File size limit: 512KB
MAX_BOOTSTRAP_FILE_SIZE = 512 * 1024


class BootstrapFileType(Enum):
    """Bootstrap file types.
    
    Defines the supported bootstrap file types:
    - SOUL: Agent personality definition (SOUL.md)
    - USER: User information (USER.md)
    - TOOLS: Tool configuration (TOOLS.md)
    """
    SOUL = "SOUL.md"
    USER = "USER.md"
    TOOLS = "TOOLS.md"


@dataclass
class BootstrapFile:
    """Bootstrap file data structure.
    
    Represents a loaded bootstrap file with its metadata and content.
    
    Attributes:
        file_type: The type of bootstrap file (SOUL, USER, or TOOLS).
        path: The absolute path to the file.
        source: The source level ("workspace" or "global").
        content: The file content as a string.
        mtime: The file modification time (Unix timestamp).
        size: The file size in bytes.
    """
    file_type: BootstrapFileType
    path: str
    source: str  # "workspace" or "global"
    content: str
    mtime: float
    size: int


class BootstrapLoader:
    """Bootstrap file loader for SOUL.md, USER.md, and TOOLS.md files.
    
    Loads bootstrap files from workspace and global directories with
    workspace-level files taking priority over global-level files.
    Implements file size limits and caching based on modification time.
    
    Attributes:
        workspace_dir: The workspace directory path (optional).
        global_dir: The global directory path (default: ~/.smartclaw).
        enabled: Whether bootstrap loading is enabled.
    """

    def __init__(
        self,
        workspace_dir: str | None = None,
        global_dir: str = "~/.smartclaw",
        enabled: bool = True,
    ) -> None:
        """Initialize the BootstrapLoader.
        
        Args:
            workspace_dir: Path to the workspace directory (optional).
            global_dir: Path to the global directory (default: ~/.smartclaw).
            enabled: Whether bootstrap loading is enabled.
        """
        self._workspace_dir = (
            Path(workspace_dir).expanduser().resolve() if workspace_dir else None
        )
        self._global_dir = Path(global_dir).expanduser().resolve()
        self._enabled = enabled
        self._cache: dict[BootstrapFileType, BootstrapFile] = {}

    @property
    def workspace_dir(self) -> Path | None:
        """Get the workspace directory path."""
        return self._workspace_dir

    @property
    def global_dir(self) -> Path:
        """Get the global directory path."""
        return self._global_dir

    @property
    def enabled(self) -> bool:
        """Check if bootstrap loading is enabled."""
        return self._enabled

    def load_file(self, file_type: BootstrapFileType) -> BootstrapFile | None:
        """Load a specific bootstrap file.
        
        Searches for the file in workspace directory first, then global
        directory. Workspace-level files take priority over global-level.
        
        Args:
            file_type: The type of bootstrap file to load.
            
        Returns:
            BootstrapFile object if found and valid, None otherwise.
            
        Notes:
            - File size is limited to 512KB (MAX_BOOTSTRAP_FILE_SIZE)
            - Files exceeding the size limit are rejected with a warning
            - Binary content (containing null bytes) is rejected
            - Uses caching based on file modification time (mtime)
        """
        if not self._enabled:
            logger.debug(
                "bootstrap_loader_disabled",
                file_type=file_type.value,
            )
            return None

        filename = file_type.value

        # Check cache first
        if file_type in self._cache:
            cached = self._cache[file_type]
            # Verify cache is still valid by checking mtime
            try:
                current_mtime = Path(cached.path).stat().st_mtime
                if current_mtime == cached.mtime:
                    logger.debug(
                        "bootstrap_file_cache_hit",
                        file_type=file_type.value,
                        path=cached.path,
                    )
                    return cached
            except OSError:
                # File may have been deleted, invalidate cache
                del self._cache[file_type]

        # Search in workspace directory first (higher priority)
        if self._workspace_dir:
            result = self._try_load_file(
                self._workspace_dir / filename,
                file_type,
                source="workspace",
            )
            if result:
                self._cache[file_type] = result
                return result

        # Search in global directory
        result = self._try_load_file(
            self._global_dir / filename,
            file_type,
            source="global",
        )
        if result:
            self._cache[file_type] = result
            return result

        logger.debug(
            "bootstrap_file_not_found",
            file_type=file_type.value,
            workspace_dir=str(self._workspace_dir) if self._workspace_dir else None,
            global_dir=str(self._global_dir),
        )
        return None

    def _try_load_file(
        self,
        file_path: Path,
        file_type: BootstrapFileType,
        source: str,
    ) -> BootstrapFile | None:
        """Try to load a bootstrap file from a specific path.
        
        Args:
            file_path: The path to the file.
            file_type: The type of bootstrap file.
            source: The source level ("workspace" or "global").
            
        Returns:
            BootstrapFile object if successful, None otherwise.
        """
        if not file_path.exists():
            return None

        if not file_path.is_file():
            logger.warning(
                "bootstrap_path_not_file",
                path=str(file_path),
                file_type=file_type.value,
            )
            return None

        # Get file stats
        try:
            stat = file_path.stat()
            file_size = stat.st_size
            file_mtime = stat.st_mtime
        except PermissionError:
            logger.warning(
                "bootstrap_file_permission_denied",
                path=str(file_path),
                file_type=file_type.value,
            )
            return None
        except OSError as e:
            logger.warning(
                "bootstrap_file_stat_error",
                path=str(file_path),
                file_type=file_type.value,
                error=str(e),
            )
            return None

        # Check file size limit
        if file_size > MAX_BOOTSTRAP_FILE_SIZE:
            logger.warning(
                "bootstrap_file_too_large",
                path=str(file_path),
                file_type=file_type.value,
                size=file_size,
                max_size=MAX_BOOTSTRAP_FILE_SIZE,
            )
            return None

        # Read file content
        try:
            content = file_path.read_text(encoding="utf-8")
        except PermissionError:
            logger.warning(
                "bootstrap_file_read_permission_denied",
                path=str(file_path),
                file_type=file_type.value,
            )
            return None
        except UnicodeDecodeError:
            logger.warning(
                "bootstrap_file_decode_error",
                path=str(file_path),
                file_type=file_type.value,
            )
            return None
        except OSError as e:
            logger.warning(
                "bootstrap_file_read_error",
                path=str(file_path),
                file_type=file_type.value,
                error=str(e),
            )
            return None

        # Check for binary content (null bytes)
        if "\x00" in content:
            logger.warning(
                "bootstrap_file_binary_content",
                path=str(file_path),
                file_type=file_type.value,
            )
            return None

        logger.info(
            "bootstrap_file_loaded",
            path=str(file_path),
            file_type=file_type.value,
            source=source,
            size=file_size,
        )

        return BootstrapFile(
            file_type=file_type,
            path=str(file_path),
            source=source,
            content=content,
            mtime=file_mtime,
            size=file_size,
        )

    def load_all(self) -> dict[BootstrapFileType, BootstrapFile]:
        """Load all bootstrap files.
        
        Loads SOUL.md, USER.md, and TOOLS.md files from workspace and
        global directories. Workspace-level files take priority.
        
        Returns:
            Dictionary mapping file types to BootstrapFile objects.
            Only includes files that were successfully loaded.
        """
        if not self._enabled:
            logger.debug("bootstrap_loader_disabled_load_all")
            return {}

        result: dict[BootstrapFileType, BootstrapFile] = {}

        for file_type in BootstrapFileType:
            bootstrap_file = self.load_file(file_type)
            if bootstrap_file:
                result[file_type] = bootstrap_file

        logger.info(
            "bootstrap_files_loaded",
            count=len(result),
            types=[ft.value for ft in result.keys()],
        )

        return result

    def get_soul_content(self) -> str:
        """Get SOUL.md content for system prompt header.
        
        Returns:
            SOUL.md content string, or empty string if not found.
        """
        bootstrap_file = self.load_file(BootstrapFileType.SOUL)
        return bootstrap_file.content if bootstrap_file else ""

    def get_user_content(self) -> str:
        """Get USER.md content for user context section.
        
        Returns:
            USER.md content string, or empty string if not found.
        """
        bootstrap_file = self.load_file(BootstrapFileType.USER)
        return bootstrap_file.content if bootstrap_file else ""

    def get_tools_content(self) -> str:
        """Get TOOLS.md content for tools description section.
        
        Returns:
            TOOLS.md content string, or empty string if not found.
        """
        bootstrap_file = self.load_file(BootstrapFileType.TOOLS)
        return bootstrap_file.content if bootstrap_file else ""

    def invalidate_cache(self, file_type: BootstrapFileType | None = None) -> None:
        """Invalidate the cache.
        
        Args:
            file_type: Specific file type to invalidate, or None to clear all.
        """
        if file_type is None:
            self._cache.clear()
            logger.debug("bootstrap_cache_cleared_all")
        elif file_type in self._cache:
            del self._cache[file_type]
            logger.debug(
                "bootstrap_cache_cleared",
                file_type=file_type.value,
            )
