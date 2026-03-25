"""Agent-level E2E tests — verify the Agent Graph correctly invokes tools.

These tests require a real LLM API key (OPENAI_API_KEY or ANTHROPIC_API_KEY).
Mark: ``pytest.mark.e2e`` — skipped by default unless ``--run-e2e`` is passed.

Usage:
    pytest tests/test_e2e_agent.py --run-e2e -v
"""

from __future__ import annotations

import os
import pathlib

import pytest

from smartclaw.agent.graph import build_graph, invoke
from smartclaw.providers.config import ModelConfig
from smartclaw.security.path_policy import PathPolicy
from smartclaw.tools.registry import create_system_tools

# ---------------------------------------------------------------------------
# Skip unless --run-e2e flag is provided
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.e2e


def _has_api_key() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))


def _get_model_config() -> ModelConfig:
    """Build a ModelConfig from available env keys."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return ModelConfig(
            primary="anthropic/claude-sonnet-4-20250514",
            fallbacks=[],
            temperature=0.0,
            max_tokens=1024,
        )
    return ModelConfig(
        primary="openai/gpt-4o-mini",
        fallbacks=[],
        temperature=0.0,
        max_tokens=1024,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a workspace directory with sample files."""
    (tmp_path / "hello.txt").write_text("Hello from SmartClaw E2E test!", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "numbers.txt").write_text("1\n2\n3\n4\n5\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def agent_graph(workspace: pathlib.Path) -> tuple:
    """Build agent graph with system tools."""
    if not _has_api_key():
        pytest.skip("No LLM API key available")

    policy = PathPolicy(
        allowed_patterns=[str(workspace.resolve()), f"{workspace.resolve()}/**"]
    )
    registry = create_system_tools(str(workspace), path_policy=policy)
    model_config = _get_model_config()
    graph = build_graph(model_config, tools=registry.get_all())
    return graph, workspace, registry


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAgentReadFile:
    """Agent uses read_file tool to read a file."""

    async def test_agent_reads_file(self, agent_graph: tuple) -> None:
        graph, workspace, _ = agent_graph

        result = await invoke(
            graph,
            f"Please read the file at {workspace}/hello.txt and tell me what it says. "
            "Reply with just the file content, nothing else.",
            max_iterations=5,
        )

        assert result.get("error") is None
        answer = result.get("final_answer", "")
        assert "Hello from SmartClaw E2E test" in answer


class TestAgentWriteFile:
    """Agent uses write_file tool to create a file."""

    async def test_agent_writes_file(self, agent_graph: tuple) -> None:
        graph, workspace, _ = agent_graph
        target = workspace / "agent_output.txt"

        result = await invoke(
            graph,
            f"Please write the text 'Agent was here' to the file {target}. "
            "Confirm when done.",
            max_iterations=5,
        )

        assert result.get("error") is None
        assert target.exists()
        assert "Agent was here" in target.read_text()


class TestAgentShell:
    """Agent uses exec_command to run shell commands."""

    async def test_agent_runs_echo(self, agent_graph: tuple) -> None:
        graph, workspace, _ = agent_graph

        result = await invoke(
            graph,
            "Run the shell command 'echo SMARTCLAW_E2E_OK' and tell me the output.",
            max_iterations=5,
        )

        assert result.get("error") is None
        answer = result.get("final_answer", "")
        assert "SMARTCLAW_E2E_OK" in answer


class TestAgentListDirectory:
    """Agent uses list_directory to explore workspace."""

    async def test_agent_lists_dir(self, agent_graph: tuple) -> None:
        graph, workspace, _ = agent_graph

        result = await invoke(
            graph,
            f"List the contents of the directory {workspace} and tell me what files are there.",
            max_iterations=5,
        )

        assert result.get("error") is None
        answer = result.get("final_answer", "")
        assert "hello.txt" in answer.lower() or "hello" in answer.lower()


class TestAgentEditFile:
    """Agent uses edit_file to modify a file."""

    async def test_agent_edits_file(self, agent_graph: tuple) -> None:
        graph, workspace, _ = agent_graph
        target = workspace / "editable.txt"
        target.write_text("color = red\n", encoding="utf-8")

        result = await invoke(
            graph,
            f"Edit the file {target}: replace 'red' with 'blue'. Confirm when done.",
            max_iterations=5,
        )

        assert result.get("error") is None
        assert "blue" in target.read_text()
        assert "red" not in target.read_text()


class TestAgentWorkflow:
    """Agent uses multiple tools in sequence."""

    async def test_agent_write_then_read(self, agent_graph: tuple) -> None:
        graph, workspace, _ = agent_graph
        target = workspace / "workflow.txt"

        result = await invoke(
            graph,
            f"First, write 'step1_done' to {target}. "
            f"Then read {target} and tell me what it contains.",
            max_iterations=8,
        )

        assert result.get("error") is None
        assert target.exists()
        answer = result.get("final_answer", "")
        assert "step1_done" in answer
