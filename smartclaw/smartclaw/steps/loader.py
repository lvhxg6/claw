"""Step registry discovery and loading."""

from __future__ import annotations

from pathlib import Path

import structlog
import yaml

from smartclaw.agent.orchestration_models import StepDefinition

logger = structlog.get_logger(component="steps.loader")


class StepRegistryLoader:
    """Load step definitions from configured directories."""

    def __init__(
        self,
        workspace_dir: str | None = None,
        global_dir: str = "~/.smartclaw/steps",
        builtin_dir: str | None = None,
    ) -> None:
        self._workspace_dir = str(Path(workspace_dir).expanduser()) if workspace_dir else None
        self._global_dir = str(Path(global_dir).expanduser())
        self._builtin_dir = str(Path(builtin_dir).expanduser()) if builtin_dir else None

    def list_steps(self) -> list[StepDefinition]:
        """Return discovered step definitions, priority workspace > global > builtin."""
        steps: list[StepDefinition] = []
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
            for file_path in sorted(base.rglob("*.yaml")):
                try:
                    definition = self._load_step(file_path)
                except Exception:
                    logger.warning("step_definition_invalid", path=str(file_path), source=source)
                    continue
                step_id = str(definition.get("id", "")).strip()
                if not step_id or step_id in seen:
                    continue
                seen.add(step_id)
                steps.append(definition)
        return steps

    def _load_step(self, file_path: Path) -> StepDefinition:
        raw = yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}
        return {
            "id": str(raw.get("id", "")).strip(),
            "domain": str(raw.get("domain", "")).strip(),
            "description": str(raw.get("description", "")).strip(),
            "required_inputs": [str(item).strip() for item in raw.get("required_inputs", []) if str(item).strip()],
            "consumes_artifact_types": [
                str(item).strip() for item in raw.get("consumes_artifact_types", []) if str(item).strip()
            ],
            "outputs": [str(item).strip() for item in raw.get("outputs", []) if str(item).strip()],
            "preferred_skill": str(raw.get("preferred_skill", "")).strip(),
            "can_parallel": bool(raw.get("can_parallel", False)),
            "risk_level": str(raw.get("risk_level", "low")).strip() or "low",
            "completion_signal": str(raw.get("completion_signal", "")).strip(),
            "side_effect_level": str(raw.get("side_effect_level", "read_only")).strip() or "read_only",
            "kind": str(raw.get("kind", "generic")).strip() or "generic",
            "plan_role": str(raw.get("plan_role", "")).strip(),
            "activation_mode": str(raw.get("activation_mode", "")).strip(),
            "display_policy": str(raw.get("display_policy", "")).strip(),
            "intent_tags": [str(item).strip() for item in raw.get("intent_tags", []) if str(item).strip()],
            "default_depends_on": [str(item).strip() for item in raw.get("default_depends_on", []) if str(item).strip()],
        }
