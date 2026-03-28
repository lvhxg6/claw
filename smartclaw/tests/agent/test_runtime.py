"""Unit tests for smartclaw.agent.runtime — AgentRuntime + setup_agent_runtime."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from smartclaw.agent.runtime import AgentRuntime, setup_agent_runtime
from smartclaw.config.settings import SmartClawSettings
from smartclaw.providers.config import ModelConfig
from smartclaw.tools.registry import ToolRegistry


def _make_settings(**overrides) -> SmartClawSettings:
    """Create a SmartClawSettings with sensible test defaults."""
    s = SmartClawSettings()
    s.mcp.enabled = False
    s.skills.enabled = False
    s.sub_agent.enabled = False
    s.memory.enabled = False
    for k, v in overrides.items():
        parts = k.split(".")
        obj = s
        for p in parts[:-1]:
            obj = getattr(obj, p)
        setattr(obj, parts[-1], v)
    return s


@pytest.fixture
def mock_build_graph():
    """Patch build_graph at module level in runtime."""
    with patch("smartclaw.agent.runtime.build_graph") as m:
        m.return_value = MagicMock(name="compiled_graph")
        yield m


# -----------------------------------------------------------------------
# Task 1.3: setup_agent_runtime returns correct structure
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_setup_returns_correct_structure(mock_build_graph):
    """setup_agent_runtime returns AgentRuntime with required fields."""
    settings = _make_settings()
    rt = await setup_agent_runtime(settings)

    assert isinstance(rt, AgentRuntime)
    assert rt.graph is not None
    assert rt.registry is not None
    assert isinstance(rt.registry, ToolRegistry)
    assert rt.system_prompt is not None
    assert isinstance(rt.system_prompt, str)
    assert rt.model_config is not None
    assert rt.registry.count >= 8


@pytest.mark.asyncio
async def test_setup_all_disabled(mock_build_graph):
    """When all optional features disabled, optional components are None."""
    settings = _make_settings()
    rt = await setup_agent_runtime(settings)

    assert rt.memory_store is None
    assert rt.summarizer is None
    assert rt.mcp_manager is None
    assert rt.registry.get("spawn_sub_agent") is None


@pytest.mark.asyncio
async def test_setup_sub_agent_enabled(mock_build_graph):
    """sub_agent.enabled=True registers spawn_sub_agent tool."""
    settings = _make_settings(**{"sub_agent.enabled": True})
    rt = await setup_agent_runtime(settings)
    tool = rt.registry.get("spawn_sub_agent")

    assert tool is not None
    assert "spawn_sub_agent" in rt.tool_names
    assert getattr(tool, "available_tools", [])
    assert all(t.name != "spawn_sub_agent" for t in tool.available_tools)


@pytest.mark.asyncio
async def test_setup_memory_enabled(mock_build_graph):
    """memory.enabled=True initializes memory_store and summarizer."""
    settings = _make_settings(**{"memory.enabled": True})

    with patch("smartclaw.memory.store.MemoryStore", autospec=True) as ms_cls:
        ms_instance = AsyncMock()
        ms_instance.close = AsyncMock()
        ms_cls.return_value = ms_instance

        rt = await setup_agent_runtime(settings)

    assert rt.memory_store is not None
    assert rt.summarizer is not None
    assert rt.tool_result_guard is not None
    assert rt.session_pruner is not None
    assert rt.graph_factory is not None


@pytest.mark.asyncio
async def test_create_graph_uses_graph_factory(mock_build_graph):
    """create_graph() routes through GraphFactory for default and override cases."""
    settings = _make_settings()
    rt = await setup_agent_runtime(settings)

    default_graph = rt.create_graph()
    override_graph = rt.create_graph("openai/gpt-4o")

    assert default_graph is not None
    assert override_graph is not None
    assert mock_build_graph.call_count >= 3


@pytest.mark.asyncio
async def test_resolve_mode_respects_explicit_request(mock_build_graph):
    """Explicit classic/orchestrator requests should win over heuristics."""
    settings = _make_settings(**{"orchestrator.mode": "auto"})
    rt = await setup_agent_runtime(settings)

    decision = rt.resolve_mode(requested_mode="orchestrator", message="hello")

    assert decision.resolved_mode == "orchestrator"
    assert decision.reason == "explicit_request"


@pytest.mark.asyncio
async def test_resolve_mode_auto_uses_heuristics(mock_build_graph):
    """Auto mode should classify multi-stage governance tasks as orchestrator."""
    settings = _make_settings(**{"orchestrator.mode": "auto"})
    rt = await setup_agent_runtime(settings)

    decision = rt.resolve_mode(
        requested_mode="auto",
        message="先做基线检查，再根据结果加固，最后输出报告",
        scenario_type="inspection",
        task_profile="multi_stage",
    )

    assert decision.resolved_mode == "orchestrator"
    assert decision.confidence >= 0.7


@pytest.mark.asyncio
async def test_setup_loads_capability_packs_and_builds_summary(mock_build_graph, tmp_path: Path):
    """Capability packs should be discovered and included in runtime prompt state."""
    pack_dir = tmp_path / "capability_packs" / "security-governance"
    pack_dir.mkdir(parents=True)
    (pack_dir / "manifest.yaml").write_text(
        "\n".join(
            [
                "name: security-governance",
                "description: Security governance workflows",
                "scenario_types:",
                "  - inspection",
                "preferred_mode: orchestrator",
                "allowed_tools:",
                "  - read_file",
                "prompt: Prefer phased inspection and remediation.",
            ]
        ),
        encoding="utf-8",
    )

    settings = _make_settings(
        **{
            "agent_defaults.workspace": str(tmp_path),
            "capability_packs.enabled": True,
            "capability_packs.workspace_dir": "{workspace}/capability_packs",
        }
    )
    rt = await setup_agent_runtime(settings)

    assert rt.capability_registry is not None
    assert rt.step_registry is not None
    assert "inspect" in rt.step_registry.list_ids()
    assert rt.capability_registry.list_names() == ["security-governance"]
    assert "Available Capability Packs" in rt.system_prompt


@pytest.mark.asyncio
async def test_create_request_graph_filters_tools_by_capability_pack(mock_build_graph, tmp_path: Path):
    """Request graph creation should apply capability-pack tool policy."""
    pack_dir = tmp_path / "capability_packs" / "security-governance"
    pack_dir.mkdir(parents=True)
    (pack_dir / "manifest.yaml").write_text(
        "\n".join(
            [
                "name: security-governance",
                "description: Security governance workflows",
                "allowed_tools:",
                "  - read_file",
            ]
        ),
        encoding="utf-8",
    )

    settings = _make_settings(
        **{
            "agent_defaults.workspace": str(tmp_path),
            "capability_packs.enabled": True,
            "capability_packs.workspace_dir": "{workspace}/capability_packs",
        }
    )
    rt = await setup_agent_runtime(settings)
    mock_build_graph.reset_mock()

    rt.create_request_graph(mode="classic", capability_pack="security-governance")

    assert mock_build_graph.called
    filtered_tools = mock_build_graph.call_args.args[1]
    assert [tool.name for tool in filtered_tools] == ["read_file"]


@pytest.mark.asyncio
async def test_build_capability_policy_exposes_governance_fields(mock_build_graph, tmp_path: Path):
    """Runtime should expose normalized capability governance policy."""
    pack_dir = tmp_path / "capability_packs" / "security-governance"
    pack_dir.mkdir(parents=True)
    (pack_dir / "manifest.yaml").write_text(
        "\n".join(
            [
                "name: security-governance",
                "description: Security governance workflows",
                "approval_required: true",
                "approval_message: Please approve execution",
                "allowed_steps:",
                "  - inspect",
                "  - report",
                "preferred_steps:",
                "  - report",
                "result_format: json",
                "schema_enforced: true",
                "result_schema: '{\"type\":\"object\",\"required\":[\"status\"]}'",
                "max_schema_retries: 1",
                "max_task_retries: 2",
                "repeated_error_threshold: 3",
                "retry_on_error: true",
                "concurrency_limits:",
                "  inspection: 2",
            ]
        ),
        encoding="utf-8",
    )
    settings = _make_settings(
        **{
            "agent_defaults.workspace": str(tmp_path),
            "capability_packs.enabled": True,
            "capability_packs.workspace_dir": "{workspace}/capability_packs",
        }
    )
    rt = await setup_agent_runtime(settings)

    policy = rt.build_capability_policy(capability_pack="security-governance")

    assert policy is not None
    assert policy["approval_required"] is True
    assert policy["schema_enforced"] is True
    assert policy["max_schema_retries"] == 1
    assert policy["max_task_retries"] == 2
    assert policy["repeated_error_threshold"] == 3
    assert policy["concurrency_limits"] == {"inspection": 2}
    assert policy["allowed_steps"] == ["inspect", "report"]
    assert policy["preferred_steps"] == ["report"]


@pytest.mark.asyncio
async def test_create_request_graph_passes_capability_pack_to_graph_factory(mock_build_graph, tmp_path: Path):
    pack_dir = tmp_path / "capability_packs" / "security-governance"
    pack_dir.mkdir(parents=True)
    (pack_dir / "manifest.yaml").write_text(
        "\n".join(
            [
                "name: security-governance",
                "description: Security governance workflows",
                "allowed_tools:",
                "  - read_file",
                "allowed_steps:",
                "  - inspect",
                "  - report",
            ]
        ),
        encoding="utf-8",
    )

    settings = _make_settings(
        **{
            "agent_defaults.workspace": str(tmp_path),
            "capability_packs.enabled": True,
            "capability_packs.workspace_dir": "{workspace}/capability_packs",
        }
    )
    rt = await setup_agent_runtime(settings)
    rt.graph_factory.create = MagicMock(return_value="graph")

    result = rt.create_request_graph(mode="orchestrator", capability_pack="security-governance")

    assert result == "graph"
    kwargs = rt.graph_factory.create.call_args.kwargs
    assert kwargs["capability_pack"] == "security-governance"


@pytest.mark.asyncio
async def test_create_request_graph_lazy_loads_skills_for_orchestrator(mock_build_graph, tmp_path: Path):
    skill_dir = tmp_path / "skills" / "inspection-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.yaml").write_text(
        "\n".join(
            [
                "name: inspection-skill",
                "description: Inspection helpers",
                "tools:",
                "  - name: inspect-native",
                "    description: Run inspection helper",
                "    type: shell",
                "    command: echo inspect",
            ]
        ),
        encoding="utf-8",
    )
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
                "preferred_skill: inspection-skill",
                "can_parallel: true",
                "risk_level: low",
                "completion_signal: inspection_result_ready",
                "side_effect_level: read_only",
                "kind: inspection",
            ]
        ),
        encoding="utf-8",
    )
    pack_dir = tmp_path / "capability_packs" / "security-governance"
    pack_dir.mkdir(parents=True)
    (pack_dir / "manifest.yaml").write_text(
        "\n".join(
            [
                "name: security-governance",
                "description: Security governance workflows",
                "allowed_steps:",
                "  - inspect",
            ]
        ),
        encoding="utf-8",
    )

    settings = _make_settings(
        **{
            "agent_defaults.workspace": str(tmp_path),
            "skills.enabled": True,
            "skills.workspace_dir": "{workspace}/skills",
            "capability_packs.enabled": True,
            "capability_packs.workspace_dir": "{workspace}/capability_packs",
            "step_registry.enabled": True,
            "step_registry.workspace_dir": "{workspace}/steps",
        }
    )
    rt = await setup_agent_runtime(settings)

    assert rt.registry.get("inspect-native") is None
    assert "Available Skills" not in rt.system_prompt

    rt.create_request_graph(mode="orchestrator", capability_pack="security-governance")

    assert rt.registry.get("inspect-native") is not None


@pytest.mark.asyncio
async def test_setup_agent_runtime_exposes_builtin_security_skills(mock_build_graph, tmp_path: Path):
    settings = _make_settings(
        **{
            "agent_defaults.workspace": str(tmp_path),
            "skills.enabled": True,
            "skills.workspace_dir": "{workspace}/skills",
        }
    )

    rt = await setup_agent_runtime(settings)

    assert rt.skills_loader is not None
    names = {info.name for info in rt.skills_loader.list_skills()}
    assert {"inspection-skill", "remediation-skill", "reporting-skill"} <= names


# -----------------------------------------------------------------------
# Task 1.3: Component failure tolerance
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sub_agent_failure_tolerance(mock_build_graph):
    """If SpawnSubAgentTool creation fails, runtime still works."""
    settings = _make_settings(**{"sub_agent.enabled": True})

    with patch(
        "smartclaw.agent.sub_agent.SpawnSubAgentTool",
        side_effect=RuntimeError("boom"),
    ):
        rt = await setup_agent_runtime(settings)

    assert rt.graph is not None
    assert rt.registry.get("spawn_sub_agent") is None


@pytest.mark.asyncio
async def test_memory_failure_tolerance(mock_build_graph):
    """If MemoryStore.initialize() fails, memory_store and summarizer are None."""
    settings = _make_settings(**{"memory.enabled": True})

    with patch("smartclaw.memory.store.MemoryStore", autospec=True) as ms_cls:
        ms_instance = AsyncMock()
        ms_instance.initialize = AsyncMock(side_effect=RuntimeError("db error"))
        ms_cls.return_value = ms_instance

        rt = await setup_agent_runtime(settings)

    assert rt.memory_store is None
    assert rt.summarizer is None


# -----------------------------------------------------------------------
# Task 1.3: close() tests
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_calls_resources():
    """close() calls close on memory_store and mcp_manager."""
    mock_mem = AsyncMock()
    mock_mcp = AsyncMock()

    rt = AgentRuntime(
        graph=MagicMock(),
        registry=ToolRegistry(),
        memory_store=mock_mem,
        summarizer=None,
        system_prompt="test",
        mcp_manager=mock_mcp,
        model_config=ModelConfig(),
    )

    await rt.close()

    mock_mem.close.assert_awaited_once()
    mock_mcp.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_with_none_resources():
    """close() works fine when memory_store and mcp_manager are None."""
    rt = AgentRuntime(
        graph=MagicMock(),
        registry=ToolRegistry(),
        memory_store=None,
        summarizer=None,
        system_prompt="test",
        mcp_manager=None,
        model_config=ModelConfig(),
    )

    await rt.close()


@pytest.mark.asyncio
async def test_close_exception_tolerance():
    """close() does not propagate exceptions from resources."""
    mock_mem = AsyncMock()
    mock_mem.close = AsyncMock(side_effect=RuntimeError("close failed"))
    mock_mcp = AsyncMock()
    mock_mcp.close = AsyncMock(side_effect=OSError("connection lost"))

    rt = AgentRuntime(
        graph=MagicMock(),
        registry=ToolRegistry(),
        memory_store=mock_mem,
        summarizer=None,
        system_prompt="test",
        mcp_manager=mock_mcp,
        model_config=ModelConfig(),
    )

    await rt.close()

    mock_mem.close.assert_awaited_once()
    mock_mcp.close.assert_awaited_once()


# -----------------------------------------------------------------------
# Task 1.3: tools / tool_names properties
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tools_property(mock_build_graph):
    """tools property returns registry.get_all()."""
    settings = _make_settings()
    rt = await setup_agent_runtime(settings)

    assert rt.tools == rt.registry.get_all()
    assert len(rt.tools) >= 8


@pytest.mark.asyncio
async def test_tool_names_sorted(mock_build_graph):
    """tool_names returns sorted list."""
    settings = _make_settings()
    rt = await setup_agent_runtime(settings)

    names = rt.tool_names
    assert names == sorted(names)
