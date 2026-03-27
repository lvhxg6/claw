"""Capability pack loader and registry tests."""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import BaseTool

from smartclaw.capabilities.governance import build_runtime_policy, validate_structured_output
from smartclaw.capabilities.loader import CapabilityPackLoader
from smartclaw.capabilities.registry import CapabilityPackRegistry


class DummyTool(BaseTool):
    """Minimal tool for registry filtering tests."""

    name: str
    description: str = "dummy"

    def _run(self, *args, **kwargs):
        return "ok"


def _write_pack(base_dir: Path) -> None:
    pack_dir = base_dir / "security-governance"
    pack_dir.mkdir(parents=True)
    (pack_dir / "prompt.md").write_text("Follow the governance workflow.", encoding="utf-8")
    (pack_dir / "schema.json").write_text('{"type":"object","required":["status"]}', encoding="utf-8")
    (pack_dir / "manifest.yaml").write_text(
        "\n".join(
            [
                "name: security-governance",
                "description: Security governance workflows",
                "scenario_types:",
                "  - inspection",
                "  - hardening",
                "preferred_mode: orchestrator",
                "task_profile: multi_stage",
                "result_format: json",
                "schema_enforced: true",
                "max_schema_retries: 2",
                "approval_required: true",
                "approval_message: Confirm governance execution",
                "allowed_tools:",
                "  - read_file",
                "  - spawn_sub_agent",
                "denied_tools:",
                "  - exec_command",
                "concurrency_limits:",
                "  inspection: 2",
                "max_task_retries: 1",
                "retry_on_error: true",
                "prompt_file: prompt.md",
                "result_schema_file: schema.json",
                "tool_groups:",
                "  inspection:",
                "    - read_file",
                "    - spawn_sub_agent",
            ]
        ),
        encoding="utf-8",
    )


def test_capability_loader_loads_manifest_and_external_files(tmp_path: Path) -> None:
    _write_pack(tmp_path)
    loader = CapabilityPackLoader(workspace_dir=str(tmp_path), global_dir=str(tmp_path / "missing"))

    info = loader.list_packs()
    assert len(info) == 1
    pack = loader.load_pack("security-governance")

    assert pack.preferred_mode == "orchestrator"
    assert pack.task_profile == "multi_stage"
    assert pack.approval_required is True
    assert "Follow the governance workflow." in pack.prompt
    assert '"required":["status"]' in pack.result_schema


def test_capability_registry_resolves_and_filters_tools(tmp_path: Path) -> None:
    _write_pack(tmp_path)
    loader = CapabilityPackLoader(workspace_dir=str(tmp_path), global_dir=str(tmp_path / "missing"))
    registry = CapabilityPackRegistry(loader=loader)
    registry.load_all()

    resolution = registry.resolve(scenario_type="inspection")
    assert resolution.resolved_name == "security-governance"

    tools = [
        DummyTool(name="read_file"),
        DummyTool(name="spawn_sub_agent"),
        DummyTool(name="exec_command"),
        DummyTool(name="web_search"),
    ]
    filtered = registry.filter_tools(tools, pack_name="security-governance")

    assert [tool.name for tool in filtered] == ["read_file", "spawn_sub_agent"]
    context = registry.render_context("security-governance")
    assert "Preferred mode: orchestrator" in context
    assert "Allowed tools: read_file, spawn_sub_agent" in context
    assert "Approval: required before execution" in context

    policy = build_runtime_policy(registry.get("security-governance"))
    assert policy is not None
    assert policy["schema_enforced"] is True
    assert policy["max_task_retries"] == 1
    structured, validation = validate_structured_output('{"status":"ok"}', policy)
    assert validation["valid"] is True
    assert structured == {"status": "ok"}
