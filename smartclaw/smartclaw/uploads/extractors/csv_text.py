"""CSV extractor."""

from __future__ import annotations

import csv
import io

from smartclaw.uploads.models import ExtractionResult


class CsvExtractor:
    """Convert CSV to readable text excerpt."""

    def extract(self, content: bytes, *, filename: str, media_type: str) -> ExtractionResult:
        raw = content.decode("utf-8", errors="replace")
        text = raw.strip()
        row_count = 0
        columns: list[str] = []
        try:
            reader = csv.reader(io.StringIO(raw))
            for index, row in enumerate(reader):
                if index == 0:
                    columns = [item.strip() for item in row if item.strip()]
                row_count += 1
        except Exception:
            pass

        summary_parts: list[str] = [f"{filename} 已上传"]
        if columns:
            summary_parts.append("列: " + ", ".join(columns[:6]))
        if row_count:
            summary_parts.append(f"行数约 {max(row_count - 1, 0)}")
        return ExtractionResult(
            text=text,
            summary="；".join(summary_parts),
            supported=True,
        )
