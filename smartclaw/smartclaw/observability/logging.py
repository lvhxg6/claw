"""Structured logging with structlog.

Provides ``setup_logging`` to configure the structlog processor chain and
``get_logger`` to obtain a component-bound logger.

Environment variable overrides (applied before ``setup_logging`` is called
via Pydantic Settings):
    SMARTCLAW_LOG_LEVEL  — log level (default: INFO)
    SMARTCLAW_LOG_FORMAT — "json" | "console" (default: console)
    SMARTCLAW_LOG_FILE   — optional file path for log output
"""

from __future__ import annotations

import logging
import os
import sys

import structlog
from structlog.types import Processor

from smartclaw.config.settings import LoggingSettings

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_LOG_LEVEL_MAP: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

_setup_done: bool = False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def setup_logging(settings: LoggingSettings | None = None) -> None:
    """Configure the structlog processor chain.

    Falls back to stdlib ``logging`` if structlog initialisation fails.

    Args:
        settings: Logging configuration.  When *None* a default
            ``LoggingSettings`` is constructed (honours env vars via
            Pydantic Settings).
    """
    global _setup_done  # noqa: PLW0603

    if settings is None:
        settings = _settings_from_env()

    try:
        _configure_structlog(settings)
        _setup_done = True
    except Exception:
        # Fallback: configure stdlib logging so callers still get output.
        _fallback_stdlib_logging(settings)
        _setup_done = True


def get_logger(component: str) -> structlog.BoundLogger:
    """Return a logger bound with the given *component* name.

    If ``setup_logging`` has not been called yet, a minimal default
    configuration is applied automatically.
    """
    if not _setup_done:
        setup_logging()

    logger: structlog.BoundLogger = structlog.get_logger(component=component)
    return logger


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _settings_from_env() -> LoggingSettings:
    """Build a ``LoggingSettings`` from environment variables."""
    level = os.environ.get("SMARTCLAW_LOG_LEVEL", "INFO")
    fmt = os.environ.get("SMARTCLAW_LOG_FORMAT", "console")
    file = os.environ.get("SMARTCLAW_LOG_FILE")
    return LoggingSettings(level=level, format=fmt, file=file)


def _resolve_level(level_str: str) -> int:
    """Map a level string to a stdlib numeric level."""
    return _LOG_LEVEL_MAP.get(level_str.upper(), logging.INFO)


def _build_processors(settings: LoggingSettings) -> list[Processor]:
    """Build the shared structlog processor chain (without the final renderer)."""
    processors: list[Processor] = [
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.CallsiteParameterAdder(
            parameters=[
                structlog.processors.CallsiteParameter.FILENAME,
                structlog.processors.CallsiteParameter.LINENO,
                structlog.processors.CallsiteParameter.FUNC_NAME,
            ],
        ),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    return processors


def _build_renderer(settings: LoggingSettings) -> Processor:
    """Choose the final renderer based on the configured format."""
    if settings.format.lower() == "json":
        return structlog.processors.JSONRenderer()
    return structlog.dev.ConsoleRenderer()


def _configure_structlog(settings: LoggingSettings) -> None:
    """Wire up structlog + stdlib logging."""
    numeric_level = _resolve_level(settings.level)

    # --- stdlib root logger -------------------------------------------
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Remove existing handlers to avoid duplicate output on re-init.
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Console / stderr handler
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setLevel(numeric_level)
    root_logger.addHandler(stream_handler)

    # Optional file handler
    if settings.file:
        file_handler = logging.FileHandler(settings.file, encoding="utf-8")
        file_handler.setLevel(numeric_level)
        root_logger.addHandler(file_handler)

    # --- structlog configuration --------------------------------------
    shared_processors = _build_processors(settings)
    renderer = _build_renderer(settings)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    # Attach a ProcessorFormatter to each stdlib handler so that
    # structlog events rendered through stdlib also go through the chain.
    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )
    for handler in root_logger.handlers:
        handler.setFormatter(formatter)


def _fallback_stdlib_logging(settings: LoggingSettings) -> None:
    """Minimal stdlib-only logging when structlog init fails."""
    numeric_level = _resolve_level(settings.level)

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if settings.file:
        handlers.append(logging.FileHandler(settings.file, encoding="utf-8"))

    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.warning("structlog initialisation failed — using stdlib logging fallback")
