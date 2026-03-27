"""Uploads router — attachment upload, lookup, and delete."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from smartclaw.gateway.models import AttachmentInfo, UploadResponse
from smartclaw.uploads.service import UploadService

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


def _get_service(request: Request) -> UploadService:
    memory_store = request.app.state.runtime.memory_store
    settings = request.app.state.settings
    return UploadService(memory_store, settings)


@router.post("", response_model=UploadResponse)
async def upload_file(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    session_key: Annotated[str | None, Form()] = None,
) -> UploadResponse:
    """Upload a file and extract supported text content."""
    service = _get_service(request)
    record = await service.save_upload(file, session_key=session_key)
    return UploadResponse(
        asset_id=record.asset_id,
        session_key=record.session_key,
        filename=record.filename,
        media_type=record.media_type,
        kind=record.kind,
        size_bytes=record.size_bytes,
        status=record.status,
        extract_status=record.extract_status,
        extract_summary=record.extract_summary or None,
        error_message=record.error_message or None,
    )


@router.get("/{asset_id}", response_model=AttachmentInfo)
async def get_upload(asset_id: str, request: Request) -> AttachmentInfo:
    """Return metadata for one uploaded attachment."""
    service = _get_service(request)
    record = await service.get_attachment(asset_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return AttachmentInfo(
        asset_id=record.asset_id,
        session_key=record.session_key,
        filename=record.filename,
        media_type=record.media_type,
        kind=record.kind,
        size_bytes=record.size_bytes,
        status=record.status,
        extract_status=record.extract_status,
        extract_summary=record.extract_summary or None,
        error_message=record.error_message or None,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get("/{asset_id}/content")
async def get_upload_content(asset_id: str, request: Request) -> FileResponse:
    """Return raw uploaded attachment content for preview use."""
    service = _get_service(request)
    record = await service.get_attachment(asset_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    path = Path(record.storage_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Attachment content not found")
    return FileResponse(path, media_type=record.media_type, filename=record.filename)


@router.delete("/{asset_id}")
async def delete_upload(asset_id: str, request: Request) -> dict:
    """Delete an uploaded attachment."""
    service = _get_service(request)
    deleted = await service.delete_attachment(asset_id)
    return {"deleted": deleted}
