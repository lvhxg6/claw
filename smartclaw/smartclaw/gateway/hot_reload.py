"""Configuration hot-reloader for SmartClaw API Gateway.

Polls the config file's mtime every ``interval`` seconds.  On change:
  - Parses YAML
  - Validates via Pydantic (SmartClawSettings)
  - Updates app.state.settings
  - Emits a "config.reloaded" diagnostic event

On failure (bad YAML or validation error) the current config is kept and
the error is logged via structlog.
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING

import structlog
import yaml

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = structlog.get_logger(component="gateway.hot_reload")


class HotReloader:
    """Poll a YAML config file for changes and hot-reload SmartClawSettings.

    Args:
        config_path: Absolute or relative path to the YAML config file.
        app: The FastAPI application whose ``app.state.settings`` will be updated.
        interval: Polling interval in seconds (default 5.0).
    """

    def __init__(self, config_path: str, app: "FastAPI", interval: float = 5.0) -> None:
        self._config_path = config_path
        self._app = app
        self._interval = interval
        self._last_mtime: float | None = None
        self._task: asyncio.Task | None = None  # type: ignore[type-arg]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background polling asyncio.Task."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.ensure_future(self._poll_loop())
        logger.info("hot_reloader_started", config_path=self._config_path, interval=self._interval)

    def stop(self) -> None:
        """Cancel the background polling task."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            logger.info("hot_reloader_stopped", config_path=self._config_path)
        self._task = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        """Async polling loop: check mtime every ``interval`` seconds."""
        # Seed the initial mtime so the first poll doesn't trigger a reload
        self._last_mtime = self._get_mtime()
        try:
            while True:
                await asyncio.sleep(self._interval)
                current_mtime = self._get_mtime()
                if current_mtime is not None and current_mtime != self._last_mtime:
                    logger.info(
                        "config_file_changed",
                        config_path=self._config_path,
                        old_mtime=self._last_mtime,
                        new_mtime=current_mtime,
                    )
                    await self._reload()
                    self._last_mtime = current_mtime
        except asyncio.CancelledError:
            pass

    async def _reload(self) -> None:
        """Reload config: parse YAML → Pydantic validate → update app.state.settings.

        On failure: log error, keep current config.
        On success: emit "config.reloaded" diagnostic event.
        """
        from smartclaw.config.settings import SmartClawSettings

        try:
            with open(self._config_path, encoding="utf-8") as f:
                raw = yaml.safe_load(f)
        except Exception as exc:
            logger.error(
                "hot_reload_yaml_parse_error",
                config_path=self._config_path,
                error=str(exc),
            )
            return

        if raw is None:
            raw = {}

        if not isinstance(raw, dict):
            logger.error(
                "hot_reload_invalid_yaml_structure",
                config_path=self._config_path,
                got_type=type(raw).__name__,
            )
            return

        try:
            new_settings = SmartClawSettings(**raw)
        except Exception as exc:
            logger.error(
                "hot_reload_validation_error",
                config_path=self._config_path,
                error=str(exc),
            )
            return

        # Success — update app state
        old_settings = getattr(self._app.state, "settings", None)
        self._app.state.settings = new_settings

        # Determine changed fields for the diagnostic event
        changed_fields: list[str] = []
        if old_settings is not None:
            try:
                old_dict = old_settings.model_dump()
                new_dict = new_settings.model_dump()
                changed_fields = [k for k in new_dict if new_dict.get(k) != old_dict.get(k)]
            except Exception:
                pass

        logger.info(
            "hot_reload_success",
            config_path=self._config_path,
            changed_fields=changed_fields,
        )

        # Emit diagnostic event (best-effort)
        try:
            from smartclaw.observability import diagnostic_bus
            await diagnostic_bus.emit(
                "config.reloaded",
                {"changed_fields": changed_fields, "success": True},
            )
        except Exception as exc:
            logger.warning("hot_reload_emit_error", error=str(exc))

    def _get_mtime(self) -> float | None:
        """Return the file's mtime, or None if the file doesn't exist."""
        try:
            return os.path.getmtime(self._config_path)
        except OSError:
            return None
