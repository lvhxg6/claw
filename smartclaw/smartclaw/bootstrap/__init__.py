"""Bootstrap module for loading SOUL.md, USER.md, and TOOLS.md files.

This module provides the BootstrapLoader class for loading bootstrap files
that define Agent identity and behavior.
"""

from smartclaw.bootstrap.loader import (
    BootstrapFile,
    BootstrapFileType,
    BootstrapLoader,
    MAX_BOOTSTRAP_FILE_SIZE,
)

__all__ = [
    "BootstrapFile",
    "BootstrapFileType",
    "BootstrapLoader",
    "MAX_BOOTSTRAP_FILE_SIZE",
]
