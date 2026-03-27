"""Base extractor protocol."""

from __future__ import annotations

from typing import Protocol

from smartclaw.uploads.models import ExtractionResult


class BaseExtractor(Protocol):
    """Protocol implemented by attachment extractors."""

    def extract(self, content: bytes, *, filename: str, media_type: str) -> ExtractionResult:
        """Extract text and summary from bytes."""
