"""Attachment upload domain models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ExtractionResult:
    text: str
    summary: str
    supported: bool
    error: str | None = None


@dataclass(slots=True)
class AttachmentRecord:
    asset_id: str
    session_key: str | None
    filename: str
    media_type: str
    kind: str
    storage_path: str
    size_bytes: int
    sha256: str
    status: str
    extract_status: str
    extract_text: str
    extract_summary: str
    error_message: str = ""
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> AttachmentRecord:
        return cls(
            asset_id=str(data["asset_id"]),
            session_key=data.get("session_key"),
            filename=str(data["filename"]),
            media_type=str(data["media_type"]),
            kind=str(data["kind"]),
            storage_path=str(data["storage_path"]),
            size_bytes=int(data["size_bytes"]),
            sha256=str(data["sha256"]),
            status=str(data.get("status", "uploaded")),
            extract_status=str(data.get("extract_status", "pending")),
            extract_text=str(data.get("extract_text", "")),
            extract_summary=str(data.get("extract_summary", "")),
            error_message=str(data.get("error_message", "")),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )

    def to_dict(self) -> dict:
        return {
            "asset_id": self.asset_id,
            "session_key": self.session_key,
            "filename": self.filename,
            "media_type": self.media_type,
            "kind": self.kind,
            "storage_path": self.storage_path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "status": self.status,
            "extract_status": self.extract_status,
            "extract_text": self.extract_text,
            "extract_summary": self.extract_summary,
            "error_message": self.error_message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
