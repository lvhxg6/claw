"""Step registry and request-time filtering."""

from __future__ import annotations

from typing import Any

from smartclaw.agent.orchestration_models import StepDefinition
from smartclaw.capabilities.models import CapabilityPackDefinition
from smartclaw.steps.loader import StepRegistryLoader


class StepRegistry:
    """Manage loaded step definitions and pack-scoped filtering."""

    def __init__(self, loader: StepRegistryLoader) -> None:
        self._loader = loader
        self._steps: dict[str, StepDefinition] = {}

    def load_all(self) -> None:
        self._steps = {str(step["id"]): step for step in self._loader.list_steps() if step.get("id")}

    def list_ids(self) -> list[str]:
        return sorted(self._steps.keys())

    def get(self, step_id: str) -> StepDefinition | None:
        return self._steps.get(step_id)

    def list_steps(self) -> list[StepDefinition]:
        return [self._steps[step_id] for step_id in self.list_ids()]

    def get_candidate_steps(
        self,
        pack: CapabilityPackDefinition | None = None,
        *,
        available_artifact_types: set[str] | None = None,
        terminal_step_ids: set[str] | None = None,
    ) -> list[StepDefinition]:
        steps = self.list_steps()
        if pack is None or not pack.allowed_steps:
            filtered = steps
        else:
            allowed = set(pack.allowed_steps)
            filtered = [step for step in steps if str(step.get("id")) in allowed]
        filtered = self._filter_by_runtime_context(
            filtered,
            available_artifact_types=available_artifact_types,
            terminal_step_ids=terminal_step_ids,
        )
        return self._sort_by_preference(filtered, pack)

    def artifact_type_for_step(self, step_id: str) -> str:
        step = self.get(step_id) or {}
        outputs = [str(item) for item in step.get("outputs", []) if str(item)]
        return outputs[0] if outputs else f"{step_id}_result"

    def artifact_ids_for_step(
        self,
        step_id: str,
        artifacts: list[dict[str, Any]] | None,
    ) -> list[str]:
        return [
            str(artifact.get("artifact_id"))
            for artifact in self.match_ready_artifacts(step_id, artifacts)
            if artifact.get("artifact_id")
        ]

    def match_ready_artifacts(
        self,
        step_id: str,
        artifacts: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        step = self.get(step_id) or {}
        consumes = {
            str(item)
            for item in step.get("consumes_artifact_types", [])
            if str(item)
        }
        if not consumes or not artifacts:
            return []
        return [
            artifact
            for artifact in artifacts
            if isinstance(artifact, dict)
            and artifact.get("status") == "ready"
            and str(artifact.get("artifact_type")) in consumes
        ]

    def approval_required_for_step(self, step_id: str) -> bool:
        step = self.get(step_id) or {}
        side_effect_level = str(step.get("side_effect_level", "read_only") or "read_only")
        risk_level = str(step.get("risk_level", "low") or "low")
        return side_effect_level != "read_only" or risk_level in {"high", "critical"}

    def _sort_by_preference(
        self,
        steps: list[StepDefinition],
        pack: CapabilityPackDefinition | None,
    ) -> list[StepDefinition]:
        if pack is None or not pack.preferred_steps:
            return steps
        preferred_index = {step_id: index for index, step_id in enumerate(pack.preferred_steps)}
        return sorted(
            steps,
            key=lambda step: (
                preferred_index.get(str(step.get("id")), 10_000),
                str(step.get("id")),
            ),
        )

    def _filter_by_runtime_context(
        self,
        steps: list[StepDefinition],
        *,
        available_artifact_types: set[str] | None,
        terminal_step_ids: set[str] | None,
    ) -> list[StepDefinition]:
        filtered: list[StepDefinition] = []
        terminal_ids = terminal_step_ids or set()
        for step in steps:
            step_id = str(step.get("id", ""))
            if not step_id or step_id in terminal_ids:
                continue
            consumes = {str(item) for item in step.get("consumes_artifact_types", []) if str(item)}
            if consumes and available_artifact_types is not None and not (consumes & available_artifact_types):
                continue
            filtered.append(step)
        return filtered
