"""PDF extractor."""

from __future__ import annotations

from io import BytesIO

from smartclaw.uploads.extractors.plain_text import _build_summary
from smartclaw.uploads.models import ExtractionResult


class PdfExtractor:
    """Extract text from PDF files using pypdf when available."""

    def extract(self, content: bytes, *, filename: str, media_type: str) -> ExtractionResult:
        try:
            from pypdf import PdfReader
        except ImportError:
            return ExtractionResult(
                text="",
                summary=f"{filename} 是 PDF 附件，但当前环境未安装 PDF 解析依赖",
                supported=False,
            )

        try:
            reader = PdfReader(BytesIO(content))
            pages: list[str] = []
            for page in reader.pages:
                extracted = (page.extract_text() or "").strip()
                if extracted:
                    pages.append(extracted)
            text = "\n\n".join(pages).strip()
        except Exception as exc:
            return ExtractionResult(
                text="",
                summary=f"{filename} PDF 提取失败",
                supported=False,
                error=str(exc),
            )

        if not text:
            return ExtractionResult(
                text="",
                summary=f"{filename} 未提取到可读文本，可能是扫描版 PDF",
                supported=False,
            )

        return ExtractionResult(text=text, summary=_build_summary(text, filename=filename), supported=True)
