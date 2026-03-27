"""SmartClaw Skills module — skill discovery, loading, and registry.

Provides:
- ``SkillsLoader`` — YAML skill definition discovery and dynamic loading.
- ``SkillsRegistry`` — skill registration, management, and ToolRegistry integration.
- ``SkillsWatcher`` — file watcher for SKILL.md hot-reload.
- ``SkillDefinition`` — YAML skill definition dataclass.
- ``SkillInfo`` — skill discovery information dataclass.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from smartclaw.skills.loader import SkillsLoader as SkillsLoader
    from smartclaw.skills.models import SkillDefinition as SkillDefinition
    from smartclaw.skills.models import SkillInfo as SkillInfo
    from smartclaw.skills.watcher import SkillsWatcher as SkillsWatcher


def __getattr__(name: str) -> object:
    if name == "SkillsLoader":
        from smartclaw.skills.loader import SkillsLoader

        return SkillsLoader
    if name == "SkillsRegistry":
        from smartclaw.skills.registry import SkillsRegistry

        return SkillsRegistry
    if name == "SkillsWatcher":
        from smartclaw.skills.watcher import SkillsWatcher

        return SkillsWatcher
    if name == "SkillDefinition":
        from smartclaw.skills.models import SkillDefinition

        return SkillDefinition
    if name == "SkillInfo":
        from smartclaw.skills.models import SkillInfo

        return SkillInfo
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["SkillsLoader", "SkillsRegistry", "SkillsWatcher", "SkillDefinition", "SkillInfo"]
