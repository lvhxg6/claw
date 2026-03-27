"""ModeRouter — lightweight execution-mode routing for SmartClaw."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Mode = Literal["auto", "classic", "orchestrator"]

_FORCE_ORCHESTRATOR_SCENARIOS = {"inspection", "hardening", "batch_job"}
_ORCHESTRATOR_TASK_PROFILES = {"multi_stage", "parallelizable", "batch"}
_ORCHESTRATOR_KEYWORDS = (
    "先",
    "再",
    "最后",
    "根据结果",
    "并行",
    "批量",
    "多个",
    "巡检",
    "检查",
    "加固",
    "整改",
    "报告",
)


@dataclass(frozen=True)
class ModeDecision:
    """Resolved execution mode and its coarse routing rationale."""

    requested_mode: str | None
    resolved_mode: Literal["classic", "orchestrator"]
    reason: str
    confidence: float


class ModeRouter:
    """Resolve execution mode from request hints and task structure."""

    def __init__(self, *, default_mode: Mode = "auto") -> None:
        self._default_mode = default_mode

    def resolve(
        self,
        *,
        requested_mode: str | None = None,
        message: str = "",
        scenario_type: str | None = None,
        task_profile: str | None = None,
    ) -> ModeDecision:
        """Resolve the execution mode for a request."""
        if requested_mode in {"classic", "orchestrator"}:
            return ModeDecision(
                requested_mode=requested_mode,
                resolved_mode=requested_mode,
                reason="explicit_request",
                confidence=1.0,
            )

        if requested_mode not in {None, "", "auto"}:
            return ModeDecision(
                requested_mode=requested_mode,
                resolved_mode="classic",
                reason="invalid_request_fallback",
                confidence=0.5,
            )

        if self._default_mode in {"classic", "orchestrator"} and requested_mode in {None, ""}:
            return ModeDecision(
                requested_mode=requested_mode,
                resolved_mode=self._default_mode,
                reason="runtime_default",
                confidence=0.9,
            )

        score = 0.0
        reasons: list[str] = []

        scenario = (scenario_type or "").strip().lower()
        if scenario in _FORCE_ORCHESTRATOR_SCENARIOS:
            score += 1.0
            reasons.append("scenario_hint")

        profile = (task_profile or "").strip().lower()
        if profile in _ORCHESTRATOR_TASK_PROFILES:
            score += 0.8
            reasons.append("task_profile")

        normalized_message = message.strip()
        keyword_hits = sum(1 for keyword in _ORCHESTRATOR_KEYWORDS if keyword in normalized_message)
        if keyword_hits:
            score += min(0.9, 0.2 * keyword_hits)
            reasons.append("task_structure")

        if score >= 0.7:
            return ModeDecision(
                requested_mode=requested_mode,
                resolved_mode="orchestrator",
                reason=",".join(reasons) or "heuristic_orchestrator",
                confidence=min(0.98, max(0.7, score)),
            )

        return ModeDecision(
            requested_mode=requested_mode,
            resolved_mode="classic",
            reason="heuristic_classic",
            confidence=max(0.55, 1.0 - score),
        )
