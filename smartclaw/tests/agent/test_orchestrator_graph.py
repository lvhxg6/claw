"""Unit tests for orchestrator planning and graph execution."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool

from smartclaw.agent.dispatch_policy import DispatchPolicy
from smartclaw.agent.graph import invoke
from smartclaw.agent.orchestrator_graph import _should_attempt_replan, build_orchestrator_graph
from smartclaw.agent.plan_manager import PlanManager
from smartclaw.capabilities.models import CapabilityPackDefinition
from smartclaw.capabilities.registry import CapabilityPackRegistry
from smartclaw.providers.config import ModelConfig
from smartclaw.steps.loader import StepRegistryLoader
from smartclaw.steps.registry import StepRegistry


def _default_model_config() -> ModelConfig:
    return ModelConfig(
        primary="openai/gpt-4o",
        fallbacks=[],
        temperature=0.0,
        max_tokens=1024,
    )


def _approval_registry(tmp_path) -> StepRegistry:
    steps_dir = tmp_path / "steps"
    steps_dir.mkdir(parents=True)
    (steps_dir / "inspect.yaml").write_text(
        "\n".join(
            [
                "id: inspect",
                "domain: security",
                "description: 对目标执行检查任务",
                "outputs:",
                "  - inspection_result",
                "can_parallel: true",
                "risk_level: low",
                "completion_signal: inspection_result_ready",
                "side_effect_level: read_only",
                "kind: inspection",
            ]
        ),
        encoding="utf-8",
    )
    (steps_dir / "remediate.yaml").write_text(
        "\n".join(
            [
                "id: remediate",
                "domain: security",
                "description: 根据检查结果执行整改",
                "consumes_artifact_types:",
                "  - inspection_result",
                "outputs:",
                "  - remediation_result",
                "can_parallel: false",
                "risk_level: medium",
                "completion_signal: remediation_result_ready",
                "side_effect_level: write",
                "kind: remediation",
            ]
        ),
        encoding="utf-8",
    )
    (steps_dir / "report.yaml").write_text(
        "\n".join(
            [
                "id: report",
                "domain: security",
                "description: 汇总检查与整改结果并生成报告",
                "consumes_artifact_types:",
                "  - inspection_result",
                "  - remediation_result",
                "outputs:",
                "  - report_result",
                "can_parallel: false",
                "risk_level: low",
                "completion_signal: report_result_ready",
                "side_effect_level: read_only",
                "kind: report",
            ]
        ),
        encoding="utf-8",
    )
    registry = StepRegistry(StepRegistryLoader(workspace_dir=str(steps_dir), global_dir=str(tmp_path / "none")))
    registry.load_all()
    return registry


def _approval_capability_registry() -> CapabilityPackRegistry:
    registry = CapabilityPackRegistry.__new__(CapabilityPackRegistry)
    registry._loader = None  # type: ignore[attr-defined]
    registry._packs = {
        "security-governance": CapabilityPackDefinition(
            name="security-governance",
            description="security",
            allowed_steps=["inspect", "remediate", "report"],
            preferred_steps=["inspect", "remediate", "report"],
        )
    }
    return registry


class DummySpawnTool(BaseTool):
    """Minimal async spawn tool for orchestrator tests."""

    name: str = "spawn_sub_agent"
    description: str = "spawn"
    seen_tasks: list[str] = []

    def _run(self, *args, **kwargs):
        return "not-used"

    async def _arun(self, task: str, **kwargs):
        self.seen_tasks.append(task)
        return f"completed:{task.splitlines()[1]}"


class FlakySpawnTool(BaseTool):
    """Spawn tool that fails once per task before succeeding."""

    name: str = "spawn_sub_agent"
    description: str = "spawn"
    attempts: dict[str, int] = {}

    def _run(self, *args, **kwargs):
        return "not-used"

    async def _arun(self, task: str, **kwargs):
        key = task.splitlines()[1]
        current = self.attempts.get(key, 0) + 1
        self.attempts[key] = current
        if current == 1:
            return "Error: temporary failure"
        return f"completed:{key}"


class AlwaysFailSpawnTool(BaseTool):
    """Spawn tool that always fails with the same error."""

    name: str = "spawn_sub_agent"
    description: str = "spawn"

    def _run(self, *args, **kwargs):
        return "not-used"

    async def _arun(self, task: str, **kwargs):
        del task, kwargs
        return "Error: target unreachable"


class TestPlanManager:
    """PlanManager should infer coarse-grained orchestrator todos."""

    def test_infers_inspection_remediation_and_report_todos(self) -> None:
        manager = PlanManager()
        from langchain_core.messages import HumanMessage

        plan = manager.create_initial_plan(
            [HumanMessage(content="先做基线检查，再根据结果加固，最后输出报告")]
        )

        assert plan["plan_version"] == "v1"
        todo_ids = [todo["todo_id"] for todo in plan["todos"]]
        assert "inspect" in todo_ids
        assert "remediate" in todo_ids
        assert "report" in todo_ids

    def test_apply_results_unlocks_dependent_todos(self) -> None:
        manager = PlanManager()
        from langchain_core.messages import HumanMessage

        plan = manager.create_initial_plan(
            [HumanMessage(content="先做基线检查，再根据结果加固，最后输出报告")]
        )
        updated = manager.apply_results(
            plan,
            [{"todo_id": "inspect", "status": "completed", "result": "ok"}],
        )

        assert updated is not None
        statuses = {todo["todo_id"]: todo["status"] for todo in updated["todos"]}
        assert statuses["inspect"] == "completed"
        assert statuses["remediate"] == "ready"
        assert statuses["report"] == "pending"

    def test_registry_replan_skips_unregistered_fallback_remediation(self, tmp_path) -> None:
        steps_dir = tmp_path / "steps_registry_only"
        steps_dir.mkdir(parents=True)
        (steps_dir / "inspect.yaml").write_text(
            "\n".join(
                [
                    "id: inspect",
                    "domain: security",
                    "description: 执行代码安全检查",
                    "outputs:",
                    "  - inspection_result",
                    "can_parallel: true",
                    "risk_level: low",
                    "completion_signal: inspection_result_ready",
                    "side_effect_level: read_only",
                    "kind: inspection",
                ]
            ),
            encoding="utf-8",
        )
        (steps_dir / "report.yaml").write_text(
            "\n".join(
                [
                    "id: report",
                    "domain: security",
                    "description: 汇总检查结果并生成报告",
                    "consumes_artifact_types:",
                    "  - inspection_result",
                    "outputs:",
                    "  - report_result",
                    "can_parallel: false",
                    "risk_level: low",
                    "completion_signal: report_result_ready",
                    "side_effect_level: read_only",
                    "kind: report",
                ]
            ),
            encoding="utf-8",
        )
        step_registry = StepRegistry(
            StepRegistryLoader(workspace_dir=str(steps_dir), global_dir=str(tmp_path / "none"))
        )
        step_registry.load_all()
        manager = PlanManager(step_registry=step_registry)
        from langchain_core.messages import HumanMessage

        current_plan = {
            "plan_version": "v1",
            "objective": "先检查再报告",
            "strategy": "test",
            "todos": [
                {
                    "todo_id": "inspect",
                    "step_id": "inspect",
                    "title": "检查",
                    "status": "completed",
                    "depends_on": [],
                },
                {
                    "todo_id": "report",
                    "step_id": "report",
                    "title": "报告",
                    "status": "completed",
                    "depends_on": ["inspect"],
                },
            ],
        }

        replanned = manager.replan(
            [HumanMessage(content="根据结果继续整改修复")],
            current_plan=current_plan,
        )

        assert replanned["todos"] == []

    def test_registry_plan_keeps_only_inspection_for_inspection_only_request(self, tmp_path) -> None:
        steps_dir = tmp_path / "steps_minimal"
        steps_dir.mkdir(parents=True)
        (steps_dir / "inspect.yaml").write_text(
            "\n".join(
                [
                    "id: inspect",
                    "domain: security",
                    "description: 执行代码安全检查",
                    "outputs:",
                    "  - inspection_result",
                    "can_parallel: true",
                    "risk_level: low",
                    "completion_signal: inspection_result_ready",
                    "side_effect_level: read_only",
                    "kind: inspection",
                    "plan_role: core",
                    "activation_mode: immediate",
                    "intent_tags:",
                    "  - inspection",
                ]
            ),
            encoding="utf-8",
        )
        (steps_dir / "remediation_plan.yaml").write_text(
            "\n".join(
                [
                    "id: remediation_plan",
                    "domain: security",
                    "description: 根据检查结果生成整改方案",
                    "consumes_artifact_types:",
                    "  - inspection_result",
                    "outputs:",
                    "  - remediation_plan_result",
                    "can_parallel: false",
                    "risk_level: medium",
                    "completion_signal: remediation_plan_result_ready",
                    "side_effect_level: read_only",
                    "kind: remediation",
                    "plan_role: conditional",
                    "activation_mode: after_artifact",
                    "intent_tags:",
                    "  - remediation",
                    "  - remediation_plan",
                ]
            ),
            encoding="utf-8",
        )
        (steps_dir / "remediation_apply.yaml").write_text(
            "\n".join(
                [
                    "id: remediation_apply",
                    "domain: security",
                    "description: 根据整改方案执行修复",
                    "consumes_artifact_types:",
                    "  - inspection_result",
                    "  - remediation_plan_result",
                    "outputs:",
                    "  - remediation_apply_result",
                    "can_parallel: false",
                    "risk_level: high",
                    "completion_signal: remediation_apply_result_ready",
                    "side_effect_level: write",
                    "kind: remediation_apply",
                    "plan_role: conditional",
                    "activation_mode: approval_gated",
                    "intent_tags:",
                    "  - remediation",
                    "  - remediation_apply",
                    "  - apply",
                ]
            ),
            encoding="utf-8",
        )
        (steps_dir / "report.yaml").write_text(
            "\n".join(
                [
                    "id: report",
                    "domain: security",
                    "description: 汇总结果并生成报告",
                    "consumes_artifact_types:",
                    "  - inspection_result",
                    "  - remediation_plan_result",
                    "  - remediation_apply_result",
                    "outputs:",
                    "  - report_result",
                    "can_parallel: false",
                    "risk_level: low",
                    "completion_signal: report_result_ready",
                    "side_effect_level: read_only",
                    "kind: report",
                    "plan_role: terminal",
                    "activation_mode: after_artifact",
                    "intent_tags:",
                    "  - reporting",
                ]
            ),
            encoding="utf-8",
        )
        step_registry = StepRegistry(StepRegistryLoader(workspace_dir=str(steps_dir), global_dir=str(tmp_path / "none")))
        step_registry.load_all()
        manager = PlanManager(step_registry=step_registry)
        from langchain_core.messages import HumanMessage

        plan = manager.create_initial_plan([HumanMessage(content="先帮我找一下当前代码的安全检查")])

        assert [todo["todo_id"] for todo in plan["todos"]] == ["inspect"]

    def test_registry_plan_adds_apply_only_for_explicit_execution_request(self, tmp_path) -> None:
        steps_dir = tmp_path / "steps_full"
        steps_dir.mkdir(parents=True)
        (steps_dir / "inspect.yaml").write_text(
            "\n".join(
                [
                    "id: inspect",
                    "domain: security",
                    "description: 执行代码安全检查",
                    "outputs:",
                    "  - inspection_result",
                    "can_parallel: true",
                    "risk_level: low",
                    "completion_signal: inspection_result_ready",
                    "side_effect_level: read_only",
                    "kind: inspection",
                    "plan_role: core",
                    "activation_mode: immediate",
                    "intent_tags:",
                    "  - inspection",
                ]
            ),
            encoding="utf-8",
        )
        (steps_dir / "remediation_plan.yaml").write_text(
            "\n".join(
                [
                    "id: remediation_plan",
                    "domain: security",
                    "description: 根据检查结果生成整改方案",
                    "consumes_artifact_types:",
                    "  - inspection_result",
                    "outputs:",
                    "  - remediation_plan_result",
                    "can_parallel: false",
                    "risk_level: medium",
                    "completion_signal: remediation_plan_result_ready",
                    "side_effect_level: read_only",
                    "kind: remediation",
                    "plan_role: conditional",
                    "activation_mode: after_artifact",
                    "intent_tags:",
                    "  - remediation",
                    "  - remediation_plan",
                ]
            ),
            encoding="utf-8",
        )
        (steps_dir / "remediation_apply.yaml").write_text(
            "\n".join(
                [
                    "id: remediation_apply",
                    "domain: security",
                    "description: 根据整改方案执行修复",
                    "consumes_artifact_types:",
                    "  - inspection_result",
                    "  - remediation_plan_result",
                    "outputs:",
                    "  - remediation_apply_result",
                    "can_parallel: false",
                    "risk_level: high",
                    "completion_signal: remediation_apply_result_ready",
                    "side_effect_level: write",
                    "kind: remediation_apply",
                    "plan_role: conditional",
                    "activation_mode: approval_gated",
                    "intent_tags:",
                    "  - remediation",
                    "  - remediation_apply",
                    "  - apply",
                ]
            ),
            encoding="utf-8",
        )
        (steps_dir / "report.yaml").write_text(
            "\n".join(
                [
                    "id: report",
                    "domain: security",
                    "description: 汇总结果并生成报告",
                    "consumes_artifact_types:",
                    "  - inspection_result",
                    "  - remediation_plan_result",
                    "  - remediation_apply_result",
                    "outputs:",
                    "  - report_result",
                    "can_parallel: false",
                    "risk_level: low",
                    "completion_signal: report_result_ready",
                    "side_effect_level: read_only",
                    "kind: report",
                    "plan_role: terminal",
                    "activation_mode: after_artifact",
                    "intent_tags:",
                    "  - reporting",
                ]
            ),
            encoding="utf-8",
        )
        step_registry = StepRegistry(StepRegistryLoader(workspace_dir=str(steps_dir), global_dir=str(tmp_path / "none")))
        step_registry.load_all()
        manager = PlanManager(step_registry=step_registry)
        from langchain_core.messages import HumanMessage

        plan = manager.create_initial_plan(
            [HumanMessage(content="先做安全检查，再生成整改方案，然后执行修复，最后输出报告")]
        )

        assert [todo["todo_id"] for todo in plan["todos"]] == [
            "inspect",
            "remediation_plan",
            "remediation_apply",
            "report",
        ]

    def test_registry_plan_reuses_completed_inspection_for_follow_up_request(self, tmp_path) -> None:
        steps_dir = tmp_path / "steps_reuse"
        steps_dir.mkdir(parents=True)
        (steps_dir / "inspect.yaml").write_text(
            "\n".join(
                [
                    "id: inspect",
                    "domain: security",
                    "description: 执行代码安全检查",
                    "outputs:",
                    "  - inspection_result",
                    "can_parallel: true",
                    "risk_level: low",
                    "completion_signal: inspection_result_ready",
                    "side_effect_level: read_only",
                    "kind: inspection",
                    "plan_role: core",
                    "activation_mode: immediate",
                    "intent_tags:",
                    "  - inspection",
                ]
            ),
            encoding="utf-8",
        )
        (steps_dir / "remediation_plan.yaml").write_text(
            "\n".join(
                [
                    "id: remediation_plan",
                    "domain: security",
                    "description: 根据检查结果生成整改方案",
                    "consumes_artifact_types:",
                    "  - inspection_result",
                    "outputs:",
                    "  - remediation_plan_result",
                    "can_parallel: false",
                    "risk_level: medium",
                    "completion_signal: remediation_plan_result_ready",
                    "side_effect_level: read_only",
                    "kind: remediation",
                    "plan_role: conditional",
                    "activation_mode: after_artifact",
                    "intent_tags:",
                    "  - remediation",
                    "  - remediation_plan",
                ]
            ),
            encoding="utf-8",
        )
        step_registry = StepRegistry(StepRegistryLoader(workspace_dir=str(steps_dir), global_dir=str(tmp_path / "none")))
        step_registry.load_all()
        manager = PlanManager(step_registry=step_registry)
        from langchain_core.messages import HumanMessage

        plan = manager.create_initial_plan(
            [HumanMessage(content="先做安全检查，再生成整改方案")],
            artifacts=[{"artifact_id": "art_001", "artifact_type": "inspection_result", "status": "ready"}],
            current_plan={
                "plan_version": "v1",
                "objective": "先做安全检查",
                "strategy": "llm_dynamic",
                "missing_inputs": [],
                "reasoning_summary": "",
                "todos": [
                    {
                        "todo_id": "inspect",
                        "step_id": "inspect",
                        "title": "执行检查",
                        "kind": "inspection",
                        "status": "completed",
                        "parallelizable": True,
                        "depends_on": [],
                        "resolved_inputs": {},
                        "consumes_artifacts": [],
                        "execution_mode": "subagent",
                        "approval_required": False,
                    }
                ],
            },
        )

        assert [todo["todo_id"] for todo in plan["todos"]] == ["remediation_plan"]

    def test_skip_pending_approval_todos_cancels_mutation_and_unblocks_report(self) -> None:
        manager = PlanManager()
        plan = {
            "plan_version": "v1",
            "objective": "检查后整改并输出报告",
            "strategy": "rule",
            "missing_inputs": [],
            "reasoning_summary": "",
            "todos": [
                {
                    "todo_id": "inspect",
                    "step_id": "inspect",
                    "title": "执行检查",
                    "kind": "inspection",
                    "status": "completed",
                    "parallelizable": True,
                    "depends_on": [],
                    "original_depends_on": [],
                    "skipped_depends_on": [],
                    "resolved_inputs": {},
                    "consumes_artifacts": [],
                    "execution_mode": "subagent",
                    "approval_required": False,
                },
                {
                    "todo_id": "remediate",
                    "step_id": "remediate",
                    "title": "执行整改",
                    "kind": "remediation",
                    "status": "pending_approval",
                    "parallelizable": False,
                    "depends_on": ["inspect"],
                    "original_depends_on": ["inspect"],
                    "skipped_depends_on": [],
                    "resolved_inputs": {"artifact_ids": ["art_001"]},
                    "consumes_artifacts": ["art_001"],
                    "execution_mode": "subagent",
                    "approval_required": True,
                },
                {
                    "todo_id": "report",
                    "step_id": "report",
                    "title": "输出报告",
                    "kind": "report",
                    "status": "pending",
                    "parallelizable": False,
                    "depends_on": ["inspect", "remediate"],
                    "original_depends_on": ["inspect", "remediate"],
                    "skipped_depends_on": [],
                    "resolved_inputs": {},
                    "consumes_artifacts": ["art_001"],
                    "execution_mode": "subagent",
                    "approval_required": False,
                },
            ],
        }

        updated = manager.skip_pending_approval_todos(plan, ["remediate"])

        assert updated is not None
        statuses = {todo["todo_id"]: todo["status"] for todo in updated["todos"]}
        report = next(todo for todo in updated["todos"] if todo["todo_id"] == "report")
        assert statuses == {"inspect": "completed", "remediate": "cancelled", "report": "ready"}
        assert report["depends_on"] == ["inspect"]
        assert report["original_depends_on"] == ["inspect", "remediate"]
        assert report["skipped_depends_on"] == ["remediate"]

    def test_registry_filtered_plan_respects_capability_pack_steps(self, tmp_path) -> None:
        steps_dir = tmp_path / "steps"
        steps_dir.mkdir(parents=True)
        (steps_dir / "inspect.yaml").write_text(
            "\n".join(
                [
                    "id: inspect",
                    "domain: security",
                    "description: 对目标执行检查任务",
                    "outputs:",
                    "  - inspection_result",
                    "can_parallel: true",
                    "risk_level: low",
                    "completion_signal: inspection_result_ready",
                    "side_effect_level: read_only",
                    "kind: inspection",
                ]
            ),
            encoding="utf-8",
        )
        (steps_dir / "report.yaml").write_text(
            "\n".join(
                [
                    "id: report",
                    "domain: security",
                    "description: 汇总结果并生成报告",
                    "outputs:",
                    "  - report_result",
                    "can_parallel: false",
                    "risk_level: low",
                    "completion_signal: report_result_ready",
                    "side_effect_level: read_only",
                    "kind: report",
                ]
            ),
            encoding="utf-8",
        )
        step_registry = StepRegistry(StepRegistryLoader(workspace_dir=str(steps_dir), global_dir=str(tmp_path / "none")))
        step_registry.load_all()

        capability_registry = CapabilityPackRegistry.__new__(CapabilityPackRegistry)
        capability_registry._loader = None  # type: ignore[attr-defined]
        capability_registry._packs = {
            "security-governance": CapabilityPackDefinition(
                name="security-governance",
                description="security",
                allowed_steps=["inspect", "report"],
                preferred_steps=["report"],
            )
        }

        manager = PlanManager(
            step_registry=step_registry,
            capability_registry=capability_registry,
            capability_pack="security-governance",
        )
        from langchain_core.messages import HumanMessage

        plan = manager.create_initial_plan([HumanMessage(content="先做检查，最后输出报告")])

        assert [todo["todo_id"] for todo in plan["todos"]] == ["inspect", "report"]
        assert plan["todos"][0]["plan_role"] == "core"
        assert plan["todos"][1]["plan_role"] == "terminal"

    def test_registry_plan_builds_full_skeleton_without_auto_including_conditional_step(self, tmp_path) -> None:
        steps_dir = tmp_path / "steps"
        steps_dir.mkdir(parents=True)
        (steps_dir / "inspect.yaml").write_text(
            "\n".join(
                [
                    "id: inspect",
                    "domain: security",
                    "description: 执行项目安全检查",
                    "outputs:",
                    "  - inspection_result",
                    "can_parallel: true",
                    "risk_level: low",
                    "completion_signal: inspection_result_ready",
                    "side_effect_level: read_only",
                    "kind: inspection",
                ]
            ),
            encoding="utf-8",
        )
        (steps_dir / "remediate.yaml").write_text(
            "\n".join(
                [
                    "id: remediate",
                    "domain: security",
                    "description: 根据检查结果整改项目风险",
                    "consumes_artifact_types:",
                    "  - inspection_result",
                    "outputs:",
                    "  - remediation_result",
                    "can_parallel: false",
                    "risk_level: medium",
                    "completion_signal: remediation_result_ready",
                    "side_effect_level: write",
                    "kind: remediation",
                ]
            ),
            encoding="utf-8",
        )
        (steps_dir / "report.yaml").write_text(
            "\n".join(
                [
                    "id: report",
                    "domain: cross_domain",
                    "description: 汇总检查结果并生成总结报告",
                    "consumes_artifact_types:",
                    "  - inspection_result",
                    "  - remediation_result",
                    "outputs:",
                    "  - report_result",
                    "can_parallel: false",
                    "risk_level: low",
                    "completion_signal: report_result_ready",
                    "side_effect_level: read_only",
                    "kind: report",
                ]
            ),
            encoding="utf-8",
        )
        step_registry = StepRegistry(StepRegistryLoader(workspace_dir=str(steps_dir), global_dir=str(tmp_path / "none")))
        step_registry.load_all()

        manager = PlanManager(step_registry=step_registry)
        from langchain_core.messages import HumanMessage

        plan = manager.create_initial_plan([HumanMessage(content="请先做安全检查，最后生成总结报告")])

        todo_ids = [todo["todo_id"] for todo in plan["todos"]]
        assert todo_ids == ["inspect", "report"]
        report = plan["todos"][1]
        assert report["depends_on"] == ["inspect"]
        assert report["plan_role"] == "terminal"
        assert report["status"] == "pending"

    def test_registry_plan_supports_analysis_design_and_documentation_skeleton(self, tmp_path) -> None:
        steps_dir = tmp_path / "steps"
        steps_dir.mkdir(parents=True)
        (steps_dir / "requirement_analysis.yaml").write_text(
            "\n".join(
                [
                    "id: requirement_analysis",
                    "domain: development",
                    "description: 分析需求并生成结构化摘要",
                    "outputs:",
                    "  - requirement_summary",
                    "can_parallel: false",
                    "risk_level: low",
                    "completion_signal: requirement_summary_ready",
                    "side_effect_level: read_only",
                    "kind: analysis",
                ]
            ),
            encoding="utf-8",
        )
        (steps_dir / "api_design.yaml").write_text(
            "\n".join(
                [
                    "id: api_design",
                    "domain: development",
                    "description: 根据需求设计 API 契约",
                    "consumes_artifact_types:",
                    "  - requirement_summary",
                    "outputs:",
                    "  - api_contract",
                    "can_parallel: false",
                    "risk_level: low",
                    "completion_signal: api_contract_ready",
                    "side_effect_level: read_only",
                    "kind: design",
                ]
            ),
            encoding="utf-8",
        )
        (steps_dir / "api_doc_generate.yaml").write_text(
            "\n".join(
                [
                    "id: api_doc_generate",
                    "domain: development",
                    "description: 根据 API 契约生成接口文档",
                    "consumes_artifact_types:",
                    "  - api_contract",
                    "outputs:",
                    "  - api_doc",
                    "can_parallel: false",
                    "risk_level: low",
                    "completion_signal: api_doc_ready",
                    "side_effect_level: read_only",
                    "kind: documentation",
                ]
            ),
            encoding="utf-8",
        )
        step_registry = StepRegistry(StepRegistryLoader(workspace_dir=str(steps_dir), global_dir=str(tmp_path / "none")))
        step_registry.load_all()

        manager = PlanManager(step_registry=step_registry)
        from langchain_core.messages import HumanMessage

        plan = manager.create_initial_plan([HumanMessage(content="先分析需求，再设计 API，最后输出接口文档")])

        assert [todo["todo_id"] for todo in plan["todos"]] == [
            "requirement_analysis",
            "api_design",
            "api_doc_generate",
        ]
        assert [todo["plan_role"] for todo in plan["todos"]] == ["core", "core", "terminal"]

    def test_registry_replan_binds_artifacts_and_step_risk_metadata(self, tmp_path) -> None:
        steps_dir = tmp_path / "steps"
        steps_dir.mkdir(parents=True)
        (steps_dir / "inspect.yaml").write_text(
            "\n".join(
                [
                    "id: inspect",
                    "domain: security",
                    "description: 对目标执行检查任务",
                    "outputs:",
                    "  - inspection_result",
                    "can_parallel: true",
                    "risk_level: low",
                    "completion_signal: inspection_result_ready",
                    "side_effect_level: read_only",
                    "kind: inspection",
                ]
            ),
            encoding="utf-8",
        )
        (steps_dir / "remediate.yaml").write_text(
            "\n".join(
                [
                    "id: remediate",
                    "domain: security",
                    "description: 根据检查结果执行整改",
                    "consumes_artifact_types:",
                    "  - inspection_result",
                    "outputs:",
                    "  - remediation_result",
                    "can_parallel: false",
                    "risk_level: medium",
                    "completion_signal: remediation_result_ready",
                    "side_effect_level: write",
                    "kind: remediation",
                ]
            ),
            encoding="utf-8",
        )
        step_registry = StepRegistry(StepRegistryLoader(workspace_dir=str(steps_dir), global_dir=str(tmp_path / "none")))
        step_registry.load_all()

        capability_registry = CapabilityPackRegistry.__new__(CapabilityPackRegistry)
        capability_registry._loader = None  # type: ignore[attr-defined]
        capability_registry._packs = {
            "security-governance": CapabilityPackDefinition(
                name="security-governance",
                description="security",
                allowed_steps=["inspect", "remediate"],
                preferred_steps=["inspect", "remediate"],
            )
        }

        manager = PlanManager(
            step_registry=step_registry,
            capability_registry=capability_registry,
            capability_pack="security-governance",
        )
        from langchain_core.messages import HumanMessage

        plan = manager.replan(
            [HumanMessage(content="先做检查，再根据结果加固")],
            artifacts=[
                {
                    "artifact_id": "art_001",
                    "artifact_type": "inspection_result",
                    "status": "ready",
                    "metadata": {"todo_id": "inspect"},
                }
            ],
            current_plan={
                "plan_version": "v1",
                "objective": "先做检查，再根据结果加固",
                "strategy": "rule_based_fallback",
                "missing_inputs": [],
                "reasoning_summary": "",
                "todos": [
                    {
                        "todo_id": "inspect",
                        "step_id": "inspect",
                        "title": "执行检查任务",
                        "kind": "inspection",
                        "status": "completed",
                        "parallelizable": True,
                        "depends_on": [],
                        "resolved_inputs": {},
                        "consumes_artifacts": [],
                        "execution_mode": "subagent",
                        "approval_required": False,
                    }
                ],
            },
        )

        assert [todo["todo_id"] for todo in plan["todos"]] == ["remediate"]
        assert plan["todos"][0]["consumes_artifacts"] == ["art_001"]
        assert plan["todos"][0]["resolved_inputs"] == {"artifact_ids": ["art_001"]}
        assert plan["todos"][0]["approval_required"] is True

    def test_registry_replan_scopes_report_artifacts_to_current_plan_lineage(self, tmp_path) -> None:
        steps_dir = tmp_path / "steps"
        steps_dir.mkdir(parents=True)
        (steps_dir / "inspect.yaml").write_text(
            "\n".join(
                [
                    "id: inspect",
                    "domain: security",
                    "description: 对目标执行检查任务",
                    "outputs:",
                    "  - inspection_result",
                    "can_parallel: true",
                    "risk_level: low",
                    "completion_signal: inspection_result_ready",
                    "side_effect_level: read_only",
                    "kind: inspection",
                ]
            ),
            encoding="utf-8",
        )
        (steps_dir / "remediation_plan.yaml").write_text(
            "\n".join(
                [
                    "id: remediation_plan",
                    "domain: security",
                    "description: 生成整改方案",
                    "consumes_artifact_types:",
                    "  - inspection_result",
                    "outputs:",
                    "  - remediation_plan_result",
                    "can_parallel: false",
                    "risk_level: low",
                    "completion_signal: remediation_plan_ready",
                    "side_effect_level: read_only",
                    "kind: remediation",
                ]
            ),
            encoding="utf-8",
        )
        (steps_dir / "remediation_apply.yaml").write_text(
            "\n".join(
                [
                    "id: remediation_apply",
                    "domain: security",
                    "description: 执行修复",
                    "consumes_artifact_types:",
                    "  - remediation_plan_result",
                    "outputs:",
                    "  - remediation_apply_result",
                    "can_parallel: false",
                    "risk_level: high",
                    "completion_signal: remediation_apply_ready",
                    "side_effect_level: write",
                    "kind: remediation_apply",
                ]
            ),
            encoding="utf-8",
        )
        (steps_dir / "report.yaml").write_text(
            "\n".join(
                [
                    "id: report",
                    "domain: security",
                    "description: 输出报告",
                    "consumes_artifact_types:",
                    "  - inspection_result",
                    "  - remediation_plan_result",
                    "  - remediation_apply_result",
                    "outputs:",
                    "  - report_result",
                    "can_parallel: false",
                    "risk_level: low",
                    "completion_signal: report_ready",
                    "side_effect_level: read_only",
                    "kind: report",
                    "plan_role: terminal",
                ]
            ),
            encoding="utf-8",
        )
        step_registry = StepRegistry(StepRegistryLoader(workspace_dir=str(steps_dir), global_dir=str(tmp_path / "none")))
        step_registry.load_all()

        capability_registry = CapabilityPackRegistry.__new__(CapabilityPackRegistry)
        capability_registry._loader = None  # type: ignore[attr-defined]
        capability_registry._packs = {
            "security-governance": CapabilityPackDefinition(
                name="security-governance",
                description="security",
                allowed_steps=["inspect", "remediation_plan", "remediation_apply", "report"],
                preferred_steps=["inspect", "remediation_plan", "remediation_apply", "report"],
            )
        }

        manager = PlanManager(
            step_registry=step_registry,
            capability_registry=capability_registry,
            capability_pack="security-governance",
        )
        from langchain_core.messages import HumanMessage

        plan = manager.replan(
            [HumanMessage(content="输出最终报告")],
            artifacts=[
                {
                    "artifact_id": "art_inspect_current",
                    "artifact_type": "inspection_result",
                    "status": "ready",
                    "metadata": {"todo_id": "inspect"},
                },
                {
                    "artifact_id": "art_plan_current",
                    "artifact_type": "remediation_plan_result",
                    "status": "ready",
                    "metadata": {"todo_id": "remediation_plan"},
                },
                {
                    "artifact_id": "art_apply_old",
                    "artifact_type": "remediation_apply_result",
                    "status": "ready",
                    "metadata": {"todo_id": "remediation_apply"},
                },
            ],
            current_plan={
                "plan_version": "v1",
                "objective": "先做安全检查，再生成整改方案，然后执行修复，最后输出报告",
                "strategy": "rule_based_fallback",
                "missing_inputs": [],
                "reasoning_summary": "",
                "todos": [
                    {
                        "todo_id": "inspect",
                        "step_id": "inspect",
                        "title": "执行安全检查",
                        "kind": "inspection",
                        "status": "completed",
                        "parallelizable": True,
                        "depends_on": [],
                        "resolved_inputs": {},
                        "consumes_artifacts": [],
                        "execution_mode": "subagent",
                        "approval_required": False,
                    },
                    {
                        "todo_id": "remediation_plan",
                        "step_id": "remediation_plan",
                        "title": "生成整改方案",
                        "kind": "remediation",
                        "status": "completed",
                        "parallelizable": False,
                        "depends_on": ["inspect"],
                        "resolved_inputs": {},
                        "consumes_artifacts": ["art_inspect_current"],
                        "execution_mode": "subagent",
                        "approval_required": False,
                    },
                    {
                        "todo_id": "remediation_apply",
                        "step_id": "remediation_apply",
                        "title": "执行修复",
                        "kind": "remediation_apply",
                        "status": "cancelled",
                        "parallelizable": False,
                        "depends_on": ["remediation_plan"],
                        "resolved_inputs": {},
                        "consumes_artifacts": ["art_plan_current"],
                        "execution_mode": "subagent",
                        "approval_required": True,
                    },
                ],
            },
        )

        assert [todo["todo_id"] for todo in plan["todos"]] == ["report"]
        assert plan["todos"][0]["consumes_artifacts"] == ["art_inspect_current", "art_plan_current"]
        assert "art_apply_old" not in plan["todos"][0]["consumes_artifacts"]


class TestDispatchPolicy:
    """DispatchPolicy should batch parallel and serial work conservatively."""

    def test_parallel_and_serial_todos_split_into_batches(self) -> None:
        policy = DispatchPolicy(max_batch_size=2)
        todos = [
            {
                "todo_id": "inspect-host-a",
                "step_id": "inspect",
                "title": "Inspect A",
                "kind": "inspection",
                "status": "ready",
                "parallelizable": True,
                "depends_on": [],
            },
            {
                "todo_id": "inspect-host-b",
                "step_id": "inspect",
                "title": "Inspect B",
                "kind": "inspection",
                "status": "ready",
                "parallelizable": True,
                "depends_on": [],
            },
            {
                "todo_id": "report",
                "step_id": "report",
                "title": "Report",
                "kind": "report",
                "status": "ready",
                "parallelizable": False,
                "depends_on": ["inspect-host-a", "inspect-host-b"],
            },
            {
                "todo_id": "blocked-remediate",
                "step_id": "remediate",
                "title": "Remediate",
                "kind": "remediation",
                "status": "pending",
                "parallelizable": False,
                "depends_on": ["report"],
            },
        ]

        batches = policy.build_batches(todos)  # type: ignore[arg-type]

        assert batches[0]["parallel"] is True
        assert batches[0]["todo_ids"] == ["inspect-host-a", "inspect-host-b"]
        assert batches[1]["parallel"] is False
        assert batches[1]["todo_ids"] == ["report"]


class TestOrchestratorGraph:
    """Orchestrator graph should populate planning state before synthesis."""

    @pytest.mark.asyncio
    async def test_orchestrator_graph_populates_plan_state(self) -> None:
        config = _default_model_config()
        ai_response = AIMessage(content="执行完成")

        with patch("smartclaw.agent.graph.FallbackChain") as mock_fc_cls:
            mock_fc = AsyncMock()
            mock_fc_cls.return_value = mock_fc
            mock_result = MagicMock()
            mock_result.response = ai_response
            mock_fc.execute = AsyncMock(return_value=mock_result)

            graph = build_orchestrator_graph(config, tools=[])
            result = await invoke(
                graph,
                "先做基线检查，再根据结果加固，最后输出报告",
                mode="orchestrator",
            )

        assert result["mode"] == "orchestrator"
        assert result["plan"] is not None
        assert result["todos"] is not None
        assert result["current_phase"] == "finish"
        assert result["phase_status"] == "completed"
        assert result["task_results"] is not None
        assert result["task_results"][0]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_orchestrator_graph_dispatches_subtasks_when_spawn_tool_available(self) -> None:
        """Orchestrator should invoke spawn_sub_agent and aggregate task results."""
        config = _default_model_config()
        ai_response = AIMessage(content="综合完成")
        spawn_tool = DummySpawnTool()
        spawn_tool.seen_tasks = []

        with patch("smartclaw.agent.graph.FallbackChain") as mock_fc_cls:
            mock_fc = AsyncMock()
            mock_fc_cls.return_value = mock_fc
            mock_result = MagicMock()
            mock_result.response = ai_response
            mock_fc.execute = AsyncMock(return_value=mock_result)

            graph = build_orchestrator_graph(config, tools=[spawn_tool])
            result = await invoke(
                graph,
                "先做基线检查，再根据结果加固，最后输出报告",
                mode="orchestrator",
            )

        assert spawn_tool.seen_tasks
        assert any(task_result.get("todo_id") == "inspect" for task_result in result["task_results"] or [])
        assert result["plan"] is not None
        assert result["artifacts"] is not None
        assert result["artifacts"][0]["artifact_type"] == "inspect_result"
        assert result["plan"]["todos"][0]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_orchestrator_graph_advances_across_multiple_phases(self) -> None:
        """Orchestrator should dispatch dependent todos in separate phases."""
        config = _default_model_config()
        ai_response = AIMessage(content="流程全部完成")
        spawn_tool = DummySpawnTool()
        spawn_tool.seen_tasks = []

        with patch("smartclaw.agent.graph.FallbackChain") as mock_fc_cls:
            mock_fc = AsyncMock()
            mock_fc_cls.return_value = mock_fc
            mock_result = MagicMock()
            mock_result.response = ai_response
            mock_fc.execute = AsyncMock(return_value=mock_result)

            graph = build_orchestrator_graph(config, tools=[spawn_tool], max_phases=6)
            result = await invoke(
                graph,
                "先做基线检查，再根据结果加固，最后输出报告",
                mode="orchestrator",
            )

        statuses = {todo["todo_id"]: todo["status"] for todo in result["plan"]["todos"]}
        assert statuses == {
            "inspect": "completed",
            "remediate": "completed",
            "report": "completed",
        }
        assert result["phase_index"] == 3
        assert len([r for r in result["task_results"] if r.get("todo_id")]) == 3
        assert len(result["artifacts"] or []) == 3
        assert len(spawn_tool.seen_tasks) == 3

    @pytest.mark.asyncio
    async def test_orchestrator_graph_retries_schema_validation_when_capability_requires_json(self) -> None:
        """Synthesize should retry when capability-pack schema validation fails."""
        config = _default_model_config()
        invalid = AIMessage(content='{"bad":"value"}')
        valid = AIMessage(content='{"status":"ok"}')

        with patch("smartclaw.agent.graph.FallbackChain") as mock_fc_cls:
            mock_fc = AsyncMock()
            mock_fc_cls.return_value = mock_fc
            mock_fc.execute = AsyncMock(
                side_effect=[
                    MagicMock(response=invalid),
                    MagicMock(response=valid),
                ]
            )

            graph = build_orchestrator_graph(config, tools=[])
            result = await invoke(
                graph,
                "输出结构化结果",
                mode="orchestrator",
                capability_pack="security-governance",
                capability_policy={
                    "schema_enforced": True,
                    "result_schema": '{"type":"object","required":["status"]}',
                    "max_schema_retries": 1,
                },
            )

        assert result["schema_validation"]["valid"] is True
        assert result["structured_result"] == {"status": "ok"}
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_orchestrator_graph_retries_failed_subtasks_per_capability_policy(self) -> None:
        """Dispatch should retry failed worker tasks when capability policy allows it."""
        config = _default_model_config()
        ai_response = AIMessage(content="综合完成")
        spawn_tool = FlakySpawnTool()
        spawn_tool.attempts = {}

        with patch("smartclaw.agent.graph.FallbackChain") as mock_fc_cls:
            mock_fc = AsyncMock()
            mock_fc_cls.return_value = mock_fc
            mock_result = MagicMock()
            mock_result.response = ai_response
            mock_fc.execute = AsyncMock(return_value=mock_result)

            graph = build_orchestrator_graph(config, tools=[spawn_tool])
            result = await invoke(
                graph,
                "先做基线检查，再根据结果加固，最后输出报告",
                mode="orchestrator",
                capability_policy={
                    "max_task_retries": 1,
                    "retry_on_error": True,
                    "concurrency_limits": {"inspection": 1},
                },
            )

        task_results = [item for item in result["task_results"] if item.get("todo_id") == "inspect"]
        assert task_results
        assert task_results[0]["status"] == "completed"
        assert task_results[0]["attempts"] == 2

    @pytest.mark.asyncio
    async def test_orchestrator_graph_stops_when_replanning_budget_exceeded(self) -> None:
        config = _default_model_config()
        ai_response = AIMessage(content="预算用尽后收敛")
        spawn_tool = DummySpawnTool()
        spawn_tool.seen_tasks = []

        with patch("smartclaw.agent.graph.FallbackChain") as mock_fc_cls:
            mock_fc = AsyncMock()
            mock_fc_cls.return_value = mock_fc
            mock_result = MagicMock()
            mock_result.response = ai_response
            mock_fc.execute = AsyncMock(return_value=mock_result)

            graph = build_orchestrator_graph(config, tools=[spawn_tool], max_phases=6)
            result = await invoke(
                graph,
                "先做基线检查，再根据结果加固，最后输出报告",
                mode="orchestrator",
                capability_policy={"max_replanning_rounds": 1},
            )

        statuses = {todo["todo_id"]: todo["status"] for todo in result["plan"]["todos"]}
        assert statuses["inspect"] == "completed"
        assert statuses["remediate"] == "completed"
        assert statuses["report"] == "completed"
        assert result["replanning_count"] == 0
        assert result["guardrail_status"] is None
        assert result["phase_status"] == "completed"
        assert result["final_answer"] == "预算用尽后收敛"

    @pytest.mark.asyncio
    async def test_orchestrator_graph_pauses_todos_that_require_approval(self, tmp_path) -> None:
        spawn_tool = DummySpawnTool()
        spawn_tool.seen_tasks = []

        with patch(
            "smartclaw.agent.llm_planner._llm_call_with_fallback",
            AsyncMock(side_effect=RuntimeError("planner unavailable")),
        ):
            graph = build_orchestrator_graph(
                _default_model_config(),
                tools=[spawn_tool],
                step_registry=_approval_registry(tmp_path),
                capability_registry=_approval_capability_registry(),
                capability_pack="security-governance",
                max_phases=6,
            )
            result = await invoke(
                graph,
                "先做检查，再根据结果加固",
                mode="orchestrator",
                capability_pack="security-governance",
            )

        statuses = {todo["todo_id"]: todo["status"] for todo in result["plan"]["todos"]}
        assert statuses == {"inspect": "completed", "remediate": "pending_approval"}
        assert len(spawn_tool.seen_tasks) == 1
        assert result["current_phase"] == "finish"
        assert result["phase_status"] == "awaiting_approval"
        assert result["clarification_request"] is not None
        assert result["clarification_request"]["kind"] == "approval"
        assert result["clarification_request"]["options"] == ["approve", "report_only", "cancel"]
        assert any(
            "待审批步骤: 根据检查结果执行整改" in detail
            for detail in (result["clarification_request"].get("details") or [])
        )

    @pytest.mark.asyncio
    async def test_orchestrator_graph_dispatches_approved_todos(self, tmp_path) -> None:
        ai_response = AIMessage(content="执行完成")
        spawn_tool = DummySpawnTool()
        spawn_tool.seen_tasks = []

        with patch(
            "smartclaw.agent.llm_planner._llm_call_with_fallback",
            AsyncMock(side_effect=RuntimeError("planner unavailable")),
        ), patch("smartclaw.agent.graph.FallbackChain") as mock_fc_cls:
            mock_fc = AsyncMock()
            mock_fc_cls.return_value = mock_fc
            mock_result = MagicMock()
            mock_result.response = ai_response
            mock_fc.execute = AsyncMock(return_value=mock_result)

            graph = build_orchestrator_graph(
                _default_model_config(),
                tools=[spawn_tool],
                step_registry=_approval_registry(tmp_path),
                capability_registry=_approval_capability_registry(),
                capability_pack="security-governance",
                max_phases=6,
            )
            result = await invoke(
                graph,
                "先做检查，再根据结果加固",
                mode="orchestrator",
                approved=True,
                capability_pack="security-governance",
            )

        statuses = {todo["todo_id"]: todo["status"] for todo in result["plan"]["todos"]}
        assert statuses == {"inspect": "completed", "remediate": "completed"}
        assert len(spawn_tool.seen_tasks) == 2
        assert result["clarification_request"] is None

    @pytest.mark.asyncio
    async def test_orchestrator_graph_report_only_skips_remediation_and_completes_report(self, tmp_path) -> None:
        ai_response = AIMessage(content="执行完成")
        spawn_tool = DummySpawnTool()
        spawn_tool.seen_tasks = []

        with patch(
            "smartclaw.agent.llm_planner._llm_call_with_fallback",
            AsyncMock(side_effect=RuntimeError("planner unavailable")),
        ), patch("smartclaw.agent.graph.FallbackChain") as mock_fc_cls:
            mock_fc = AsyncMock()
            mock_fc_cls.return_value = mock_fc
            mock_result = MagicMock()
            mock_result.response = ai_response
            mock_fc.execute = AsyncMock(return_value=mock_result)

            graph = build_orchestrator_graph(
                _default_model_config(),
                tools=[spawn_tool],
                step_registry=_approval_registry(tmp_path),
                capability_registry=_approval_capability_registry(),
                capability_pack="security-governance",
                max_phases=6,
            )
            result = await invoke(
                graph,
                "先做检查，再根据结果加固，最后输出报告",
                mode="orchestrator",
                approval_action="report_only",
                capability_pack="security-governance",
            )

        statuses = {todo["todo_id"]: todo["status"] for todo in result["plan"]["todos"]}
        assert statuses == {"inspect": "completed", "remediate": "cancelled", "report": "completed"}
        assert len(spawn_tool.seen_tasks) == 2
        report_prompt = spawn_tool.seen_tasks[-1]
        assert "Execution plan status:" in report_prompt
        assert "[cancelled] remediate (remediate): 根据检查结果执行整改" in report_prompt
        assert "Do not claim completed remediation" in report_prompt
        assert "report it as skipped or not executed" in report_prompt
        assert result["clarification_request"] is None

    def test_finalize_successful_synthesis_completes_terminal_todo_without_rewriting_cancelled(self) -> None:
        manager = PlanManager()
        for report_status in ("pending", "ready", "in_progress"):
            plan = {
                "plan_version": "v1",
                "objective": "report only",
                "strategy": "test",
                "todos": [
                    {
                        "todo_id": "inspect",
                        "step_id": "inspect",
                        "title": "执行检查",
                        "status": "completed",
                        "plan_role": "core",
                    },
                    {
                        "todo_id": "remediate",
                        "step_id": "remediate",
                        "title": "执行修复",
                        "status": "cancelled",
                        "plan_role": "conditional",
                    },
                    {
                        "todo_id": "report",
                        "step_id": "report",
                        "title": "输出报告",
                        "status": report_status,
                        "plan_role": "terminal",
                    },
                ],
            }

            finalized = manager.finalize_successful_synthesis(plan)

            assert finalized is not None
            statuses = {todo["todo_id"]: todo["status"] for todo in finalized["todos"]}
            assert statuses == {
                "inspect": "completed",
                "remediate": "cancelled",
                "report": "completed",
            }
            assert manager.is_plan_completed(finalized) is True


    def test_should_not_replan_when_plan_already_completed(self) -> None:
        manager = PlanManager()
        plan = {
            "plan_version": "v1",
            "objective": "report only",
            "strategy": "test",
            "todos": [
                {
                    "todo_id": "inspect",
                    "step_id": "inspect",
                    "title": "检查",
                    "status": "completed",
                },
                {
                    "todo_id": "remediate",
                    "step_id": "remediate",
                    "title": "整改",
                    "status": "cancelled",
                },
                {
                    "todo_id": "report",
                    "step_id": "report",
                    "title": "报告",
                    "status": "completed",
                },
            ],
        }

        assert manager.is_plan_completed(plan) is True
        assert _should_attempt_replan(manager, plan, ready_todos=[]) is False

    @pytest.mark.asyncio
    async def test_orchestrator_graph_stops_on_repeated_error_pattern(self) -> None:
        spawn_tool = AlwaysFailSpawnTool()

        graph = build_orchestrator_graph(
            _default_model_config(),
            tools=[spawn_tool],
            max_phases=6,
        )
        result = await invoke(
            graph,
            "先做基线检查，再根据结果加固，最后输出报告",
            mode="orchestrator",
            capability_policy={
                "max_task_retries": 2,
                "retry_on_error": True,
                "repeated_error_threshold": 2,
            },
        )

        assert result["guardrail_status"]["reason"] == "repeated_error"
        assert result["guardrail_status"]["source"] == "task_retries"
        assert result["phase_status"] == "guarded_stop"
        assert "same failure pattern repeated" in (result["final_answer"] or "")
