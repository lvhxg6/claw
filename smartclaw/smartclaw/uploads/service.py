"""Attachment upload service."""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from uuid import uuid4

import structlog
from fastapi import HTTPException, UploadFile

from smartclaw.config.settings import SmartClawSettings
from smartclaw.memory.store import MemoryStore
from smartclaw.uploads.extractors import (
    CsvExtractor,
    DocxExtractor,
    ImageStubExtractor,
    JsonYamlExtractor,
    OcrImageExtractor,
    PdfExtractor,
    PlainTextExtractor,
    XlsxExtractor,
)
from smartclaw.uploads.models import AttachmentRecord, ExtractionResult

logger = structlog.get_logger(component="uploads.service")


class UploadService:
    """Handles attachment validation, storage, extraction, and lookup."""

    def __init__(self, memory_store: MemoryStore, settings: SmartClawSettings) -> None:
        self._memory_store = memory_store
        self._settings = settings
        self._upload_settings = settings.uploads
        workspace = settings.agent_defaults.workspace
        root_dir = self._upload_settings.root_dir.replace("{workspace}", workspace)
        self._root_dir = Path(root_dir).expanduser()
        self._plain_text = PlainTextExtractor()
        self._json_yaml = JsonYamlExtractor()
        self._csv = CsvExtractor()
        self._pdf = PdfExtractor()
        self._docx = DocxExtractor()
        self._xlsx = XlsxExtractor()
        image_mode = (self._upload_settings.image_analysis_mode or "disabled").strip().lower()
        self._image = (
            OcrImageExtractor(
                enabled=True,
                tesseract_cmd=self._upload_settings.ocr_tesseract_cmd,
                languages=self._upload_settings.ocr_languages,
            )
            if image_mode in {"ocr_only", "vision_preferred"}
            else ImageStubExtractor()
        )

    async def save_upload(self, upload: UploadFile, session_key: str | None = None) -> AttachmentRecord:
        """Persist an uploaded file and extract supported text."""
        if not self._upload_settings.enabled:
            raise HTTPException(status_code=404, detail="Uploads are disabled")
        if not upload.filename:
            raise HTTPException(status_code=400, detail="Missing filename")

        resolved_session_key = session_key or str(uuid4())
        existing = await self._memory_store.list_attachments(resolved_session_key)
        if len(existing) >= self._upload_settings.max_files_per_session:
            raise HTTPException(status_code=400, detail="Too many attachments for this session")

        content = await upload.read()
        size_bytes = len(content)
        max_bytes = self._upload_settings.max_file_size_mb * 1024 * 1024
        if size_bytes > max_bytes:
            raise HTTPException(status_code=400, detail="File too large")

        filename = Path(upload.filename).name or "upload.bin"
        media_type = _resolve_media_type(filename, upload.content_type)
        if media_type not in self._upload_settings.allowed_media_types:
            raise HTTPException(status_code=400, detail=f"Unsupported media type: {media_type}")

        asset_id = "att_" + uuid4().hex[:12]
        kind = _classify_kind(media_type)
        digest = hashlib.sha256(content).hexdigest()
        self._root_dir.mkdir(parents=True, exist_ok=True)
        target_dir = self._root_dir / resolved_session_key
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"{asset_id}_{filename}"
        target_path.write_bytes(content)

        extraction = self._extract(content, filename=filename, media_type=media_type)
        record = AttachmentRecord(
            asset_id=asset_id,
            session_key=resolved_session_key,
            filename=filename,
            media_type=media_type,
            kind=kind,
            storage_path=str(target_path),
            size_bytes=size_bytes,
            sha256=digest,
            status="uploaded" if extraction.error is None else "failed",
            extract_status=_extract_status(extraction),
            extract_text=extraction.text,
            extract_summary=extraction.summary,
            error_message=extraction.error or "",
        )
        await self._memory_store.upsert_attachment(record.to_dict())
        logger.info("attachment_uploaded", asset_id=asset_id, session_key=resolved_session_key, media_type=media_type)
        return record

    async def get_attachment(self, asset_id: str) -> AttachmentRecord | None:
        record = await self._memory_store.get_attachment(asset_id)
        if record is None:
            return None
        return AttachmentRecord.from_dict(record)

    async def list_attachments(self, session_key: str) -> list[AttachmentRecord]:
        records = await self._memory_store.list_attachments(session_key)
        return [AttachmentRecord.from_dict(item) for item in records]

    async def get_attachments(self, asset_ids: list[str]) -> list[AttachmentRecord]:
        records = await self._memory_store.get_attachments(asset_ids)
        return [AttachmentRecord.from_dict(item) for item in records]

    async def delete_attachment(self, asset_id: str) -> bool:
        record = await self._memory_store.get_attachment(asset_id)
        if record is None:
            return False
        path = Path(record["storage_path"])
        if path.exists():
            path.unlink(missing_ok=True)
        await self._memory_store.delete_attachment(asset_id)
        return True

    def _extract(self, content: bytes, *, filename: str, media_type: str) -> ExtractionResult:
        if media_type.startswith("image/"):
            return self._image.extract(content, filename=filename, media_type=media_type)
        if media_type == "application/pdf":
            return self._pdf.extract(content, filename=filename, media_type=media_type)
        if media_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            return self._docx.extract(content, filename=filename, media_type=media_type)
        if media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
            return self._xlsx.extract(content, filename=filename, media_type=media_type)
        if media_type == "text/csv":
            return self._csv.extract(content, filename=filename, media_type=media_type)
        if media_type in {"application/json", "application/x-yaml", "text/yaml", "text/x-yaml"}:
            return self._json_yaml.extract(content, filename=filename, media_type=media_type)
        return self._plain_text.extract(content, filename=filename, media_type=media_type)


def _resolve_media_type(filename: str, declared: str | None) -> str:
    declared_type = (declared or "").strip().lower()
    if declared_type and declared_type != "application/octet-stream":
        return declared_type
    guessed, _ = mimetypes.guess_type(filename)
    return (guessed or "application/octet-stream").lower()


def _classify_kind(media_type: str) -> str:
    if media_type.startswith("image/"):
        return "image"
    if media_type in {"text/csv", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}:
        return "table"
    if media_type.startswith("text/") or media_type in {"application/json", "application/x-yaml"}:
        return "text"
    return "document"


def _extract_status(result: ExtractionResult) -> str:
    if result.error:
        return "failed"
    if not result.supported:
        return "unsupported"
    return "success"
