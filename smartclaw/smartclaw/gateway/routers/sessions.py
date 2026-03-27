"""Sessions router — GET/DELETE /api/sessions/{session_key}/*."""

from __future__ import annotations

from fastapi import APIRouter, Request
from langchain_core.messages import message_to_dict

from smartclaw.gateway.models import SessionConfigRequest, SessionHistoryResponse, SessionSummaryResponse

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


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
    try:
        await memory_store.set_history(session_key, [])
        await memory_store.set_summary(session_key, "")
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
