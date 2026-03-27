"""Attachment text extractors."""

from smartclaw.uploads.extractors.base import BaseExtractor
from smartclaw.uploads.extractors.csv_text import CsvExtractor
from smartclaw.uploads.extractors.docx import DocxExtractor
from smartclaw.uploads.extractors.image_ocr import OcrImageExtractor
from smartclaw.uploads.extractors.image_stub import ImageStubExtractor
from smartclaw.uploads.extractors.json_yaml import JsonYamlExtractor
from smartclaw.uploads.extractors.pdf import PdfExtractor
from smartclaw.uploads.extractors.plain_text import PlainTextExtractor
from smartclaw.uploads.extractors.xlsx import XlsxExtractor

__all__ = [
    "BaseExtractor",
    "CsvExtractor",
    "DocxExtractor",
    "OcrImageExtractor",
    "ImageStubExtractor",
    "JsonYamlExtractor",
    "PdfExtractor",
    "PlainTextExtractor",
    "XlsxExtractor",
]
