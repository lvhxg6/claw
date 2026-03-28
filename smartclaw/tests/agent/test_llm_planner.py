"""Unit tests for the LLM-backed planner."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import BaseTool

from smartclaw.agent.llm_planner import LLMPlanner
from smartclaw.agent.graph import invoke
from smartclaw.agent.orchestrator_graph import build_orchestrator_graph
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


def _registry_with_steps(tmp_path) -> StepRegistry:
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
    registry = StepRegistry(StepRegistryLoader(workspace_dir=str(steps_dir), global_dir=str(tmp_path / "none")))
    registry.load_all()
    return registry


def _registry_with_four_steps(tmp_path) -> StepRegistry:
    steps_dir = tmp_path / "steps4"
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
    registry = StepRegistry(StepRegistryLoader(workspace_dir=str(steps_dir), global_dir=str(tmp_path / "none")))
    registry.load_all()
    return registry


def _capability_registry() -> CapabilityPackRegistry:
    registry = CapabilityPackRegistry.__new__(CapabilityPackRegistry)
    registry._loader = None  # type: ignore[attr-defined]
    registry._packs = {
        "security-governance": CapabilityPackDefinition(
            name="security-governance",
            description="security",
            allowed_steps=["inspect", "report"],
            preferred_steps=["inspect", "report"],
        )
    }
    return registry


def _four_step_capability_registry() -> CapabilityPackRegistry:
    registry = CapabilityPackRegistry.__new__(CapabilityPackRegistry)
    registry._loader = None  # type: ignore[attr-defined]
    registry._packs = {
        "security-governance": CapabilityPackDefinition(
            name="security-governance",
            description="security",
            allowed_steps=["inspect", "remediation_plan", "remediation_apply", "report"],
            preferred_steps=["inspect", "remediation_plan", "remediation_apply", "report"],
        )
    }
    return registry


class DummySpawnTool(BaseTool):
    name: str = "spawn_sub_agent"
    description: str = "spawn"

    def _run(self, *args, **kwargs):
        return "not-used"

    async def _arun(self, task: str, **kwargs):
        return f"completed:{task.splitlines()[1]}"


class TestLLMPlanner:
    def test_step_registry_filters_candidates_by_artifacts_and_terminal_steps(self, tmp_path) -> None:
        registry = _registry_with_steps(tmp_path)
        pack = _capability_registry().get("security-governance")

        initial = registry.get_candidate_steps(pack, available_artifact_types=set(), terminal_step_ids=set())
        follow_up = registry.get_candidate_steps(
            pack,
            available_artifact_types={"inspection_result"},
            terminal_step_ids={"inspect"},
        )

        assert [step["id"] for step in initial] == ["inspect"]
        assert [step["id"] for step in follow_up] == ["report"]

    @pytest.mark.asyncio
    async def test_llm_planner_parses_valid_todo_plan(self, tmp_path) -> None:
        registry = _registry_with_steps(tmp_path)
        planner = LLMPlanner(
            model_config=_default_model_config(),
            step_registry=registry,
            capability_registry=_capability_registry(),
            capability_pack="security-governance",
        )
        response = AIMessage(
            content=(
                '{"plan_version":"v1","objective":"先做检查再报告","strategy":"llm_dynamic",'
                '"missing_inputs":[],"reasoning_summary":"先检查后报告","todos":['
                '{"todo_id":"inspect","step_id":"inspect","title":"执行检查","kind":"inspection",'
                '"status":"ready","parallelizable":true,"depends_on":[],"resolved_inputs":{},'
                '"consumes_artifacts":[],"execution_mode":"subagent","approval_required":false},'
                '{"todo_id":"report","step_id":"report","title":"输出报告","kind":"report",'
                '"status":"pending","parallelizable":false,"depends_on":["inspect"],"resolved_inputs":{},'
                '"consumes_artifacts":[],"execution_mode":"subagent","approval_required":false}'
                "]}"
            )
        )

        with patch("smartclaw.agent.llm_planner._llm_call_with_fallback", AsyncMock(return_value=response)):
            plan = await planner.create_plan(
                [HumanMessage(content="先做检查再输出报告")],
                artifacts=[{"artifact_id": "art_001", "artifact_type": "inspection_result", "status": "ready"}],
            )

        assert plan is not None
        assert [todo["todo_id"] for todo in plan["todos"]] == ["inspect", "report"]
        assert plan["strategy"] == "llm_dynamic"

    @pytest.mark.asyncio
    async def test_llm_planner_replan_allows_dependency_on_completed_todo(self, tmp_path) -> None:
        registry = _registry_with_steps(tmp_path)
        planner = LLMPlanner(
            model_config=_default_model_config(),
            step_registry=registry,
            capability_registry=_capability_registry(),
            capability_pack="security-governance",
        )
        response = AIMessage(
            content=(
                '{"plan_version":"v1","objective":"检查后报告","strategy":"llm_dynamic_replan",'
                '"missing_inputs":[],"reasoning_summary":"检查已完成，继续报告","todos":['
                '{"todo_id":"report","step_id":"report","title":"输出报告","kind":"report",'
                '"status":"pending","parallelizable":false,"depends_on":["inspect"],"resolved_inputs":{},'
                '"consumes_artifacts":["art_001"],"execution_mode":"subagent","approval_required":false}'
                "]}"
            )
        )

        current_plan = {
            "plan_version": "v1",
            "objective": "检查后报告",
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
                    "resolved_inputs": {},
                    "consumes_artifacts": [],
                    "execution_mode": "subagent",
                    "approval_required": False,
                }
            ],
        }

        with patch("smartclaw.agent.llm_planner._llm_call_with_fallback", AsyncMock(return_value=response)):
            plan = await planner.replan(
                [HumanMessage(content="先做检查再输出报告")],
                current_plan=current_plan,
                artifacts=[{"artifact_id": "art_001", "artifact_type": "inspection_result", "status": "ready"}],
                step_run_records=[{"todo_id": "inspect", "step_id": "inspect", "status": "completed"}],
            )

        assert plan is not None
        assert [todo["todo_id"] for todo in plan["todos"]] == ["report"]
        assert plan["todos"][0]["depends_on"] == ["inspect"]
        assert plan["todos"][0]["consumes_artifacts"] == ["art_001"]
        assert plan["todos"][0]["resolved_inputs"] == {"artifact_ids": ["art_001"]}

    @pytest.mark.asyncio
    async def test_llm_planner_prunes_to_minimal_satisfaction_for_inspection_only(self, tmp_path) -> None:
        registry = _registry_with_four_steps(tmp_path)
        planner = LLMPlanner(
            model_config=_default_model_config(),
            step_registry=registry,
            capability_registry=_four_step_capability_registry(),
            capability_pack="security-governance",
        )
        response = AIMessage(
            content=(
                '{"plan_version":"v1","objective":"先做安全检查","strategy":"llm_dynamic",'
                '"missing_inputs":[],"reasoning_summary":"完整工作流","todos":['
                '{"todo_id":"inspect","step_id":"inspect","title":"执行检查","kind":"inspection","status":"ready","parallelizable":true,"depends_on":[],"resolved_inputs":{},"consumes_artifacts":[],"execution_mode":"subagent","approval_required":false},'
                '{"todo_id":"remediation_plan","step_id":"remediation_plan","title":"生成整改方案","kind":"remediation","status":"pending","parallelizable":false,"depends_on":["inspect"],"resolved_inputs":{},"consumes_artifacts":[],"execution_mode":"subagent","approval_required":false},'
                '{"todo_id":"remediation_apply","step_id":"remediation_apply","title":"执行修复","kind":"remediation_apply","status":"pending","parallelizable":false,"depends_on":["remediation_plan"],"resolved_inputs":{},"consumes_artifacts":[],"execution_mode":"subagent","approval_required":true},'
                '{"todo_id":"report","step_id":"report","title":"输出报告","kind":"report","status":"pending","parallelizable":false,"depends_on":["remediation_apply"],"resolved_inputs":{},"consumes_artifacts":[],"execution_mode":"subagent","approval_required":false}'
                "]}"
            )
        )

        with patch("smartclaw.agent.llm_planner._llm_call_with_fallback", AsyncMock(return_value=response)):
            plan = await planner.create_plan([HumanMessage(content="先做安全检查")])

        assert plan is not None
        assert [todo["todo_id"] for todo in plan["todos"]] == ["inspect"]

    @pytest.mark.asyncio
    async def test_llm_planner_keeps_apply_and_report_only_when_explicitly_requested(self, tmp_path) -> None:
        registry = _registry_with_four_steps(tmp_path)
        planner = LLMPlanner(
            model_config=_default_model_config(),
            step_registry=registry,
            capability_registry=_four_step_capability_registry(),
            capability_pack="security-governance",
        )
        response = AIMessage(
            content=(
                '{"plan_version":"v1","objective":"先做安全检查，再生成整改方案，然后执行修复，最后输出报告","strategy":"llm_dynamic",'
                '"missing_inputs":[],"reasoning_summary":"完整工作流","todos":['
                '{"todo_id":"inspect","step_id":"inspect","title":"执行检查","kind":"inspection","status":"ready","parallelizable":true,"depends_on":[],"resolved_inputs":{},"consumes_artifacts":[],"execution_mode":"subagent","approval_required":false},'
                '{"todo_id":"remediation_plan","step_id":"remediation_plan","title":"生成整改方案","kind":"remediation","status":"pending","parallelizable":false,"depends_on":["inspect"],"resolved_inputs":{},"consumes_artifacts":[],"execution_mode":"subagent","approval_required":false},'
                '{"todo_id":"remediation_apply","step_id":"remediation_apply","title":"执行修复","kind":"remediation_apply","status":"pending","parallelizable":false,"depends_on":["remediation_plan"],"resolved_inputs":{},"consumes_artifacts":[],"execution_mode":"subagent","approval_required":true},'
                '{"todo_id":"report","step_id":"report","title":"输出报告","kind":"report","status":"pending","parallelizable":false,"depends_on":["remediation_apply"],"resolved_inputs":{},"consumes_artifacts":[],"execution_mode":"subagent","approval_required":false}'
                "]}"
            )
        )

        with patch("smartclaw.agent.llm_planner._llm_call_with_fallback", AsyncMock(return_value=response)):
            plan = await planner.create_plan([HumanMessage(content="先做安全检查，再生成整改方案，然后执行修复，最后输出报告")])

        assert plan is not None
        assert [todo["todo_id"] for todo in plan["todos"]] == [
            "inspect",
            "remediation_plan",
            "remediation_apply",
            "report",
        ]

    @pytest.mark.asyncio
    async def test_llm_planner_reuses_completed_session_steps_for_new_request(self, tmp_path) -> None:
        registry = _registry_with_four_steps(tmp_path)
        planner = LLMPlanner(
            model_config=_default_model_config(),
            step_registry=registry,
            capability_registry=_four_step_capability_registry(),
            capability_pack="security-governance",
        )
        response = AIMessage(
            content=(
                '{"plan_version":"v1","objective":"先做安全检查，再生成整改方案","strategy":"llm_dynamic",'
                '"missing_inputs":[],"reasoning_summary":"继续剩余步骤","todos":['
                '{"todo_id":"inspect","step_id":"inspect","title":"执行检查","kind":"inspection","status":"ready","parallelizable":true,"depends_on":[],"resolved_inputs":{},"consumes_artifacts":[],"execution_mode":"subagent","approval_required":false},'
                '{"todo_id":"remediation_plan","step_id":"remediation_plan","title":"生成整改方案","kind":"remediation","status":"pending","parallelizable":false,"depends_on":["inspect"],"resolved_inputs":{},"consumes_artifacts":[],"execution_mode":"subagent","approval_required":false}'
                "]}"
            )
        )
        current_plan = {
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
        }

        with patch("smartclaw.agent.llm_planner._llm_call_with_fallback", AsyncMock(return_value=response)):
            plan = await planner.create_plan(
                [HumanMessage(content="先做安全检查，再生成整改方案")],
                artifacts=[{"artifact_id": "art_001", "artifact_type": "inspection_result", "status": "ready"}],
                current_plan=current_plan,
            )

        assert plan is not None
        assert [todo["todo_id"] for todo in plan["todos"]] == ["remediation_plan"]

    @pytest.mark.asyncio
    async def test_orchestrator_graph_falls_back_to_rule_planner_on_invalid_llm_output(self, tmp_path) -> None:
        registry = _registry_with_steps(tmp_path)
        ai_response = AIMessage(content="执行完成")

        with patch(
            "smartclaw.agent.llm_planner._llm_call_with_fallback",
            AsyncMock(return_value=AIMessage(content="not-json")),
        ), patch("smartclaw.agent.graph.FallbackChain") as mock_fc_cls:
            mock_fc = AsyncMock()
            mock_fc_cls.return_value = mock_fc
            mock_result = AsyncMock()
            mock_result.response = ai_response
            mock_fc.execute = AsyncMock(return_value=mock_result)

            graph = build_orchestrator_graph(
                _default_model_config(),
                tools=[],
                step_registry=registry,
                capability_registry=_capability_registry(),
                capability_pack="security-governance",
            )
            result = await invoke(
                graph,
                "先做检查，再根据结果加固，最后输出报告",
                mode="orchestrator",
            )

        todo_ids = [todo["todo_id"] for todo in result["plan"]["todos"]]
        assert todo_ids == ["inspect"]
        assert result["plan"]["strategy"] == "rule_based_fallback"

    @pytest.mark.asyncio
    async def test_orchestrator_graph_replans_remaining_work_with_llm(self, tmp_path) -> None:
        registry = _registry_with_steps(tmp_path)
        spawn_tool = DummySpawnTool()
        synth_response = AIMessage(content="执行完成")
        llm_responses = [
            AIMessage(
                content=(
                    '{"plan_version":"v1","objective":"先检查再报告","strategy":"llm_dynamic",'
                    '"missing_inputs":[],"reasoning_summary":"先检查","todos":['
                    '{"todo_id":"inspect","step_id":"inspect","title":"执行检查","kind":"inspection",'
                    '"status":"ready","parallelizable":true,"depends_on":[],"resolved_inputs":{},'
                    '"consumes_artifacts":[],"execution_mode":"subagent","approval_required":false}'
                    "]}"
                )
            ),
            AIMessage(
                content=(
                    '{"plan_version":"v1","objective":"先检查再报告","strategy":"llm_dynamic_replan",'
                    '"missing_inputs":[],"reasoning_summary":"检查完成后出报告","todos":['
                    '{"todo_id":"report","step_id":"report","title":"输出报告","kind":"report",'
                    '"status":"pending","parallelizable":false,"depends_on":["inspect"],"resolved_inputs":{},'
                    '"consumes_artifacts":["art_001"],"execution_mode":"subagent","approval_required":false}'
                    "]}"
                )
            ),
        ]

        with patch(
            "smartclaw.agent.llm_planner._llm_call_with_fallback",
            AsyncMock(side_effect=llm_responses),
        ), patch("smartclaw.agent.graph.FallbackChain") as mock_fc_cls:
            mock_fc = AsyncMock()
            mock_fc_cls.return_value = mock_fc
            mock_result = AsyncMock()
            mock_result.response = synth_response
            mock_fc.execute = AsyncMock(return_value=mock_result)

            graph = build_orchestrator_graph(
                _default_model_config(),
                tools=[spawn_tool],
                step_registry=registry,
                capability_registry=_capability_registry(),
                capability_pack="security-governance",
                max_phases=6,
            )
            result = await invoke(
                graph,
                "先做检查，最后输出报告",
                mode="orchestrator",
            )

        statuses = {todo["todo_id"]: todo["status"] for todo in result["plan"]["todos"]}
        assert statuses == {"inspect": "completed", "report": "completed"}
        assert len([item for item in result["task_results"] if item.get("todo_id")]) == 2
