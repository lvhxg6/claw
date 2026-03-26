"""FastAPI application factory and lifespan for SmartClaw API Gateway."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = structlog.get_logger(component="gateway.app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: initialize resources on startup, clean up on shutdown."""
    app.state.ready = False

    settings = getattr(app.state, "settings", None)
    if settings is None:
        from smartclaw.config.settings import SmartClawSettings
        settings = SmartClawSettings()
        app.state.settings = settings

    # Initialize ToolRegistry
    from smartclaw.tools.registry import ToolRegistry
    registry = ToolRegistry()
    app.state.registry = registry

    # Initialize MemoryStore
    from smartclaw.memory.store import MemoryStore
    memory_store = MemoryStore(db_path=settings.memory.db_path)
    await memory_store.initialize()
    app.state.memory_store = memory_store

    # Build Agent Graph (minimal: no tools by default in gateway mode)
    from smartclaw.agent.graph import build_graph
    graph = build_graph(model_config=settings.model, tools=registry.get_all())
    app.state.graph = graph

    app.state.ready = True
    logger.info("gateway_startup_complete")

    yield

    # Shutdown
    app.state.ready = False
    try:
        await memory_store.close()
    except Exception:
        pass
    logger.info("gateway_shutdown_complete")


def create_app(settings: Any = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    from smartclaw.gateway.routers.chat import router as chat_router
    from smartclaw.gateway.routers.health import router as health_router
    from smartclaw.gateway.routers.sessions import router as sessions_router
    from smartclaw.gateway.routers.tools import router as tools_router

    app = FastAPI(title="SmartClaw API", version="0.1.0", lifespan=lifespan)

    # Store settings in state before lifespan runs (if provided)
    if settings is not None:
        app.state.settings = settings

    # CORS middleware
    cors_origins = ["*"]
    if settings is not None and hasattr(settings, "gateway"):
        cors_origins = settings.gateway.cors_origins

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(chat_router)
    app.include_router(sessions_router)
    app.include_router(tools_router)
    app.include_router(health_router)

    return app
