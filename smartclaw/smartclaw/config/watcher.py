"""ConfigWatcher — File watcher for config.yaml hot-reload.

This module provides the ConfigWatcher class for monitoring config.yaml
file changes using the watchdog library. Supports debounce mechanism
and configuration validation.

Validates: Requirements 4.1, 4.2, 4.8
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable

import structlog
import yaml

try:
    from watchdog.events import FileSystemEvent, FileSystemEventHandler
    from watchdog.observers import Observer

    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    FileSystemEvent = object  # type: ignore[misc, assignment]
    FileSystemEventHandler = object  # type: ignore[misc, assignment]
    Observer = object  # type: ignore[misc, assignment]

logger = structlog.get_logger(component="config.watcher")

# Default debounce time in milliseconds
DEFAULT_DEBOUNCE_MS = 500

# Configuration keys that support hot-reload
HOT_RELOAD_KEYS = {
    "providers",
    "memory",
    "skills",
    "logging.level",
    "logging",
}

# Configuration keys that require restart
RESTART_REQUIRED_KEYS = {
    "gateway.host",
    "gateway.port",
    "gateway",
}


class ConfigWatcher:
    """Configuration file watcher for hot-reload functionality.

    Monitors config.yaml file changes using the watchdog library.
    Implements debounce mechanism and configuration validation.

    Attributes:
        config_path: Path to the configuration file.
        debounce_ms: Debounce time in milliseconds.
        enabled: Whether the watcher is enabled.

    Validates: Requirements 4.1, 4.2, 4.8
    """

    def __init__(
        self,
        config_path: str = "config.yaml",
        debounce_ms: int = DEFAULT_DEBOUNCE_MS,
        on_reload: Callable[[dict[str, Any]], None] | None = None,
        on_restart_required: Callable[[set[str]], None] | None = None,
        enabled: bool = True,
    ) -> None:
        """Initialize the ConfigWatcher.

        Args:
            config_path: Path to the configuration file.
            debounce_ms: Debounce time in milliseconds (default: 500).
            on_reload: Callback function invoked with new config on reload.
            on_restart_required: Callback when restart-required keys change.
            enabled: Whether the watcher is enabled.
        """
        self._config_path = Path(config_path).expanduser().resolve()
        self._debounce_ms = debounce_ms
        self._on_reload = on_reload
        self._on_restart_required = on_restart_required
        self._enabled = enabled

        self._observer: Observer | None = None
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._running = False
        self._current_config: dict[str, Any] = {}
        self._last_valid_config: dict[str, Any] = {}

    @property
    def config_path(self) -> Path:
        """Get the configuration file path."""
        return self._config_path

    @property
    def enabled(self) -> bool:
        """Check if the watcher is enabled."""
        return self._enabled

    @property
    def running(self) -> bool:
        """Check if the watcher is currently running."""
        return self._running

    @property
    def current_config(self) -> dict[str, Any]:
        """Get the current configuration."""
        return self._current_config.copy()

    def start(self) -> None:
        """Start configuration file watching.

        Begins monitoring the config file for changes.
        Does nothing if already running or disabled.

        Raises:
            RuntimeError: If watchdog library is not available.
        """
        if not self._enabled:
            logger.debug("config_watcher_disabled")
            return

        if self._running:
            logger.debug("config_watcher_already_running")
            return

        if not WATCHDOG_AVAILABLE:
            logger.error(
                "config_watcher_watchdog_not_available",
                message="watchdog library is not installed",
            )
            raise RuntimeError(
                "watchdog library is required for config hot-reload. "
                "Install it with: pip install watchdog"
            )

        # Load initial configuration
        self._load_initial_config()

        # Setup observer
        self._observer = Observer()
        handler = _ConfigEventHandler(self)

        # Watch the directory containing the config file
        config_dir = self._config_path.parent
        if config_dir.is_dir():
            self._observer.schedule(
                handler,
                str(config_dir),
                recursive=False,
            )
            logger.info(
                "config_watcher_watching",
                path=str(self._config_path),
            )

        self._observer.start()
        self._running = True
        logger.info(
            "config_watcher_started",
            config_path=str(self._config_path),
            debounce_ms=self._debounce_ms,
        )

    def stop(self) -> None:
        """Stop configuration file watching.

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

        # Stop observer
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5.0)
            self._observer = None

        self._running = False
        logger.info("config_watcher_stopped")

    def _load_initial_config(self) -> None:
        """Load the initial configuration from file."""
        if not self._config_path.is_file():
            logger.warning(
                "config_file_not_found",
                path=str(self._config_path),
            )
            return

        try:
            content = self._config_path.read_text(encoding="utf-8")
            config = yaml.safe_load(content) or {}
            self._current_config = config
            self._last_valid_config = config.copy()
            logger.info(
                "config_loaded",
                path=str(self._config_path),
            )
        except Exception as exc:
            logger.error(
                "config_load_failed",
                path=str(self._config_path),
                error=str(exc),
            )

    def _schedule_reload(self) -> None:
        """Schedule a configuration reload with debounce."""
        with self._lock:
            # Cancel existing timer if any
            if self._timer is not None:
                self._timer.cancel()

            # Schedule new timer
            delay_seconds = self._debounce_ms / 1000.0
            self._timer = threading.Timer(
                delay_seconds,
                self._do_reload,
            )
            self._timer.daemon = True
            self._timer.start()

            logger.debug(
                "config_reload_scheduled",
                debounce_ms=self._debounce_ms,
            )

    def _do_reload(self) -> None:
        """Execute the configuration reload operation."""
        with self._lock:
            self._timer = None

        if not self._config_path.is_file():
            logger.warning(
                "config_file_not_found_on_reload",
                path=str(self._config_path),
            )
            return

        try:
            # Read and parse new configuration
            content = self._config_path.read_text(encoding="utf-8")
            new_config = yaml.safe_load(content) or {}

            # Validate configuration
            errors = self._validate_config(new_config)
            if errors:
                logger.error(
                    "config_validation_failed",
                    errors=errors,
                )
                # Keep using last valid config
                return

            # Compute diff
            changed_keys, restart_keys = self._diff_config(
                self._current_config, new_config
            )

            if not changed_keys and not restart_keys:
                logger.debug("config_no_changes")
                return

            # Update current config
            old_config = self._current_config
            self._current_config = new_config
            self._last_valid_config = new_config.copy()

            logger.info(
                "config_reloaded",
                changed_keys=list(changed_keys),
                restart_required_keys=list(restart_keys),
            )

            # Notify about restart-required keys
            if restart_keys and self._on_restart_required:
                try:
                    self._on_restart_required(restart_keys)
                except Exception as exc:
                    logger.error(
                        "config_restart_callback_failed",
                        error=str(exc),
                    )

            # Invoke reload callback for hot-reloadable changes
            if changed_keys and self._on_reload:
                try:
                    self._on_reload(new_config)
                    logger.info("config_reload_callback_completed")
                except Exception as exc:
                    logger.error(
                        "config_reload_callback_failed",
                        error=str(exc),
                    )
                    # Rollback to previous config on callback failure
                    self._current_config = old_config

        except yaml.YAMLError as exc:
            logger.error(
                "config_parse_failed",
                path=str(self._config_path),
                error=str(exc),
            )
        except Exception as exc:
            logger.error(
                "config_reload_failed",
                error=str(exc),
            )

    def _validate_config(self, config: dict[str, Any]) -> list[str]:
        """Validate configuration structure and values.

        Args:
            config: Configuration dictionary to validate.

        Returns:
            List of error messages. Empty list means validation passed.
        """
        errors: list[str] = []

        if not isinstance(config, dict):
            errors.append("Configuration must be a dictionary")
            return errors

        # Validate providers section
        if "providers" in config:
            providers = config["providers"]
            if not isinstance(providers, dict):
                errors.append("'providers' must be a dictionary")

        # Validate memory section
        if "memory" in config:
            memory = config["memory"]
            if not isinstance(memory, dict):
                errors.append("'memory' must be a dictionary")
            else:
                if "chunk_tokens" in memory:
                    if not isinstance(memory["chunk_tokens"], int) or memory["chunk_tokens"] <= 0:
                        errors.append("'memory.chunk_tokens' must be a positive integer")
                if "vector_weight" in memory:
                    weight = memory["vector_weight"]
                    if not isinstance(weight, (int, float)) or not 0 <= weight <= 1:
                        errors.append("'memory.vector_weight' must be between 0 and 1")

        # Validate skills section
        if "skills" in config:
            skills = config["skills"]
            if not isinstance(skills, dict):
                errors.append("'skills' must be a dictionary")
            else:
                if "debounce_ms" in skills:
                    if not isinstance(skills["debounce_ms"], int) or skills["debounce_ms"] < 0:
                        errors.append("'skills.debounce_ms' must be a non-negative integer")

        # Validate gateway section
        if "gateway" in config:
            gateway = config["gateway"]
            if not isinstance(gateway, dict):
                errors.append("'gateway' must be a dictionary")
            else:
                if "port" in gateway:
                    port = gateway["port"]
                    if not isinstance(port, int) or not 1 <= port <= 65535:
                        errors.append("'gateway.port' must be between 1 and 65535")

        # Validate logging section
        if "logging" in config:
            logging_config = config["logging"]
            if not isinstance(logging_config, dict):
                errors.append("'logging' must be a dictionary")
            else:
                if "level" in logging_config:
                    level = logging_config["level"]
                    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
                    if not isinstance(level, str) or level.upper() not in valid_levels:
                        errors.append(f"'logging.level' must be one of {valid_levels}")

        return errors

    def _diff_config(
        self, old: dict[str, Any], new: dict[str, Any]
    ) -> tuple[set[str], set[str]]:
        """Compare configuration and identify changed keys.

        Args:
            old: Previous configuration.
            new: New configuration.

        Returns:
            Tuple of (hot_reloadable_changed_keys, restart_required_keys).
        """
        changed_keys: set[str] = set()
        restart_keys: set[str] = set()

        # Get all top-level keys
        all_keys = set(old.keys()) | set(new.keys())

        for key in all_keys:
            old_value = old.get(key)
            new_value = new.get(key)

            if old_value != new_value:
                # Check if this is a restart-required key
                if key in RESTART_REQUIRED_KEYS or any(
                    key.startswith(rk.split(".")[0]) for rk in RESTART_REQUIRED_KEYS
                ):
                    restart_keys.add(key)
                    # Also check nested keys for gateway
                    if key == "gateway" and isinstance(old_value, dict) and isinstance(new_value, dict):
                        for nested_key in ["host", "port"]:
                            if old_value.get(nested_key) != new_value.get(nested_key):
                                restart_keys.add(f"gateway.{nested_key}")
                elif key in HOT_RELOAD_KEYS or any(
                    key.startswith(hk.split(".")[0]) for hk in HOT_RELOAD_KEYS
                ):
                    changed_keys.add(key)
                else:
                    # Unknown keys are treated as hot-reloadable
                    changed_keys.add(key)

        return changed_keys, restart_keys

    def force_reload(self) -> None:
        """Force an immediate configuration reload without debounce."""
        self._do_reload()


class _ConfigEventHandler(FileSystemEventHandler):  # type: ignore[misc]
    """Watchdog event handler for config file changes."""

    def __init__(self, watcher: ConfigWatcher) -> None:
        """Initialize the event handler.

        Args:
            watcher: The parent ConfigWatcher instance.
        """
        super().__init__()
        self._watcher = watcher

    def on_modified(self, event: FileSystemEvent) -> None:
        """Handle file modification events."""
        self._handle(event)

    def on_created(self, event: FileSystemEvent) -> None:
        """Handle file creation events."""
        self._handle(event)

    def _handle(self, event: FileSystemEvent) -> None:
        """Process a file system event.

        Args:
            event: The file system event to process.
        """
        if event.is_directory:
            return

        event_path = Path(event.src_path).resolve()
        config_path = self._watcher.config_path

        # Only handle events for the config file
        if event_path != config_path:
            return

        logger.debug(
            "config_file_changed",
            path=str(event_path),
        )
        self._watcher._schedule_reload()
