"""SkillsWatcher — File watcher for SKILL.md hot-reload.

This module provides the SkillsWatcher class for monitoring SKILL.md file
changes using the watchdog library. Supports watching both workspace and
global skill directories with debounce mechanism.

Validates: Requirements 3.1, 3.2
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

import structlog

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer

    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    # Provide stub types for type checking when watchdog is not installed
    FileSystemEvent = object  # type: ignore[misc, assignment]
    FileSystemEventHandler = object  # type: ignore[misc, assignment]
    Observer = object  # type: ignore[misc, assignment]

logger = structlog.get_logger(component="skills.watcher")

# Default debounce time in milliseconds
DEFAULT_DEBOUNCE_MS = 250

# Directories to ignore when watching for file changes
IGNORED_DIRS = {
    ".git",
    "__pycache__",
    "venv",
    ".venv",
    "node_modules",
    ".idea",
    ".vscode",
}

# Skill file names to watch (case-insensitive)
SKILL_FILE_NAMES = {"skill.md", "skill.yaml"}


class SkillsWatcher:
    """Skills file watcher for hot-reload functionality.

    Monitors SKILL.md and skill.yaml file changes in workspace and global
    skill directories using the watchdog library. Implements debounce
    mechanism to prevent excessive reloads.

    Attributes:
        workspace_dir: The workspace skills directory path (optional).
        global_dir: The global skills directory path.
        debounce_ms: Debounce time in milliseconds.
        enabled: Whether the watcher is enabled.

    Validates: Requirements 3.1, 3.2
    """

    def __init__(
        self,
        workspace_dir: str | None = None,
        global_dir: str = "~/.smartclaw/skills",
        debounce_ms: int = DEFAULT_DEBOUNCE_MS,
        on_reload: Callable[[], None] | None = None,
        enabled: bool = True,
    ) -> None:
        """Initialize the SkillsWatcher.

        Args:
            workspace_dir: Path to the workspace directory (optional).
                           Skills are expected in {workspace_dir}/skills/.
            global_dir: Path to the global skills directory.
            debounce_ms: Debounce time in milliseconds (default: 250).
            on_reload: Callback function to invoke on reload.
            enabled: Whether the watcher is enabled.
        """
        # Workspace skills directory: {workspace}/skills/
        self._workspace_dir = (
            Path(workspace_dir).expanduser().resolve() / "skills"
            if workspace_dir
            else None
        )
        self._global_dir = Path(global_dir).expanduser().resolve()
        self._debounce_ms = debounce_ms
        self._on_reload = on_reload
        self._enabled = enabled

        self._observer: Observer | None = None
        self._version: int = 0
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._running = False
        self._pending_path: str | None = None

    @property
    def workspace_dir(self) -> Path | None:
        """Get the workspace skills directory path."""
        return self._workspace_dir

    @property
    def global_dir(self) -> Path:
        """Get the global skills directory path."""
        return self._global_dir

    @property
    def enabled(self) -> bool:
        """Check if the watcher is enabled."""
        return self._enabled

    @property
    def running(self) -> bool:
        """Check if the watcher is currently running."""
        return self._running

    def start(self) -> None:
        """Start file watching.

        Begins monitoring workspace and global skill directories for
        SKILL.md file changes. Does nothing if already running or disabled.

        Raises:
            RuntimeError: If watchdog library is not available.
        """
        if not self._enabled:
            logger.debug("skills_watcher_disabled")
            return

        if self._running:
            logger.debug("skills_watcher_already_running")
            return

        if not WATCHDOG_AVAILABLE:
            logger.error(
                "skills_watcher_watchdog_not_available",
                message="watchdog library is not installed",
            )
            raise RuntimeError(
                "watchdog library is required for skills hot-reload. "
                "Install it with: pip install watchdog"
            )

        self._observer = Observer()
        handler = _SkillsEventHandler(self)

        # Watch workspace skills directory if it exists
        if self._workspace_dir and self._workspace_dir.is_dir():
            self._observer.schedule(
                handler,
                str(self._workspace_dir),
                recursive=True,
            )
            logger.info(
                "skills_watcher_watching_workspace",
                path=str(self._workspace_dir),
            )

        # Watch global skills directory if it exists
        if self._global_dir.is_dir():
            self._observer.schedule(
                handler,
                str(self._global_dir),
                recursive=True,
            )
            logger.info(
                "skills_watcher_watching_global",
                path=str(self._global_dir),
            )

        self._observer.start()
        self._running = True
        logger.info(
            "skills_watcher_started",
            workspace_dir=str(self._workspace_dir) if self._workspace_dir else None,
            global_dir=str(self._global_dir),
            debounce_ms=self._debounce_ms,
        )

    def stop(self) -> None:
        """Stop file watching.

        Stops the file observer and cancels any pending reload timers.
        Does nothing if not running.
        """
        if not self._running:
            return

        # Cancel pending timer
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
                self._pending_path = None

        # Stop observer
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5.0)
            self._observer = None

        self._running = False
        logger.info("skills_watcher_stopped")

    def get_version(self) -> int:
        """Get the current skills version number.

        Returns:
            The current version number (timestamp-based, monotonically increasing).
        """
        return self._version

    def _schedule_reload(self, changed_path: str) -> None:
        """Schedule a reload with debounce.

        Multiple file changes within the debounce window are merged into
        a single reload operation.

        Args:
            changed_path: Path to the changed file.
        """
        with self._lock:
            # Cancel existing timer if any
            if self._timer is not None:
                self._timer.cancel()

            self._pending_path = changed_path

            # Schedule new timer
            delay_seconds = self._debounce_ms / 1000.0
            self._timer = threading.Timer(
                delay_seconds,
                self._do_reload,
            )
            self._timer.daemon = True
            self._timer.start()

            logger.debug(
                "skills_reload_scheduled",
                changed_path=changed_path,
                debounce_ms=self._debounce_ms,
            )

    def _do_reload(self) -> None:
        """Execute the reload operation.

        Updates the version number and invokes the reload callback.
        Errors during reload are logged but do not crash the watcher.
        """
        with self._lock:
            changed_path = self._pending_path
            self._timer = None
            self._pending_path = None

        # Bump version
        new_version = self._bump_version()

        logger.info(
            "skills_reload_triggered",
            changed_path=changed_path,
            new_version=new_version,
        )

        # Invoke callback
        if self._on_reload is not None:
            try:
                self._on_reload()
                logger.info(
                    "skills_reload_completed",
                    version=new_version,
                )
            except Exception as exc:
                logger.error(
                    "skills_reload_failed",
                    error=str(exc),
                    version=new_version,
                )

    def _bump_version(self) -> int:
        """Update the version number.

        Uses timestamp-based versioning to ensure monotonic increase.

        Returns:
            The new version number.
        """
        now = int(time.time() * 1000)
        with self._lock:
            self._version = max(now, self._version + 1)
            return self._version


class _SkillsEventHandler(FileSystemEventHandler):  # type: ignore[misc]
    """Watchdog event handler for skill file changes.

    Filters events to only process SKILL.md and skill.yaml file changes,
    ignoring changes in excluded directories.
    """

    def __init__(self, watcher: SkillsWatcher) -> None:
        """Initialize the event handler.

        Args:
            watcher: The parent SkillsWatcher instance.
        """
        super().__init__()
        self._watcher = watcher

    def on_created(self, event: FileSystemEvent) -> None:
        """Handle file creation events."""
        self._handle(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        """Handle file modification events."""
        self._handle(event)

    def on_deleted(self, event: FileSystemEvent) -> None:
        """Handle file deletion events."""
        self._handle(event)

    def _handle(self, event: FileSystemEvent) -> None:
        """Process a file system event.

        Filters out directory events, non-skill files, and files in
        ignored directories.

        Args:
            event: The file system event to process.
        """
        # Ignore directory events
        if event.is_directory:
            return

        path = Path(event.src_path)

        # Check if it's a skill file (case-insensitive)
        if path.name.lower() not in SKILL_FILE_NAMES:
            return

        # Check if path contains any ignored directory
        for part in path.parts:
            if part in IGNORED_DIRS:
                logger.debug(
                    "skills_event_ignored_dir",
                    path=str(path),
                    ignored_dir=part,
                )
                return

        # Schedule reload
        self._watcher._schedule_reload(str(path))
