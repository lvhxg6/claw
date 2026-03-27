"""Sessions router — GET/DELETE /api/sessions/{session_key}/*."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from langchain_core.messages import message_to_dict

from smartclaw.gateway.models import (
    AttachmentInfo,
    SessionConfigRequest,
    SessionHistoryResponse,
    SessionListItemData,
    SessionStatsResponse,
    SessionSummaryResponse,
)
from smartclaw.uploads.service import UploadService

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    return max(0, len(text) * 2 // 5)


def _estimate_messages_tokens(messages: list) -> int:
    total_chars = 0
    for msg in messages:
        content = getattr(msg, "content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total_chars += len(block.get("text", ""))
                elif isinstance(block, str):
                    total_chars += len(block)
        total_chars += 12
    return max(0, total_chars * 2 // 5)


@router.get("", response_model=list[SessionListItemData])
async def list_sessions(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[SessionListItemData]:
    """Return recent sessions for the workspace UI."""
    memory_store = request.app.state.memory_store
    if memory_store is None:
        return []
    try:
        sessions = await memory_store.list_sessions(limit=limit)
    except Exception:
        return []
    return [SessionListItemData(**item) for item in sessions]


@router.get("/{session_key}/history", response_model=SessionHistoryResponse)
async def get_history(session_key: str, request: Request) -> SessionHistoryResponse:
    """Return conversation history for a session. Empty list if not found."""
    memory_store = request.app.state.memory_store
    try:
        messages = await memory_store.get_history(session_key)
        return SessionHistoryResponse(
            session_key=session_key,
            messages=[message_to_dict(m) for m in messages],
        )
    except Exception:
        return SessionHistoryResponse(session_key=session_key, messages=[])


@router.get("/{session_key}/summary", response_model=SessionSummaryResponse)
async def get_summary(session_key: str, request: Request) -> SessionSummaryResponse:
    """Return summary for a session. Empty string if not found."""
    memory_store = request.app.state.memory_store
    try:
        summary = await memory_store.get_summary(session_key)
        return SessionSummaryResponse(session_key=session_key, summary=summary)
    except Exception:
        return SessionSummaryResponse(session_key=session_key, summary="")


@router.get("/{session_key}/stats", response_model=SessionStatsResponse)
async def get_session_stats(session_key: str, request: Request) -> SessionStatsResponse:
    """Return estimated context usage and latest token stats for a session."""
    memory_store = request.app.state.memory_store
    runtime = request.app.state.runtime
    settings = request.app.state.settings
    try:
        history = await memory_store.get_history(session_key)
    except Exception:
        history = []
    try:
        summary = await memory_store.get_summary(session_key)
    except Exception:
        summary = ""
    try:
        attachments = await memory_store.list_attachments(session_key)
    except Exception:
        attachments = []
    try:
        session_config = await memory_store.get_session_config(session_key)
    except Exception:
        session_config = None

    history_tokens = (
        runtime.summarizer.estimate_tokens(history)
        if getattr(runtime, "summarizer", None) is not None
        else _estimate_messages_tokens(history)
    )
    summary_tokens = _estimate_text_tokens(summary)
    system_prompt = getattr(runtime, "system_prompt", "") or ""
    system_prompt_tokens = _estimate_text_tokens(system_prompt)
    attachment_text = "\n".join(item.get("extract_text", "") for item in attachments if item.get("extract_text"))
    attachment_tokens = _estimate_text_tokens(attachment_text)
    total_context_tokens = system_prompt_tokens + history_tokens + summary_tokens + attachment_tokens
    context_window = int(getattr(settings.memory, "context_window", 0) or 0)
    usage_ratio = (total_context_tokens / context_window) if context_window > 0 else 0.0

    config = (session_config or {}).get("config") or {}
    if not isinstance(config, dict):
        config = {}
    runtime_stats = config.get("runtime_stats") or {}
    last_token_stats = runtime_stats.get("last_token_stats")
    if not isinstance(last_token_stats, dict):
        last_token_stats = None

    return SessionStatsResponse(
        session_key=session_key,
        message_count=len(history),
        attachment_count=len(attachments),
        system_prompt_tokens_est=system_prompt_tokens,
        history_tokens_est=history_tokens,
        summary_tokens_est=summary_tokens,
        attachment_tokens_est=attachment_tokens,
        context_tokens_est=total_context_tokens,
        context_window=context_window,
        context_usage_ratio=round(usage_ratio, 4),
        last_token_stats=last_token_stats,
        provider_cache_supported=False,
        provider_cache_tokens=None,
    )


@router.get("/{session_key}/attachments", response_model=list[AttachmentInfo])
async def list_session_attachments(session_key: str, request: Request) -> list[AttachmentInfo]:
    """Return attachments linked to a session."""
    memory_store = request.app.state.memory_store
    try:
        records = await memory_store.list_attachments(session_key)
    except Exception:
        return []
    return [
        AttachmentInfo(
            asset_id=item["asset_id"],
            session_key=item.get("session_key"),
            filename=item["filename"],
            media_type=item["media_type"],
            kind=item["kind"],
            size_bytes=int(item.get("size_bytes", 0)),
            status=item.get("status", "uploaded"),
            extract_status=item.get("extract_status", "pending"),
            extract_summary=item.get("extract_summary") or None,
            error_message=item.get("error_message") or None,
            created_at=item.get("created_at"),
            updated_at=item.get("updated_at"),
        )
        for item in records
    ]


@router.get("/{session_key}/decisions")
async def get_session_decisions(session_key: str):
    """Return decision records for a session. Empty list if not found."""
    from smartclaw.observability import decision_collector

    records = decision_collector.get_decisions(session_key)
    return [r.to_dict() for r in records]


@router.delete("/{session_key}")
async def delete_session(session_key: str, request: Request) -> dict:  # type: ignore[type-arg]
    """Delete a session's history and summary."""
    memory_store = request.app.state.memory_store
    settings = request.app.state.settings
    service = UploadService(memory_store, settings)
    try:
        attachments = await service.list_attachments(session_key)
    except Exception:
        attachments = []

    for attachment in attachments:
        try:
            await service.delete_attachment(attachment.asset_id)
        except Exception:
            # Best-effort filesystem cleanup; metadata is force-cleared below.
            pass

    try:
        if hasattr(memory_store, "delete_attachments_for_session"):
            await memory_store.delete_attachments_for_session(session_key)
    except Exception:
        pass

    try:
        if hasattr(memory_store, "delete_session"):
            await memory_store.delete_session(session_key)
        else:
            await memory_store.set_history(session_key, [])
            await memory_store.set_summary(session_key, "")
            if hasattr(memory_store, "delete_session_config"):
                await memory_store.delete_session_config(session_key)
    except Exception:
        pass
    return {"deleted": True}


@router.put("/{session_key}/config")
async def set_session_config(
    session_key: str,
    body: SessionConfigRequest,
    request: Request,
) -> dict:  # type: ignore[type-arg]
    """Persist session-level model override."""
    memory_store = request.app.state.runtime.memory_store
    if memory_store is None:
        return {"error": "Memory store not available"}
    try:
        await memory_store.set_session_config(
            session_key, model_override=body.model
        )
        return {"session_key": session_key, "model_override": body.model}
    except Exception as exc:
        return {"error": str(exc)}
