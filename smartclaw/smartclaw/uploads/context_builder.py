"""Attachment-to-message context builder."""

from __future__ import annotations

from smartclaw.config.settings import UploadSettings
from smartclaw.uploads.models import AttachmentRecord


def build_attachment_context(
    attachments: list[AttachmentRecord],
    settings: UploadSettings,
) -> str:
    """Build a bounded attachment context block."""
    if not attachments:
        return ""

    lines = ["[Attachments]"]
    remaining = max(int(settings.max_context_chars), 0)
    per_attachment_limit = max(int(settings.max_attachment_chars), 0)

    for attachment in attachments:
        block_lines = [
            f"- {attachment.filename}",
            f"  Type: {attachment.media_type}",
        ]
        if attachment.extract_summary:
            block_lines.append(f"  Summary: {attachment.extract_summary}")
        excerpt = (attachment.extract_text or "").strip()
        if excerpt and per_attachment_limit > 0:
            excerpt = excerpt[:per_attachment_limit]
            block_lines.append("  Excerpt:")
            block_lines.append(_indent(excerpt, "  "))
        block = "\n".join(block_lines)
        if remaining <= 0:
            break
        if len(block) > remaining:
            block = block[:remaining]
        lines.append(block)
        remaining -= len(block) + 1
        if remaining <= 0:
            break

    return "\n".join(lines).strip()


def _indent(value: str, prefix: str) -> str:
    return "\n".join(prefix + line for line in value.splitlines())
