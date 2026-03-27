"""Capability pack discovery and loading."""

from __future__ import annotations

from pathlib import Path

import structlog
import yaml

from smartclaw.capabilities.models import CapabilityPackDefinition, CapabilityPackInfo

logger = structlog.get_logger(component="capabilities.loader")


class CapabilityPackLoader:
    """Load capability pack manifests from configured directories."""

    def __init__(
        self,
        workspace_dir: str | None = None,
        global_dir: str = "~/.smartclaw/capability_packs",
        builtin_dir: str | None = None,
    ) -> None:
        self._workspace_dir = str(Path(workspace_dir).expanduser()) if workspace_dir else None
        self._global_dir = str(Path(global_dir).expanduser())
        self._builtin_dir = str(Path(builtin_dir).expanduser()) if builtin_dir else None

    def list_packs(self) -> list[CapabilityPackInfo]:
        """Return discovered capability packs, priority workspace > global > builtin."""
        packs: list[CapabilityPackInfo] = []
        seen: set[str] = set()
        for base_dir, source in (
            (self._workspace_dir, "workspace"),
            (self._global_dir, "global"),
            (self._builtin_dir, "builtin"),
        ):
            if base_dir is None:
                continue
            base = Path(base_dir)
            if not base.is_dir():
                continue
            for child in sorted(base.iterdir()):
                if not child.is_dir():
                    continue
                manifest_path = child / "manifest.yaml"
                if not manifest_path.is_file():
                    continue
                try:
                    pack = self._load_manifest(manifest_path)
                except Exception:
                    logger.warning("capability_manifest_invalid", path=str(manifest_path))
                    continue
                errors = pack.validate()
                if errors:
                    logger.warning(
                        "capability_validation_failed",
                        name=pack.name,
                        path=str(manifest_path),
                        errors=errors,
                    )
                    continue
                if pack.name in seen:
                    continue
                seen.add(pack.name)
                packs.append(
                    CapabilityPackInfo(
                        name=pack.name,
                        path=str(manifest_path),
                        source=source,
                        description=pack.description,
                        scenario_types=list(pack.scenario_types),
                    )
                )
        return packs

    def load_pack(self, name: str) -> CapabilityPackDefinition:
        """Load a capability pack by name."""
        for info in self.list_packs():
            if info.name == name:
                return self._load_manifest(Path(info.path))
        raise ImportError(f"Capability pack '{name}' not found")

    def build_summary(self) -> str:
        """Build a stable summary of discovered capability packs."""
        lines: list[str] = []
        for info in self.list_packs():
            scenario_text = f" scenarios={','.join(info.scenario_types)}" if info.scenario_types else ""
            lines.append(f"- `{info.name}`: {info.description}{scenario_text}")
        return "\n".join(lines)

    def _load_manifest(self, manifest_path: Path) -> CapabilityPackDefinition:
        raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        prompt = str(raw.get("prompt", "") or "")
        prompt_file = raw.get("prompt_file")
        if prompt_file:
            prompt = (manifest_path.parent / str(prompt_file)).read_text(encoding="utf-8").strip()

        result_schema = str(raw.get("result_schema", "") or "")
        schema_file = raw.get("result_schema_file")
        if schema_file:
            result_schema = (manifest_path.parent / str(schema_file)).read_text(encoding="utf-8").strip()

        definition = CapabilityPackDefinition(
            name=str(raw.get("name", "")).strip(),
            description=str(raw.get("description", "")).strip(),
            version=str(raw.get("version")).strip() if raw.get("version") is not None else None,
            scenario_types=[str(item).strip() for item in raw.get("scenario_types", []) if str(item).strip()],
            preferred_mode=str(raw.get("preferred_mode")).strip() if raw.get("preferred_mode") else None,
            task_profile=str(raw.get("task_profile")).strip() if raw.get("task_profile") else None,
            prompt=prompt,
            result_schema=result_schema,
            result_format=str(raw.get("result_format", "text")).strip() or "text",
            schema_enforced=bool(raw.get("schema_enforced", False)),
            max_schema_retries=int(raw.get("max_schema_retries", 0) or 0),
            approval_required=bool(raw.get("approval_required", False)),
            approval_message=str(raw.get("approval_message", "")).strip(),
            allowed_tools=[str(item).strip() for item in raw.get("allowed_tools", []) if str(item).strip()],
            denied_tools=[str(item).strip() for item in raw.get("denied_tools", []) if str(item).strip()],
            tool_groups={
                str(group): [str(item).strip() for item in items if str(item).strip()]
                for group, items in (raw.get("tool_groups", {}) or {}).items()
                if isinstance(items, list)
            },
            concurrency_limits={
                str(group): int(limit)
                for group, limit in (raw.get("concurrency_limits", {}) or {}).items()
            },
            max_task_retries=int(raw.get("max_task_retries", 0) or 0),
            retry_on_error=bool(raw.get("retry_on_error", True)),
            metadata=dict(raw.get("metadata", {}) or {}),
            manifest_path=str(manifest_path),
        )
        return definition
