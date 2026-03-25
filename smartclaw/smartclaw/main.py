"""SmartClaw entry point module.

Initialization order (per design.md):
    1. Load dotenv — inject .env vars into process environment
    2. Load config — read YAML + Pydantic validation
    3. Setup logging — configure structlog processor chain
    4. Log startup message
"""

from __future__ import annotations

import logging
import sys

from smartclaw.config.loader import load_config
from smartclaw.config.settings import SmartClawSettings
from smartclaw.credentials import load_dotenv
from smartclaw.observability.logging import get_logger, setup_logging


def _init() -> SmartClawSettings:
    """Run the full initialization sequence and return validated settings.

    Steps:
        1. ``load_dotenv()`` — populate env vars from ``.env``
        2. ``load_config()`` — read YAML, merge env overrides, validate
        3. ``setup_logging(settings.logging)`` — wire up structlog

    Returns:
        The validated :class:`SmartClawSettings` instance.

    Raises:
        FileNotFoundError: Config file missing.
        yaml.YAMLError: Config file has bad YAML syntax.
        pydantic.ValidationError: Config values fail schema validation.
    """
    # Step 1: credentials / dotenv
    load_dotenv()

    # Step 2: configuration
    settings = load_config()

    # Step 3: logging
    setup_logging(settings.logging)

    return settings


def main() -> None:
    """SmartClaw entry function — initializes all subsystems in order."""
    try:
        settings = _init()
        logger = get_logger("main")
        logger.info(
            "SmartClaw started",
            version="0.1.0",
            log_level=settings.logging.level,
            log_format=settings.logging.format,
        )
    except FileNotFoundError as exc:
        logging.error("Configuration file not found: %s", exc)
        sys.exit(1)
    except Exception as exc:
        logging.error("Failed to initialize SmartClaw: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
