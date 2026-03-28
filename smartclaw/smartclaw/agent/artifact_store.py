"""Lightweight artifact storage for orchestrator runtime."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from smartclaw.agent.orchestration_models import ArtifactEnvelope


class ArtifactStore:
    """Persist normalized artifacts to session-scoped JSON payload files."""

    def __init__(self, root_dir: str | Path | None = None) -> None:
        base_dir = Path(root_dir) if root_dir is not None else Path(tempfile.gettempdir()) / "smartclaw-artifacts"
        self._root_dir = base_dir

    def create_artifact(
        self,
        *,
        session_key: str | None,
        step_id: str,
        artifact_type: str,
        result: str,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactEnvelope:
        artifact_id = f"art_{uuid4().hex[:12]}"
        payload_dir = self._root_dir / "sessions" / (session_key or "ephemeral") / "artifacts"
        payload_dir.mkdir(parents=True, exist_ok=True)
        payload_path = payload_dir / f"{artifact_id}.json"
        payload = {
            "summary": _summarize_result(result),
            "data": {
                "result": result,
            },
            "metadata": metadata or {},
        }
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "artifact_id": artifact_id,
            "artifact_type": artifact_type,
            "schema_version": "v1",
            "producer_step": step_id,
            "status": "ready",
            "summary": payload["summary"],
            "validation": {
                "is_valid": True,
                "errors": [],
            },
            "payload_path": str(payload_path),
        }


def _summarize_result(result: str) -> str:
    text = " ".join(result.split())
    return text[:160] if len(text) > 160 else text
