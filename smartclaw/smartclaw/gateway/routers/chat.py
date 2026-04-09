"""Chat router — POST /api/chat, POST /api/chat/stream."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
from collections.abc import AsyncGenerator
from contextlib import suppress
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from smartclaw.gateway.models import ChatRequest, ChatResponse, ClarificationData
from smartclaw.hooks.events import HookEvent
from smartclaw.uploads import build_attachment_context
from smartclaw.uploads.models import AttachmentRecord
from smartclaw.uploads.service import UploadService

logger = structlog.get_logger(component="gateway.chat")
_TRUTHY = {"1", "true", "yes", "on"}
_TRACE_APPROVAL = os.environ.get("SMARTCLAW_TRACE_APPROVAL", "").strip().lower() in _TRUTHY

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


def _todo_status_snapshot(todos: list[dict[str, Any]] | None) -> dict[str, int]:
    counts: dict[str, int] = {}
    for todo in todos or []:
        if not isinstance(todo, dict):
            continue
        status = str(todo.get("status", "unknown") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _log_request_trace(
    *,
    endpoint: str,
    session_key: str,
    request_body: ChatRequest,
) -> None:
    if not _TRACE_APPROVAL:
        return
    logger.info(
        "chat_request_trace",
        endpoint=endpoint,
        session_key=session_key,
        mode=request_body.mode,
        scenario_type=request_body.scenario_type,
        task_profile=request_body.task_profile,
        capability_pack=request_body.capability_pack,
        approved=request_body.approved,
        approval_action=request_body.approval_action,
        model=request_body.model,
        message_preview=(request_body.message or "")[:160],
    )


def _resolve_execution(request_body: ChatRequest, runtime: Any) -> tuple[str, Any, str, str | None, dict | None]:
    """Resolve execution mode and graph for this request."""
    capability_resolution = runtime.resolve_capability_pack(
        requested_name=request_body.capability_pack,
        scenario_type=request_body.scenario_type,
    )
    scenario_type = request_body.scenario_type
    task_profile = request_body.task_profile
    preferred_mode = request_body.mode
    if capability_resolution.pack is not None:
        scenario_type = scenario_type or (
            capability_resolution.pack.scenario_types[0]
            if capability_resolution.pack.scenario_types
            else None
        )
        task_profile = task_profile or capability_resolution.pack.task_profile
        if preferred_mode in {None, "", "auto"} and capability_resolution.pack.preferred_mode:
            preferred_mode = capability_resolution.pack.preferred_mode

    decision = runtime.resolve_mode(
        requested_mode=preferred_mode,
        message=request_body.message,
        scenario_type=scenario_type,
        task_profile=task_profile,
    )
    graph = runtime.create_request_graph(
        request_body.model or None,
        mode=decision.resolved_mode,
        capability_pack=capability_resolution.resolved_name,
    )
    system_prompt = runtime.compose_system_prompt(capability_pack=capability_resolution.resolved_name)
    capability_policy = runtime.build_capability_policy(
        capability_pack=capability_resolution.resolved_name
    )
    return (
        decision.resolved_mode,
        graph,
        system_prompt,
        capability_resolution.resolved_name,
        capability_policy,
    )


def _build_approval_response(policy: dict | None, *, session_key: str) -> ChatResponse:
    from smartclaw.capabilities.governance import build_approval_request

    clarification = build_approval_request(policy)
    return ChatResponse(
        session_key=session_key,
        response="",
        iterations=0,
        error=None,
        token_stats=None,
        clarification=ClarificationData(
            kind=clarification.get("kind"),
            question=clarification["question"],
            details=clarification.get("details"),
            options=clarification.get("options"),
            option_descriptions=clarification.get("option_descriptions"),
        ),
    )


async def _apply_session_model_override(
    request_body: ChatRequest,
    *,
    session_key: str,
    memory_store: Any,
) -> ChatRequest:
    """Apply persisted session-level model override when request omits model."""
    if request_body.model or memory_store is None:
        return request_body
    try:
        cfg = await memory_store.get_session_config(session_key)
        if cfg and cfg.get("model_override"):
            return request_body.model_copy(update={"model": cfg["model_override"]})
    except Exception:
        pass
    return request_body


async def _persist_session_token_stats(
    *,
    memory_store: Any,
    session_key: str,
    token_stats: dict[str, int] | None,
) -> None:
    """Persist latest token stats in session config JSON for later stats queries."""
    if memory_store is None or not session_key or token_stats is None:
        return
    try:
        existing = await memory_store.get_session_config(session_key) or {}
        model_override = existing.get("model_override")
        config = existing.get("config") or {}
        if not isinstance(config, dict):
            config = {}
        config["runtime_stats"] = {
            "last_token_stats": token_stats,
        }
        await memory_store.set_session_config(
            session_key,
            model_override=model_override,
            config_json=json.dumps(config, ensure_ascii=False),
        )
    except Exception:
        pass


async def _resolve_session_key(
    request_body: ChatRequest,
    *,
    runtime: Any,
    settings: Any,
) -> str:
    """Resolve session key, preferring attachment-linked sessions when present."""
    if request_body.session_key:
        return request_body.session_key
    attachment_ids = request_body.attachment_ids or []
    if not attachment_ids:
        return str(uuid.uuid4())

    service = UploadService(runtime.memory_store, settings)
    attachments = await service.get_attachments(list(attachment_ids))
    attachment_session_keys = {item.session_key for item in attachments if item.session_key}
    if len(attachment_session_keys) == 1:
        return next(iter(attachment_session_keys))
    return str(uuid.uuid4())


async def _resolve_request_attachments(
    request_body: ChatRequest,
    *,
    session_key: str,
    runtime: Any,
    settings: Any,
) -> list[AttachmentRecord]:
    """Resolve attachment ids into attachment records and validate session affinity."""
    attachment_ids = request_body.attachment_ids or []
    if not attachment_ids:
        return []

    service = UploadService(runtime.memory_store, settings)
    attachments = await service.get_attachments(list(attachment_ids))
    if len(attachments) != len(attachment_ids):
        raise ValueError("One or more attachments were not found")

    for attachment in attachments:
        if attachment.session_key and attachment.session_key != session_key:
            raise ValueError("Attachment session mismatch")

    return attachments


async def _compose_request_message(
    request_body: ChatRequest,
    *,
    session_key: str,
    runtime: Any,
    settings: Any,
) -> str:
    """Merge uploaded attachment summaries into the effective user message."""
    attachments = await _resolve_request_attachments(
        request_body,
        session_key=session_key,
        runtime=runtime,
        settings=settings,
    )
    if not attachments:
        return request_body.message

    attachment_context = build_attachment_context(attachments, settings.uploads)
    if not attachment_context:
        return request_body.message
    return attachment_context + "\n\n[User Request]\n" + request_body.message


def _effective_model_config(runtime: Any, model_ref: str | None) -> Any:
    """Return a request-scoped model config, preserving fallbacks and defaults."""
    if not model_ref:
        return runtime.model_config
    return runtime.model_config.model_copy(update={"primary": model_ref})


def _merge_attachment_context(
    attachments: list[AttachmentRecord],
    *,
    settings: Any,
    user_message: str,
) -> str:
    """Merge attachment context into a plain-text user request."""
    if not attachments:
        return user_message
    attachment_context = build_attachment_context(attachments, settings.uploads)
    if not attachment_context:
        return user_message
    return attachment_context + "\n\n[User Request]\n" + user_message


def _resolve_image_strategy(
    *,
    runtime: Any,
    settings: Any,
    request_body: ChatRequest,
    attachments: list[AttachmentRecord],
) -> tuple[str, Any]:
    """Resolve image handling strategy for the effective model and request attachments."""
    image_attachments = [item for item in attachments if item.media_type.startswith("image/")]
    capabilities = runtime.resolve_model_capabilities(request_body.model or None)
    if not image_attachments:
        return "text_only", capabilities

    image_mode = (settings.uploads.image_analysis_mode or "disabled").strip().lower()
    if image_mode == "disabled":
        return "disabled", capabilities
    if image_mode == "ocr_only":
        return "ocr_only", capabilities
    if image_mode == "vision_only":
        if not capabilities.supports_vision:
            raise ValueError("Current model does not support image input required by vision_only mode")
        return "vision_only", capabilities
    if image_mode == "vision_preferred":
        if capabilities.supports_vision:
            return "vision_preferred", capabilities
        return "ocr_only", capabilities
    return "ocr_only", capabilities


def _build_vision_user_message(
    *,
    request_body: ChatRequest,
    attachments: list[AttachmentRecord],
    settings: Any,
    capabilities: Any,
):
    """Build a multimodal user message from uploaded image attachments."""
    from smartclaw.agent.graph import create_vision_message_batch

    image_attachments = [item for item in attachments if item.media_type.startswith("image/")]
    non_image_attachments = [item for item in attachments if not item.media_type.startswith("image/")]

    if not image_attachments:
        raise ValueError("No image attachments available for multimodal analysis")

    if capabilities.max_image_count is not None and len(image_attachments) > capabilities.max_image_count:
        raise ValueError(f"Current model supports at most {capabilities.max_image_count} images per request")

    image_payloads: list[dict[str, str]] = []
    for attachment in image_attachments:
        image_bytes = Path(attachment.storage_path).read_bytes()
        if capabilities.max_image_bytes is not None and len(image_bytes) > capabilities.max_image_bytes:
            raise ValueError(f"Attachment '{attachment.filename}' exceeds the model image size limit")
        image_payloads.append(
            {
                "media_type": attachment.media_type,
                "image_base64": base64.b64encode(image_bytes).decode("ascii"),
            }
        )

    sections: list[str] = []
    if non_image_attachments:
        attachment_context = build_attachment_context(non_image_attachments, settings.uploads)
        if attachment_context:
            sections.append(attachment_context)

    sections.append("[Images]")
    for attachment in image_attachments:
        sections.append(f"- {attachment.filename} ({attachment.media_type})")

    sections.append("[User Request]\n" + request_body.message)
    text = "\n".join(section for section in sections if section).strip()
    return create_vision_message_batch(text, image_payloads)


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
        with suppress(asyncio.QueueFull):
            queue.put_nowait({**event.to_dict(), "hook_point": hook_point})

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

    if hp == "clarification":
        return {
            "event": "clarification",
            "data": json.dumps(
                {
                    "session_key": evt_dict.get("session_key"),
                    "kind": evt_dict.get("kind"),
                    "question": evt_dict.get("question", ""),
                    "details": evt_dict.get("details"),
                    "options": evt_dict.get("options"),
                    "option_descriptions": evt_dict.get("option_descriptions"),
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


def _clarification_event_data(
    clarification_request: dict[str, Any],
    *,
    session_key: str,
) -> str:
    return json.dumps(
        {
            "session_key": session_key,
            "kind": clarification_request.get("kind"),
            "question": clarification_request["question"],
            "details": clarification_request.get("details"),
            "options": clarification_request.get("options"),
            "option_descriptions": clarification_request.get("option_descriptions"),
        },
        ensure_ascii=False,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=ChatResponse)
async def chat(request_body: ChatRequest, request: Request) -> ChatResponse:
    """Synchronous chat endpoint: invoke Agent Graph and return full result."""
    runtime = request.app.state.runtime
    settings = request.app.state.settings
    session_key = await _resolve_session_key(request_body, runtime=runtime, settings=settings)
    memory_store = runtime.memory_store

    # Track active request for model switching protection
    runtime.increment_requests()

    request_body = await _apply_session_model_override(
        request_body,
        session_key=session_key,
        memory_store=memory_store,
    )
    _log_request_trace(endpoint="chat", session_key=session_key, request_body=request_body)

    try:
        resolved_mode, graph, system_prompt, capability_pack, capability_policy = _resolve_execution(
            request_body,
            runtime,
        )
    except ValueError as exc:
        runtime.decrement_requests()
        return JSONResponse(  # type: ignore[return-value]
            status_code=400,
            content={"error": str(exc)},
        )

    if capability_policy and capability_policy.get("approval_required") and not request_body.approved:
        if _TRACE_APPROVAL:
            logger.info(
                "chat_request_approval_blocked",
                endpoint="chat",
                session_key=session_key,
                approval_required=bool(capability_policy.get("approval_required")),
                approved=request_body.approved,
                approval_action=request_body.approval_action,
            )
        runtime.decrement_requests()
        return _build_approval_response(capability_policy, session_key=session_key)

    try:
        from smartclaw.agent.graph import invoke, invoke_multimodal

        attachments = await _resolve_request_attachments(
            request_body,
            session_key=session_key,
            runtime=runtime,
            settings=settings,
        )
        image_strategy, capabilities = _resolve_image_strategy(
            runtime=runtime,
            settings=settings,
            request_body=request_body,
            attachments=attachments,
        )

        if image_strategy in {"vision_preferred", "vision_only"}:
            user_message = _build_vision_user_message(
                request_body=request_body,
                attachments=attachments,
                settings=settings,
                capabilities=capabilities,
            )
            result = await invoke_multimodal(
                user_message,
                model_config=_effective_model_config(runtime, request_body.model),
                session_key=session_key,
                memory_store=memory_store,
                system_prompt=system_prompt,
                summarizer=runtime.summarizer,
                context_engine=getattr(runtime, "context_engine", None),
            )
        else:
            effective_message = _merge_attachment_context(
                attachments,
                settings=settings,
                user_message=request_body.message,
            )

            result = await invoke(
                graph,
                effective_message,
                max_iterations=request_body.max_iterations,
                session_key=session_key,
                memory_store=memory_store,
                system_prompt=system_prompt,
                summarizer=runtime.summarizer,
                context_engine=getattr(runtime, "context_engine", None),
                mode=resolved_mode,
                capability_pack=capability_pack,
                capability_policy=capability_policy,
                approved=request_body.approved,
                approval_action=request_body.approval_action,
            )
        if _TRACE_APPROVAL:
            logger.info(
                "chat_result_trace",
                endpoint="chat",
                session_key=session_key,
                phase_status=result.get("phase_status"),
                current_phase=result.get("current_phase"),
                error=result.get("error"),
                todo_status_counts=_todo_status_snapshot(result.get("todos") or []),
                todo_count=len(result.get("todos") or []),
            )
        clarification = None
        cr = result.get("clarification_request")
        if cr:
            clarification = ClarificationData(
                kind=cr.get("kind"),
                question=cr["question"],
                details=cr.get("details"),
                options=cr.get("options"),
                option_descriptions=cr.get("option_descriptions"),
            )
        await _persist_session_token_stats(
            memory_store=memory_store,
            session_key=session_key,
            token_stats=result.get("token_stats"),
        )
        return ChatResponse(
            session_key=session_key,
            response=result.get("final_answer") or "",
            iterations=result.get("iteration", 0),
            error=result.get("error"),
            token_stats=result.get("token_stats"),
            clarification=clarification,
        )
    except ValueError as exc:
        logger.warning("chat_attachment_error", error=str(exc))
        return JSONResponse(  # type: ignore[return-value]
            status_code=400,
            content={"error": str(exc)},
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
    runtime = request.app.state.runtime
    settings = request.app.state.settings
    session_key = await _resolve_session_key(request_body, runtime=runtime, settings=settings)
    memory_store = runtime.memory_store
    max_iterations = request_body.max_iterations

    # Track active request for model switching protection
    runtime.increment_requests()

    request_body = await _apply_session_model_override(
        request_body,
        session_key=session_key,
        memory_store=memory_store,
    )
    _log_request_trace(endpoint="chat_stream", session_key=session_key, request_body=request_body)

    try:
        resolved_mode, graph, system_prompt, capability_pack, capability_policy = _resolve_execution(
            request_body,
            runtime,
        )
    except ValueError as exc:
        runtime.decrement_requests()
        return JSONResponse(  # type: ignore[return-value]
            status_code=400,
            content={"error": str(exc)},
        )

    if capability_policy and capability_policy.get("approval_required") and not request_body.approved:
        if _TRACE_APPROVAL:
            logger.info(
                "chat_request_approval_blocked",
                endpoint="chat_stream",
                session_key=session_key,
                approval_required=bool(capability_policy.get("approval_required")),
                approved=request_body.approved,
                approval_action=request_body.approval_action,
            )
        async def approval_generator() -> AsyncGenerator[dict, None]:  # type: ignore[type-arg]
            from smartclaw.capabilities.governance import build_approval_request

            clarification = build_approval_request(capability_policy)
            yield {
                "event": "clarification",
                "data": _clarification_event_data(clarification, session_key=session_key),
            }
            yield {
                "event": "done",
                "data": json.dumps(
                    {
                        "session_key": session_key,
                        "response": "",
                        "iterations": 0,
                    },
                    ensure_ascii=False,
                ),
            }
            runtime.decrement_requests()

        return EventSourceResponse(approval_generator())

    async def event_generator() -> AsyncGenerator[dict, None]:  # type: ignore[type-arg]
        from smartclaw.agent.graph import invoke, invoke_multimodal
        effective_message = request_body.message
        attachments: list[AttachmentRecord] = []
        use_multimodal = False
        invoke_task_kwargs: dict[str, Any] = {}

        try:
            attachments = await _resolve_request_attachments(
                request_body,
                session_key=session_key,
                runtime=runtime,
                settings=settings,
            )
            image_strategy, capabilities = _resolve_image_strategy(
                runtime=runtime,
                settings=settings,
                request_body=request_body,
                attachments=attachments,
            )
            if image_strategy in {"vision_preferred", "vision_only"}:
                effective_message = _build_vision_user_message(
                    request_body=request_body,
                    attachments=attachments,
                    settings=settings,
                    capabilities=capabilities,
                )
                use_multimodal = True
                invoke_task_kwargs = {
                    "model_config": _effective_model_config(runtime, request_body.model),
                    "session_key": session_key,
                    "memory_store": memory_store,
                    "system_prompt": system_prompt,
                    "summarizer": runtime.summarizer,
                    "context_engine": getattr(runtime, "context_engine", None),
                }
            else:
                effective_message = _merge_attachment_context(
                    attachments,
                    settings=settings,
                    user_message=request_body.message,
                )
                invoke_task_kwargs = {
                    "max_iterations": max_iterations,
                    "session_key": session_key,
                    "memory_store": memory_store,
                    "system_prompt": system_prompt,
                    "summarizer": runtime.summarizer,
                    "context_engine": getattr(runtime, "context_engine", None),
                    "mode": resolved_mode,
                    "capability_pack": capability_pack,
                    "capability_policy": capability_policy,
                    "approved": request_body.approved,
                    "approval_action": request_body.approval_action,
                }
            queue: asyncio.Queue = asyncio.Queue(maxsize=200)  # type: ignore[type-arg]
            handlers = _register_stream_handlers(queue)
        except ValueError as exc:
            yield {
                "event": "error",
                "data": json.dumps({"error": str(exc)}, ensure_ascii=False),
            }
            runtime.decrement_requests()
            return
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
                if use_multimodal:
                    result = await invoke_multimodal(
                        effective_message,  # type: ignore[arg-type]
                        **invoke_task_kwargs,
                    )
                else:
                    result = await invoke(
                        graph,
                        effective_message,
                        **invoke_task_kwargs,
                    )
                cr = result.get("clarification_request")
                if cr:
                    yield {
                        "event": "clarification",
                        "data": _clarification_event_data(cr, session_key=session_key),
                    }
                yield {
                    "event": "done",
                    "data": json.dumps(
                        {
                            "session_key": session_key,
                            "response": result.get("final_answer") or "",
                            "iterations": result.get("iteration", 0),
                            "token_stats": result.get("token_stats"),
                            "phase_status": result.get("phase_status"),
                            "current_phase": result.get("current_phase"),
                            "todos": result.get("todos") or [],
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
            if use_multimodal:
                task = asyncio.create_task(
                    invoke_multimodal(
                        effective_message,  # type: ignore[arg-type]
                        **invoke_task_kwargs,
                    )
                )
            else:
                task = asyncio.create_task(
                    invoke(
                        graph,
                        effective_message,
                        **invoke_task_kwargs,
                    )
                )

            # Main loop: read events from queue while invoke runs
            while not task.done():
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=1.0)
                    sse = _format_sse(evt)
                    if sse:
                        yield sse
                except TimeoutError:
                    continue

            # Drain remaining events
            while not queue.empty():
                evt = queue.get_nowait()
                sse = _format_sse(evt)
                if sse:
                    yield sse

            # Final event
            result = task.result()
            if _TRACE_APPROVAL:
                logger.info(
                    "chat_result_trace",
                    endpoint="chat_stream",
                    session_key=session_key,
                    phase_status=result.get("phase_status"),
                    current_phase=result.get("current_phase"),
                    error=result.get("error"),
                    todo_status_counts=_todo_status_snapshot(result.get("todos") or []),
                    todo_count=len(result.get("todos") or []),
                )
            cr = result.get("clarification_request")
            if cr:
                yield {
                    "event": "clarification",
                    "data": _clarification_event_data(cr, session_key=session_key),
                }
            await _persist_session_token_stats(
                memory_store=memory_store,
                session_key=session_key,
                token_stats=result.get("token_stats"),
            )
            yield {
                "event": "done",
                "data": json.dumps(
                    {
                        "session_key": session_key,
                        "response": result.get("final_answer") or "",
                        "iterations": result.get("iteration", 0),
                        "token_stats": result.get("token_stats"),
                        "phase_status": result.get("phase_status"),
                        "current_phase": result.get("current_phase"),
                        "todos": result.get("todos") or [],
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
