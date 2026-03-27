"""DOCX extractor."""

from __future__ import annotations

from io import BytesIO

from smartclaw.uploads.extractors.plain_text import _build_summary
from smartclaw.uploads.models import ExtractionResult


class DocxExtractor:
    """Extract text from DOCX files using python-docx when available."""

    def extract(self, content: bytes, *, filename: str, media_type: str) -> ExtractionResult:
        try:
            from docx import Document
        except ImportError:
            return ExtractionResult(
                text="",
                summary=f"{filename} 是 DOCX 附件，但当前环境未安装 DOCX 解析依赖",
                supported=False,
            )

        try:
            document = Document(BytesIO(content))
            parts = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
            text = "\n".join(parts).strip()
        except Exception as exc:
            return ExtractionResult(
                text="",
                summary=f"{filename} DOCX 提取失败",
                supported=False,
                error=str(exc),
            )

        if not text:
            return ExtractionResult(
                text="",
                summary=f"{filename} 已上传，但未提取到文本内容",
                supported=False,
            )

        return ExtractionResult(text=text, summary=_build_summary(text, filename=filename), supported=True)
