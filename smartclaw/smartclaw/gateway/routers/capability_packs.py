"""Capability pack router — GET /api/capability-packs."""

from __future__ import annotations

from fastapi import APIRouter, Request

from smartclaw.gateway.models import CapabilityPackInfoData

router = APIRouter(prefix="/api/capability-packs", tags=["capability_packs"])


@router.get("", response_model=list[CapabilityPackInfoData])
async def list_capability_packs(request: Request) -> list[CapabilityPackInfoData]:
    """Return all registered capability packs."""
    runtime = request.app.state.runtime
    registry = getattr(runtime, "capability_registry", None)
    if registry is None:
        return []

    items: list[CapabilityPackInfoData] = []
    for name in registry.list_names():
        pack = registry.get(name)
        if pack is None:
            continue
        items.append(
            CapabilityPackInfoData(
                name=pack.name,
                description=pack.description,
                scenario_types=list(pack.scenario_types),
                preferred_mode=pack.preferred_mode,
                task_profile=pack.task_profile,
                approval_required=pack.approval_required,
                schema_enforced=pack.schema_enforced,
            )
        )
    return items
