"""SKILL.md parser — extract metadata and body from Markdown skill files.

Parses YAML frontmatter (between ``---`` delimiters) to extract ``name``
and ``description``. Falls back to directory name and first paragraph when
frontmatter is absent or invalid.

Adapted from PicoClaw's ``pkg/skills/loader.go`` splitFrontmatter pattern.
"""

from __future__ import annotations

import yaml


def split_frontmatter(content: str) -> tuple[str, str]:
    """Split YAML frontmatter from Markdown body.

    Returns ``(frontmatter_yaml, body_markdown)``.
    If no frontmatter (content doesn't start with ``---``), returns
    ``("", content)``.
    """
    # Normalize line endings
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")

    if not lines or lines[0].strip() != "---":
        return "", content

    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break

    if end == -1:
        return "", content

    frontmatter = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1 :])
    # Strip leading newlines from body
    body = body.lstrip("\n")
    return frontmatter, body


def _first_paragraph(text: str) -> str:
    """Extract the first non-empty paragraph from Markdown text."""
    lines = text.strip().split("\n")
    paragraph_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        # Skip headings
        if stripped.startswith("#"):
            if paragraph_lines:
                break
            continue
        if not stripped:
            if paragraph_lines:
                break
            continue
        paragraph_lines.append(stripped)
    return " ".join(paragraph_lines)


def parse_skill_md(content: str, dir_name: str) -> tuple[str, str, str]:
    """Parse a SKILL.md file.

    Returns ``(name, description, body)``:
    - *name*: from frontmatter ``name`` field, or *dir_name* fallback
    - *description*: from frontmatter ``description`` field, or first
      paragraph fallback
    - *body*: Markdown content with frontmatter stripped
    """
    frontmatter_str, body = split_frontmatter(content)

    name = dir_name
    description = ""

    if frontmatter_str:
        try:
            meta = yaml.safe_load(frontmatter_str)
            if isinstance(meta, dict):
                if meta.get("name") is not None:
                    name = str(meta["name"])
                if meta.get("description") is not None:
                    description = str(meta["description"])
        except yaml.YAMLError:
            # Invalid YAML frontmatter — fall back to defaults
            pass

    if not description:
        description = _first_paragraph(body)

    return name, description, body
