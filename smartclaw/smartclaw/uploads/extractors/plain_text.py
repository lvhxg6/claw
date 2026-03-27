"""Plain text and markdown extractors."""

from __future__ import annotations

from smartclaw.uploads.models import ExtractionResult


class PlainTextExtractor:
    """Decode text-like attachments as UTF-8."""

    def extract(self, content: bytes, *, filename: str, media_type: str) -> ExtractionResult:
        text = content.decode("utf-8", errors="replace").strip()
        summary = _build_summary(text, filename=filename)
        return ExtractionResult(text=text, summary=summary, supported=True)


def _build_summary(text: str, *, filename: str) -> str:
    if not text:
        return f"{filename} 已上传，但未提取到文本内容"
    normalized = " ".join(text.split())
    if len(normalized) <= 120:
        return normalized
    return normalized[:119] + "…"
