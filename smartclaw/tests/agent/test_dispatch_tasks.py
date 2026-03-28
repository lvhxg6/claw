"""Unit tests for smartclaw.agent.dispatch_tasks."""

from __future__ import annotations

from langchain_core.tools import BaseTool

from smartclaw.agent.dispatch_tasks import DispatchTasks


class RecordingSpawnTool(BaseTool):
    """Spawn tool that records incoming tasks."""

    name: str = "spawn_sub_agent"
    description: str = "spawn"
    seen_tasks: list[str] = []

    def _run(self, *args, **kwargs):
        return "unused"

    async def _arun(self, task: str, **kwargs):
        del kwargs
        self.seen_tasks.append(task)
        return "completed"


async def test_run_batches_includes_preferred_skill_guidance_in_prompt() -> None:
    spawn_tool = RecordingSpawnTool()
    runner = DispatchTasks(
        spawn_tool=spawn_tool,
        skill_context_provider=lambda name: f"skill:{name}" if name else "",
    )
    plan = {
        "objective": "执行安全治理流程",
        "todos": [
            {
                "todo_id": "inspect",
                "step_id": "inspect",
                "title": "执行检查任务",
                "kind": "inspection",
                "status": "ready",
                "resolved_inputs": {"artifact_ids": []},
                "execution_mode": "subagent",
                "preferred_skill": "inspection-skill",
            }
        ],
    }
    batches = [{"batch_id": "phase-1-batch-1", "todo_ids": ["inspect"], "parallel": False}]

    results = await runner.run_batches(plan=plan, batches=batches, phase_index=1)

    assert len(results) == 1
    assert spawn_tool.seen_tasks
    prompt = spawn_tool.seen_tasks[0]
    assert "Preferred skill guidance:" in prompt
    assert "skill:inspection-skill" in prompt
