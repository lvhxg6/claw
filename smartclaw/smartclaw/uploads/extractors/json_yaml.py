"""JSON and YAML extractors."""

from __future__ import annotations

import json

import yaml

from smartclaw.uploads.extractors.plain_text import _build_summary
from smartclaw.uploads.models import ExtractionResult


class JsonYamlExtractor:
    """Parse JSON and YAML into normalized text."""

    def extract(self, content: bytes, *, filename: str, media_type: str) -> ExtractionResult:
        raw = content.decode("utf-8", errors="replace")
        try:
            if "json" in media_type:
                parsed = json.loads(raw)
                text = json.dumps(parsed, ensure_ascii=False, indent=2)
            else:
                parsed = yaml.safe_load(raw)
                text = yaml.safe_dump(parsed, allow_unicode=True, sort_keys=False)
        except Exception:
            text = raw.strip()
        text = text.strip()
        return ExtractionResult(text=text, summary=_build_summary(text, filename=filename), supported=True)
