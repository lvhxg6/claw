"""Chat router — POST /api/chat, POST /api/chat/stream."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from smartclaw.gateway.models import ChatRequest, ChatResponse

logger = structlog.get_logger(component="gateway.chat")

router = APIRouter(prefix="/api/chat", tags=["chat"])


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


@router.post("", response_model=ChatResponse)
async def chat(request_body: ChatRequest, request: Request) -> ChatResponse:
    """Synchronous chat endpoint: invoke Agent Graph and return full result."""
    session_key = request_body.session_key or str(uuid.uuid4())
    runtime = request.app.state.runtime
    memory_store = runtime.memory_store

    try:
        graph = _resolve_graph(request_body, runtime)
    except ValueError as exc:
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
        )
        return ChatResponse(
            session_key=session_key,
            response=result.get("final_answer") or "",
            iterations=result.get("iteration", 0),
            error=result.get("error"),
        )
    except Exception as exc:
        logger.error("chat_invoke_error", error=str(exc))
        return JSONResponse(  # type: ignore[return-value]
            status_code=500,
            content={"error": str(exc)},
        )


@router.post("/stream")
async def chat_stream(request_body: ChatRequest, request: Request) -> EventSourceResponse:
    """SSE streaming endpoint: emits tool_call, tool_result, thinking, done, error events."""
    session_key = request_body.session_key or str(uuid.uuid4())
    runtime = request.app.state.runtime
    memory_store = runtime.memory_store

    try:
        graph = _resolve_graph(request_body, runtime)
    except ValueError as exc:
        return JSONResponse(  # type: ignore[return-value]
            status_code=400,
            content={"error": str(exc)},
        )

    async def event_generator() -> AsyncGenerator[dict, None]:  # type: ignore[type-arg]
        try:
            from smartclaw.agent.graph import invoke

            # Emit a thinking event to signal start
            yield {
                "event": "thinking",
                "data": json.dumps({"session_key": session_key, "status": "started"}),
            }

            result = await invoke(
                graph,
                request_body.message,
                max_iterations=request_body.max_iterations,
                session_key=session_key,
                memory_store=memory_store,
                system_prompt=runtime.system_prompt,
                summarizer=runtime.summarizer,
            )

            # Emit done event with final answer
            yield {
                "event": "done",
                "data": json.dumps({
                    "session_key": session_key,
                    "response": result.get("final_answer") or "",
                    "iterations": result.get("iteration", 0),
                }),
            }
        except Exception as exc:
            logger.error("chat_stream_error", error=str(exc))
            yield {
                "event": "error",
                "data": json.dumps({"error": str(exc)}),
            }

    return EventSourceResponse(event_generator())
