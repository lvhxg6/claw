"""FastAPI application factory and lifespan for SmartClaw API Gateway."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse

logger = structlog.get_logger(component="gateway.app")

# SSE broadcast queues for hook events (one per connected debug client)
_hook_event_queues: list[asyncio.Queue] = []

# SSE broadcast queues for decision events (one per connected debug client)
_decision_event_queues: list[asyncio.Queue] = []

# SSE broadcast queues for execution/orchestrator events
_execution_event_queues: list[asyncio.Queue] = []

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
        with suppress(ValueError):
            _hook_event_queues.remove(q)


def _broadcast_decision_event(data: dict) -> None:
    """Push a decision event to all connected debug SSE clients."""
    payload = json.dumps(data, ensure_ascii=False, default=str)
    dead = []
    for q in _decision_event_queues:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        with suppress(ValueError):
            _decision_event_queues.remove(q)


def _broadcast_execution_event(data: dict) -> None:
    """Push an execution event to all connected debug SSE clients."""
    payload = json.dumps(data, ensure_ascii=False, default=str)
    dead = []
    for q in _execution_event_queues:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        with suppress(ValueError):
            _execution_event_queues.remove(q)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: initialize resources on startup, clean up on shutdown."""
    app.state.ready = False

    settings = getattr(app.state, "settings", None)
    if settings is None:
        from smartclaw.config.settings import SmartClawSettings
        settings = SmartClawSettings()
        app.state.settings = settings

    # Initialize full agent stack via shared runtime
    from smartclaw.agent.runtime import setup_agent_runtime

    runtime = await setup_agent_runtime(settings)
    app.state.runtime = runtime

    # Backward compatibility aliases
    app.state.graph = runtime.graph
    app.state.registry = runtime.registry
    app.state.memory_store = runtime.memory_store

    # Register hook handlers to broadcast events to debug UI
    import smartclaw.hooks.registry as hook_registry
    from smartclaw.hooks.events import HookEvent

    async def _debug_hook_handler(event: HookEvent) -> None:
        _broadcast_hook_event(event.to_dict())

    for hp in hook_registry.VALID_HOOK_POINTS:
        hook_registry.register(hp, _debug_hook_handler)

    # Register decision event subscriber on Diagnostic Bus
    from smartclaw.observability import diagnostic_bus

    async def _decision_bus_handler(event_type: str, payload: dict) -> None:
        _broadcast_decision_event(payload)

    async def _execution_bus_handler(event_type: str, payload: dict) -> None:
        _broadcast_execution_event({"event_type": event_type, **payload})

    execution_event_types = [
        "plan.created",
        "plan.updated",
        "dispatch.created",
        "dispatch.batch_started",
        "dispatch.batch_ended",
        "phase.started",
        "phase.ended",
        "subagent.spawned",
        "subagent.completed",
        "subagent.retry_scheduled",
        "schema.validation",
    ]

    diagnostic_bus.on("decision.captured", _decision_bus_handler)
    for event_type in execution_event_types:
        diagnostic_bus.on(event_type, _execution_bus_handler)

    app.state.ready = True
    logger.info("gateway_startup_complete", tools=runtime.registry.count)

    yield

    # Shutdown
    app.state.ready = False
    for hp in hook_registry.VALID_HOOK_POINTS:
        hook_registry.unregister(hp, _debug_hook_handler)
    diagnostic_bus.off("decision.captured", _decision_bus_handler)
    for event_type in execution_event_types:
        diagnostic_bus.off(event_type, _execution_bus_handler)
    await runtime.close()
    logger.info("gateway_shutdown_complete")


def create_app(settings: Any = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    from smartclaw.gateway.routers.chat import router as chat_router
    from smartclaw.gateway.routers.capability_packs import router as capability_packs_router
    from smartclaw.gateway.routers.health import router as health_router
    from smartclaw.gateway.routers.models import router as models_router
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
    app.include_router(capability_packs_router)
    app.include_router(sessions_router)
    app.include_router(tools_router)
    app.include_router(health_router)
    app.include_router(models_router)

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

    # Debug UI: decision events SSE endpoint
    @app.get("/api/debug/decision-events")
    async def debug_decision_events(request: Request):
        """SSE stream of decision trace events for the debug UI."""
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        _decision_event_queues.append(q)

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
                    _decision_event_queues.remove(q)
                except ValueError:
                    pass

        return EventSourceResponse(generator())

    # Debug UI: orchestrator / execution events SSE endpoint
    @app.get("/api/debug/execution-events")
    async def debug_execution_events(request: Request):
        """SSE stream of orchestrator execution events for the debug UI."""
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        _execution_event_queues.append(q)

        async def generator():
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        payload = await asyncio.wait_for(q.get(), timeout=15.0)
                        yield {"data": payload}
                    except TimeoutError:
                        yield {"data": json.dumps({"ping": True})}
            finally:
                with suppress(ValueError):
                    _execution_event_queues.remove(q)

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
