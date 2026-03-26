"""Chat router — POST /api/chat, POST /api/chat/stream."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from smartclaw.gateway.models import ChatRequest, ChatResponse
from smartclaw.hooks.events import HookEvent

logger = structlog.get_logger(component="gateway.chat")

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Hook points that the SSE stream subscribes to
STREAM_HOOK_POINTS = [
    "tool:before",
    "tool:after",
    "llm:before",
    "llm:after",
    "agent:start",
    "agent:end",
]


def _resolve_graph(request_body: ChatRequest, runtime: Any) -> Any:
    """Return the graph to use for this request.

    If request_body.model is None or empty, returns runtime.graph.
    Otherwise validates the model ref and builds a temporary graph.

    Raises:
        ValueError: If the model reference is invalid.
    """
    model_str = request_body.model
    if not model_str:
        return runtime.graph

    from smartclaw.agent.graph import build_graph
    from smartclaw.providers.config import ModelConfig, parse_model_ref

    # Validate — raises ValueError on bad format
    parse_model_ref(model_str)

    temp_config = ModelConfig(
        primary=model_str,
        fallbacks=runtime.model_config.fallbacks,
        temperature=runtime.model_config.temperature,
        max_tokens=runtime.model_config.max_tokens,
    )
    return build_graph(temp_config, runtime.tools)


# ---------------------------------------------------------------------------
# SSE stream helpers
# ---------------------------------------------------------------------------


def _make_queue_handler(
    queue: asyncio.Queue,  # type: ignore[type-arg]
    hook_point: str,
):
    """Factory: return an async handler that writes event dicts to *queue*.

    When the queue is full the event is silently discarded (no blocking).
    """

    async def handler(event: HookEvent) -> None:
        try:
            queue.put_nowait({**event.to_dict(), "hook_point": hook_point})
        except asyncio.QueueFull:
            pass  # discard — never block the agent loop

    return handler


def _format_sse(evt_dict: dict) -> dict | None:  # type: ignore[type-arg]
    """Map a queue event dict to an SSE ``{event, data}`` dict.

    Returns ``None`` for hook points that should not be pushed to the client
    (e.g. ``llm:after``, ``agent:end``).
    """
    hp = evt_dict.get("hook_point", "")

    if hp == "llm:before":
        return {
            "event": "thinking",
            "data": json.dumps(
                {
                    "status": "reasoning",
                    "iteration": evt_dict.get("message_count", 0),
                },
                ensure_ascii=False,
            ),
        }

    if hp == "tool:before":
        return {
            "event": "tool_call",
            "data": json.dumps(
                {
                    "tool_name": evt_dict.get("tool_name", ""),
                    "args": evt_dict.get("tool_args", {}),
                    "tool_call_id": evt_dict.get("tool_call_id", ""),
                },
                ensure_ascii=False,
            ),
        }

    if hp == "tool:after":
        result_raw = evt_dict.get("result", "")
        return {
            "event": "tool_result",
            "data": json.dumps(
                {
                    "tool_name": evt_dict.get("tool_name", ""),
                    "result": str(result_raw)[:2048],
                    "duration_ms": evt_dict.get("duration_ms", 0),
                    "success": evt_dict.get("error") is None,
                },
                ensure_ascii=False,
            ),
        }

    if hp == "agent:start":
        return {
            "event": "iteration",
            "data": json.dumps(
                {
                    "current": 1,
                    "max": evt_dict.get("max_iterations") or 50,
                },
                ensure_ascii=False,
            ),
        }

    # llm:after, agent:end, unknown → skip
    return None


def _register_stream_handlers(
    queue: asyncio.Queue,  # type: ignore[type-arg]
) -> dict[str, Any]:
    """Register temporary hook handlers for all STREAM_HOOK_POINTS.

    Returns a mapping ``{hook_point: handler}`` for later unregistration.
    """
    import smartclaw.hooks.registry as hook_registry

    handlers: dict[str, Any] = {}
    for hp in STREAM_HOOK_POINTS:
        h = _make_queue_handler(queue, hp)
        hook_registry.register(hp, h)
        handlers[hp] = h
    return handlers


def _unregister_stream_handlers(handlers: dict[str, Any]) -> None:
    """Unregister all temporary hook handlers."""
    import smartclaw.hooks.registry as hook_registry

    for hp, h in handlers.items():
        hook_registry.unregister(hp, h)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=ChatResponse)
async def chat(request_body: ChatRequest, request: Request) -> ChatResponse:
    """Synchronous chat endpoint: invoke Agent Graph and return full result."""
    session_key = request_body.session_key or str(uuid.uuid4())
    runtime = request.app.state.runtime
    memory_store = runtime.memory_store

    # Track active request for model switching protection
    runtime.increment_requests()

    # Session model override: if request has no model, check session_config
    if not request_body.model and memory_store is not None:
        try:
            cfg = await memory_store.get_session_config(session_key)
            if cfg and cfg.get("model_override"):
                request_body = request_body.model_copy(
                    update={"model": cfg["model_override"]}
                )
        except Exception:
            pass  # fall back to default model

    try:
        graph = _resolve_graph(request_body, runtime)
    except ValueError as exc:
        runtime.decrement_requests()
        return JSONResponse(  # type: ignore[return-value]
            status_code=400,
            content={"error": str(exc)},
        )

    try:
        from smartclaw.agent.graph import invoke

        result = await invoke(
            graph,
            request_body.message,
            max_iterations=request_body.max_iterations,
            session_key=session_key,
            memory_store=memory_store,
            system_prompt=runtime.system_prompt,
            summarizer=runtime.summarizer,
            context_engine=getattr(runtime, "context_engine", None),
        )
        return ChatResponse(
            session_key=session_key,
            response=result.get("final_answer") or "",
            iterations=result.get("iteration", 0),
            error=result.get("error"),
            token_stats=result.get("token_stats"),
        )
    except Exception as exc:
        logger.error("chat_invoke_error", error=str(exc))
        return JSONResponse(  # type: ignore[return-value]
            status_code=500,
            content={"error": str(exc)},
        )
    finally:
        runtime.decrement_requests()


@router.post("/stream")
async def chat_stream(request_body: ChatRequest, request: Request) -> EventSourceResponse:
    """SSE streaming endpoint: emits tool_call, tool_result, thinking, done, error events."""
    session_key = request_body.session_key or str(uuid.uuid4())
    runtime = request.app.state.runtime
    memory_store = runtime.memory_store
    max_iterations = request_body.max_iterations

    # Track active request for model switching protection
    runtime.increment_requests()

    try:
        graph = _resolve_graph(request_body, runtime)
    except ValueError as exc:
        runtime.decrement_requests()
        return JSONResponse(  # type: ignore[return-value]
            status_code=400,
            content={"error": str(exc)},
        )

    async def event_generator() -> AsyncGenerator[dict, None]:  # type: ignore[type-arg]
        from smartclaw.agent.graph import invoke

        try:
            queue: asyncio.Queue = asyncio.Queue(maxsize=200)  # type: ignore[type-arg]
            handlers = _register_stream_handlers(queue)
        except Exception:
            # Fallback: queue/handler setup failed → simple thinking + done
            try:
                yield {
                    "event": "thinking",
                    "data": json.dumps(
                        {"session_key": session_key, "status": "started"},
                        ensure_ascii=False,
                    ),
                }
                result = await invoke(
                    graph,
                    request_body.message,
                    max_iterations=max_iterations,
                    session_key=session_key,
                    memory_store=memory_store,
                    system_prompt=runtime.system_prompt,
                    summarizer=runtime.summarizer,
                    context_engine=getattr(runtime, "context_engine", None),
                )
                yield {
                    "event": "done",
                    "data": json.dumps(
                        {
                            "session_key": session_key,
                            "response": result.get("final_answer") or "",
                            "iterations": result.get("iteration", 0),
                        },
                        ensure_ascii=False,
                    ),
                }
            except Exception as fallback_exc:
                yield {
                    "event": "error",
                    "data": json.dumps(
                        {"error": str(fallback_exc)}, ensure_ascii=False
                    ),
                }
            finally:
                runtime.decrement_requests()
            return

        try:
            task = asyncio.create_task(
                invoke(
                    graph,
                    request_body.message,
                    max_iterations=max_iterations,
                    session_key=session_key,
                    memory_store=memory_store,
                    system_prompt=runtime.system_prompt,
                    summarizer=runtime.summarizer,
                    context_engine=getattr(runtime, "context_engine", None),
                )
            )

            # Main loop: read events from queue while invoke runs
            while not task.done():
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=1.0)
                    sse = _format_sse(evt)
                    if sse:
                        yield sse
                except asyncio.TimeoutError:
                    continue

            # Drain remaining events
            while not queue.empty():
                evt = queue.get_nowait()
                sse = _format_sse(evt)
                if sse:
                    yield sse

            # Final event
            result = task.result()
            yield {
                "event": "done",
                "data": json.dumps(
                    {
                        "session_key": session_key,
                        "response": result.get("final_answer") or "",
                        "iterations": result.get("iteration", 0),
                    },
                    ensure_ascii=False,
                ),
            }
        except Exception as exc:
            logger.error("chat_stream_error", error=str(exc))
            yield {
                "event": "error",
                "data": json.dumps({"error": str(exc)}, ensure_ascii=False),
            }
        finally:
            _unregister_stream_handlers(handlers)
            runtime.decrement_requests()

    return EventSourceResponse(event_generator())
