"""PromptComposer — structured assembly of the SmartClaw system prompt."""

from __future__ import annotations


class PromptComposer:
    """Compose the final system prompt from runtime prompt fragments."""

    def compose(
        self,
        *,
        base_prompt: str,
        skills_summary: str = "",
        capability_summary: str = "",
        capability_context: str = "",
        soul_content: str = "",
        user_content: str = "",
        tools_content: str = "",
        memory_context: str = "",
        mode: str = "auto",
    ) -> str:
        """Return the final prompt text in a stable order."""
        parts: list[str] = []

        if soul_content:
            parts.append(soul_content.strip())

        parts.append(base_prompt.strip())

        if tools_content:
            parts.append(f"## Tool Context\n{tools_content.strip()}")

        if memory_context:
            parts.append(f"## Long-term Memory\n{memory_context.strip()}")

        if user_content:
            parts.append(f"## User Context\n{user_content.strip()}")

        if skills_summary:
            parts.append(f"## Available Skills\n{skills_summary.strip()}")

        if capability_summary:
            parts.append(f"## Available Capability Packs\n{capability_summary.strip()}")

        if capability_context:
            parts.append(f"## Active Capability Pack\n{capability_context.strip()}")

        if mode:
            parts.append(f"## Runtime Mode\nCurrent default mode: `{mode}`.")

        return "\n\n".join(part for part in parts if part)
