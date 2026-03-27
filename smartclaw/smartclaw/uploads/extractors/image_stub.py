"""Image upload stub extractor."""

from __future__ import annotations

from smartclaw.uploads.models import ExtractionResult


class ImageStubExtractor:
    """Accept image uploads without semantic extraction."""

    def extract(self, content: bytes, *, filename: str, media_type: str) -> ExtractionResult:
        return ExtractionResult(
            text="",
            summary=f"{filename} 是图片附件，当前未启用 OCR 或多模态图片理解",
            supported=False,
        )
