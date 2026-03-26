"""FastAPI application factory and lifespan for SmartClaw API Gateway."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

logger = structlog.get_logger(component="gateway.app")

# SSE broadcast queues for hook events (one per connected debug client)
_hook_event_queues: list[asyncio.Queue] = []

_STATIC_DIR = Path(__file__).parent / "static"


def _broadcast_hook_event(data: dict) -> None:
    """Push a hook event to all connected debug SSE clients."""
    payload = json.dumps(data, ensure_ascii=False, default=str)
    dead = []
    for q in _hook_event_queues:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        try:
            _hook_event_queues.remove(q)
        except ValueError:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: initialize resources on startup, clean up on shutdown."""
    app.state.ready = False

    settings = getattr(app.state, "settings", None)
    if settings is None:
        from smartclaw.config.settings import SmartClawSettings
        settings = SmartClawSettings()
        app.state.settings = settings

    # Initialize ToolRegistry with system tools
    from smartclaw.tools.registry import create_system_tools
    import os
    workspace = os.path.expanduser(settings.agent_defaults.workspace)
    registry = create_system_tools(workspace)
    app.state.registry = registry

    # Initialize MemoryStore
    from smartclaw.memory.store import MemoryStore
    db_path = os.path.expanduser(settings.memory.db_path)
    memory_store = MemoryStore(db_path=db_path)
    await memory_store.initialize()
    app.state.memory_store = memory_store

    # Build Agent Graph with all system tools
    from smartclaw.agent.graph import build_graph
    graph = build_graph(model_config=settings.model, tools=registry.get_all())
    app.state.graph = graph

    # Register hook handlers to broadcast events to debug UI
    import smartclaw.hooks.registry as hook_registry
    from smartclaw.hooks.events import HookEvent

    async def _debug_hook_handler(event: HookEvent) -> None:
        _broadcast_hook_event(event.to_dict())

    for hp in hook_registry.VALID_HOOK_POINTS:
        hook_registry.register(hp, _debug_hook_handler)

    app.state.ready = True
    logger.info("gateway_startup_complete", tools=registry.count)

    yield

    # Shutdown
    app.state.ready = False
    for hp in hook_registry.VALID_HOOK_POINTS:
        hook_registry.unregister(hp, _debug_hook_handler)
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

    # Debug UI: hook events SSE endpoint
    @app.get("/api/debug/hook-events")
    async def debug_hook_events(request: Request):
        """SSE stream of lifecycle hook events for the debug UI."""
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        _hook_event_queues.append(q)

        async def generator():
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        payload = await asyncio.wait_for(q.get(), timeout=15.0)
                        yield {"data": payload}
                    except asyncio.TimeoutError:
                        yield {"data": json.dumps({"ping": True})}
            finally:
                try:
                    _hook_event_queues.remove(q)
                except ValueError:
                    pass

        return EventSourceResponse(generator())

    # Config endpoint for Debug UI
    @app.get("/api/config")
    async def get_config(request: Request):
        """Return model and gateway configuration for the debug UI."""
        settings = getattr(request.app.state, "settings", None)
        if settings is None:
            return {"model": "unknown", "gateway_port": 8000}
        return {
            "model": settings.model.primary,
            "gateway_port": settings.gateway.port,
        }

    # Debug UI: serve static HTML
    if _STATIC_DIR.exists():
        @app.get("/", response_class=HTMLResponse)
        async def debug_ui():
            return (_STATIC_DIR / "index.html").read_text(encoding="utf-8")

    return app
