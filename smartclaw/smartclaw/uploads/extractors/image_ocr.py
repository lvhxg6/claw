"""Image OCR extractor."""

from __future__ import annotations

from io import BytesIO

from smartclaw.uploads.models import ExtractionResult


class OcrImageExtractor:
    """Extract text from image attachments using Pillow + pytesseract."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        tesseract_cmd: str = "tesseract",
        languages: list[str] | None = None,
    ) -> None:
        self._enabled = enabled
        self._tesseract_cmd = tesseract_cmd
        self._languages = list(languages or ["eng"])

    def extract(self, content: bytes, *, filename: str, media_type: str) -> ExtractionResult:
        if not self._enabled:
            return ExtractionResult(
                text="",
                summary=f"{filename} 是图片附件，当前图片分析策略为 disabled",
                supported=False,
            )

        try:
            from PIL import Image
        except ImportError:
            return ExtractionResult(
                text="",
                summary=f"{filename} 是图片附件，但当前环境未安装 Pillow",
                supported=False,
            )

        try:
            import pytesseract
        except ImportError:
            return ExtractionResult(
                text="",
                summary=f"{filename} 是图片附件，但当前环境未安装 pytesseract",
                supported=False,
            )

        pytesseract.pytesseract.tesseract_cmd = self._tesseract_cmd
        language = "+".join(self._languages)

        try:
            image = Image.open(BytesIO(content))
            image.load()
            width, height = image.size
            text = pytesseract.image_to_string(image, lang=language).strip()
        except pytesseract.TesseractNotFoundError:
            return ExtractionResult(
                text="",
                summary=f"{filename} 图片 OCR 失败，未找到 tesseract 可执行文件",
                supported=False,
            )
        except Exception as exc:
            error_message = str(exc)
            lowered = error_message.lower()
            if "failed loading language" in lowered or "could not initialize tesseract" in lowered:
                return ExtractionResult(
                    text="",
                    summary=f"{filename} 图片 OCR 失败，当前缺少所需语言包: {language}",
                    supported=False,
                    error=error_message,
                )
            return ExtractionResult(
                text="",
                summary=f"{filename} 图片 OCR 提取失败",
                supported=False,
                error=error_message,
            )

        if not text:
            return ExtractionResult(
                text="",
                summary=(
                    f"{filename} 已上传，图片尺寸 {width}x{height}，但未识别到文字。"
                    f" 当前 OCR 语言: {language}"
                ),
                supported=False,
            )

        normalized = " ".join(text.split())
        if len(normalized) > 120:
            normalized = normalized[:119] + "…"
        summary = f"{filename} 已完成 OCR；尺寸 {width}x{height}；识别摘要: {normalized}"
        return ExtractionResult(text=text, summary=summary, supported=True)
