"""Capability pack registry and request-time resolution."""

from __future__ import annotations

from langchain_core.tools import BaseTool

from smartclaw.capabilities.loader import CapabilityPackLoader
from smartclaw.capabilities.models import CapabilityPackDefinition, CapabilityResolution


class CapabilityPackRegistry:
    """Manage loaded capability packs and request-time lookups."""

    def __init__(self, loader: CapabilityPackLoader) -> None:
        self._loader = loader
        self._packs: dict[str, CapabilityPackDefinition] = {}

    def load_all(self) -> None:
        """Load all discovered capability packs into the registry."""
        loaded: dict[str, CapabilityPackDefinition] = {}
        for info in self._loader.list_packs():
            loaded[info.name] = self._loader.load_pack(info.name)
        self._packs = loaded

    def build_summary(self) -> str:
        """Return a stable summary for prompt composition."""
        if not self._packs:
            return ""
        lines = []
        for pack in sorted(self._packs.values(), key=lambda item: item.name):
            scenario_text = f" scenarios={','.join(pack.scenario_types)}" if pack.scenario_types else ""
            lines.append(f"- `{pack.name}`: {pack.description}{scenario_text}")
        return "\n".join(lines)

    def list_names(self) -> list[str]:
        """Return registered pack names."""
        return sorted(self._packs.keys())

    def get(self, name: str) -> CapabilityPackDefinition | None:
        """Return a capability pack by name."""
        return self._packs.get(name)

    def resolve(
        self,
        *,
        requested_name: str | None = None,
        scenario_type: str | None = None,
    ) -> CapabilityResolution:
        """Resolve a request to a capability pack."""
        if requested_name:
            pack = self._packs.get(requested_name)
            if pack is not None:
                return CapabilityResolution(
                    requested_name=requested_name,
                    resolved_name=pack.name,
                    reason="explicit_request",
                    pack=pack,
                )
            return CapabilityResolution(
                requested_name=requested_name,
                resolved_name=None,
                reason="unknown_capability_pack",
                pack=None,
            )

        normalized_scenario = (scenario_type or "").strip().lower()
        if normalized_scenario:
            for pack in self._packs.values():
                if normalized_scenario in {item.lower() for item in pack.scenario_types}:
                    return CapabilityResolution(
                        requested_name=requested_name,
                        resolved_name=pack.name,
                        reason="scenario_match",
                        pack=pack,
                    )

        return CapabilityResolution(
            requested_name=requested_name,
            resolved_name=None,
            reason="no_match",
            pack=None,
        )

    def filter_tools(
        self,
        tools: list[BaseTool],
        *,
        pack_name: str | None = None,
    ) -> list[BaseTool]:
        """Apply capability-pack tool scoping to a tool list."""
        if pack_name is None:
            return list(tools)
        pack = self._packs.get(pack_name)
        if pack is None:
            return list(tools)

        allowed = set(pack.allowed_tools)
        denied = set(pack.denied_tools)
        filtered: list[BaseTool] = []
        for tool in tools:
            if allowed and tool.name not in allowed:
                continue
            if tool.name in denied:
                continue
            filtered.append(tool)
        return filtered

    def render_context(self, pack_name: str | None = None) -> str:
        """Render the active capability pack prompt fragment and policy summary."""
        if pack_name is None:
            return ""
        pack = self._packs.get(pack_name)
        if pack is None:
            return ""

        parts = [f"Name: {pack.name}", f"Description: {pack.description}"]
        if pack.preferred_mode:
            parts.append(f"Preferred mode: {pack.preferred_mode}")
        if pack.task_profile:
            parts.append(f"Task profile: {pack.task_profile}")
        if pack.allowed_tools:
            parts.append(f"Allowed tools: {', '.join(pack.allowed_tools)}")
        if pack.denied_tools:
            parts.append(f"Denied tools: {', '.join(pack.denied_tools)}")
        if pack.allowed_steps:
            parts.append(f"Allowed steps: {', '.join(pack.allowed_steps)}")
        if pack.preferred_steps:
            parts.append(f"Preferred steps: {', '.join(pack.preferred_steps)}")
        if pack.approval_required:
            parts.append("Approval: required before execution")
        if pack.max_task_retries:
            parts.append(f"Task retries: {pack.max_task_retries}")
        if pack.max_replanning_rounds:
            parts.append(f"Replanning limit: {pack.max_replanning_rounds}")
        if pack.concurrency_limits:
            limits = ", ".join(f"{key}={value}" for key, value in sorted(pack.concurrency_limits.items()))
            parts.append(f"Concurrency limits: {limits}")
        if pack.result_schema:
            parts.append("Result schema:")
            parts.append(pack.result_schema)
        if pack.prompt:
            parts.append("Prompt guidance:")
            parts.append(pack.prompt)
        return "\n".join(parts)
