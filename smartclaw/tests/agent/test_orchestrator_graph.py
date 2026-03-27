"""Unit tests for orchestrator planning and graph execution."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool

from smartclaw.agent.dispatch_policy import DispatchPolicy
from smartclaw.agent.graph import invoke
from smartclaw.agent.orchestrator_graph import build_orchestrator_graph
from smartclaw.agent.plan_manager import PlanManager
from smartclaw.providers.config import ModelConfig


def _default_model_config() -> ModelConfig:
    return ModelConfig(
        primary="openai/gpt-4o",
        fallbacks=[],
        temperature=0.0,
        max_tokens=1024,
    )


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


class TestPlanManager:
    """PlanManager should infer coarse-grained orchestrator todos."""

    def test_infers_inspection_remediation_and_report_todos(self) -> None:
        manager = PlanManager()
        from langchain_core.messages import HumanMessage

        plan = manager.create_initial_plan(
            [HumanMessage(content="先做基线检查，再根据结果加固，最后输出报告")]
        )

        todo_ids = [todo["id"] for todo in plan["todos"]]
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
        statuses = {todo["id"]: todo["status"] for todo in updated["todos"]}
        assert statuses["inspect"] == "completed"
        assert statuses["remediate"] == "ready"
        assert statuses["report"] == "pending"


class TestDispatchPolicy:
    """DispatchPolicy should batch parallel and serial work conservatively."""

    def test_parallel_and_serial_todos_split_into_batches(self) -> None:
        policy = DispatchPolicy(max_batch_size=2)
        todos = [
            {
                "id": "inspect-host-a",
                "title": "Inspect A",
                "kind": "inspection",
                "status": "ready",
                "parallelizable": True,
                "depends_on": [],
            },
            {
                "id": "inspect-host-b",
                "title": "Inspect B",
                "kind": "inspection",
                "status": "ready",
                "parallelizable": True,
                "depends_on": [],
            },
            {
                "id": "report",
                "title": "Report",
                "kind": "report",
                "status": "ready",
                "parallelizable": False,
                "depends_on": ["inspect-host-a", "inspect-host-b"],
            },
            {
                "id": "blocked-remediate",
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
        assert result["current_phase"] == "completed"
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

        statuses = {todo["id"]: todo["status"] for todo in result["plan"]["todos"]}
        assert statuses == {
            "inspect": "completed",
            "remediate": "completed",
            "report": "completed",
        }
        assert result["phase_index"] == 3
        assert len([r for r in result["task_results"] if r.get("todo_id")]) == 3
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
