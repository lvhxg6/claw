"""SmartClaw API Gateway entry point.

Usage::

    python -m smartclaw.serve
    # or via the CLI entry point defined in pyproject.toml
"""

from __future__ import annotations

import signal
import sys

import structlog
import uvicorn

logger = structlog.get_logger(component="serve")


def main() -> None:
    """Load config → create app → register signal handlers → start uvicorn."""
    from smartclaw.config.loader import load_config
    from smartclaw.credentials import load_dotenv
    from smartclaw.gateway.app import create_app

    # ------------------------------------------------------------------
    # Load environment variables from .env
    # ------------------------------------------------------------------
    load_dotenv()

    # ------------------------------------------------------------------
    # Load configuration
    # ------------------------------------------------------------------
    try:
        settings = load_config()
    except Exception as exc:
        logger.error("config_load_failed", error=str(exc))
        sys.exit(1)

    logger.info(
        "smartclaw_gateway_starting",
        host=settings.gateway.host,
        port=settings.gateway.port,
    )

    # ------------------------------------------------------------------
    # Create FastAPI application
    # ------------------------------------------------------------------
    app = create_app(settings)

    # ------------------------------------------------------------------
    # Uvicorn server configuration
    # ------------------------------------------------------------------
    config = uvicorn.Config(
        app=app,
        host=settings.gateway.host,
        port=settings.gateway.port,
        log_level="info",
        timeout_graceful_shutdown=settings.gateway.shutdown_timeout,
    )
    server = uvicorn.Server(config)

    # ------------------------------------------------------------------
    # Graceful shutdown via SIGTERM / SIGINT
    # ------------------------------------------------------------------
    def _handle_signal(sig: int, frame: object) -> None:  # noqa: ARG001
        sig_name = signal.Signals(sig).name
        logger.info("shutdown_signal_received", signal=sig_name)
        server.should_exit = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # ------------------------------------------------------------------
    # Run (blocking)
    # ------------------------------------------------------------------
    try:
        server.run()
    except Exception as exc:
        logger.error("server_error", error=str(exc))
        sys.exit(1)

    logger.info("smartclaw_gateway_stopped")


if __name__ == "__main__":
    main()
