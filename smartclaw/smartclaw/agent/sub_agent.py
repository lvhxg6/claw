"""Sub-Agent module: EphemeralStore, SubAgentConfig, spawn_sub_agent, SpawnSubAgentTool.

Provides task delegation from a parent Agent to child sub-agents via
LangGraph SubGraph. Includes concurrency control (asyncio.Semaphore),
depth limiting, timeout enforcement, and ephemeral in-memory message storage.

Reference: PicoClaw ``pkg/agent/subturn.go``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import structlog
from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

logger = structlog.get_logger(component="agent.sub_agent")


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


class DepthLimitExceededError(Exception):
    """Raised when sub-agent spawn exceeds the maximum nesting depth."""


class ConcurrencyTimeoutError(Exception):
    """Raised when waiting for a concurrency slot times out."""


# ---------------------------------------------------------------------------
# SubAgentConfig
# ---------------------------------------------------------------------------


@dataclass
class SubAgentConfig:
    """Configuration for spawning a sub-agent.

    Attributes:
        task: Task description for the sub-agent.
        model: LLM model reference in 'provider/model' format.
        tools: Tools available to the sub-agent.
        system_prompt: Optional custom system prompt.
        max_iterations: Max reasoning-action loop iterations (default 25).
        timeout_seconds: Execution timeout in seconds (default 300).
        max_depth: Maximum nesting depth for recursive sub-agents (default 3).
    """

    task: str
    model: str
    tools: list[BaseTool] = field(default_factory=list)
    system_prompt: str | None = None
    max_iterations: int = 25
    timeout_seconds: int = 300
    max_depth: int = 3

    def validate(self) -> None:
        """Validate required fields. Raises ValueError if invalid."""
        if not self.task or not self.task.strip():
            raise ValueError("SubAgentConfig.task must be a non-empty string")
        if not self.model or not self.model.strip():
            raise ValueError("SubAgentConfig.model must be a non-empty string")


# ---------------------------------------------------------------------------
# EphemeralStore
# ---------------------------------------------------------------------------


class EphemeralStore:
    """In-memory message store for sub-agents.

    Auto-truncates at ``max_size`` to prevent memory accumulation
    in long-running sub-agents. Does NOT persist to disk.
    """

    def __init__(self, max_size: int = 50) -> None:
        self._max_size = max_size
        self._messages: list[BaseMessage] = []

    def add_message(self, message: BaseMessage) -> None:
        """Append a message, auto-truncating if max_size is exceeded."""
        self._messages.append(message)
        self._truncate_if_needed()

    def get_history(self) -> list[BaseMessage]:
        """Return a copy of the current message history."""
        return list(self._messages)

    def truncate(self, keep_last: int) -> None:
        """Keep only the last ``keep_last`` messages."""
        if keep_last <= 0:
            self._messages.clear()
        elif keep_last < len(self._messages):
            self._messages = self._messages[-keep_last:]

    def set_history(self, messages: list[BaseMessage]) -> None:
        """Replace the entire history, auto-truncating if needed."""
        self._messages = list(messages)
        self._truncate_if_needed()

    @property
    def max_size(self) -> int:
        """Return the configured max_size."""
        return self._max_size

    def _truncate_if_needed(self) -> None:
        """Internal: truncate to max_size if exceeded."""
        if len(self._messages) > self._max_size:
            self._messages = self._messages[-self._max_size :]



# ---------------------------------------------------------------------------
# spawn_sub_agent
# ---------------------------------------------------------------------------


async def spawn_sub_agent(
    config: SubAgentConfig,
    *,
    parent_depth: int = 0,
    semaphore: asyncio.Semaphore | None = None,
    concurrency_timeout: float = 30.0,
) -> str:
    """Spawn a sub-agent to execute a delegated task.

    Steps:
        1. Validate config
        2. Depth check: parent_depth >= config.max_depth → DepthLimitExceededError
        3. Semaphore acquire with timeout → ConcurrencyTimeoutError
        4. Build graph via build_graph with config.model and config.tools
        5. Run with asyncio.timeout(config.timeout_seconds)
        6. Return final_answer or error string

    Args:
        config: Sub-agent configuration.
        parent_depth: Current nesting depth of the parent agent.
        semaphore: Optional asyncio.Semaphore for concurrency control.
        concurrency_timeout: Seconds to wait for a semaphore slot.

    Returns:
        The sub-agent's final response string.

    Raises:
        DepthLimitExceededError: If parent_depth >= config.max_depth.
        ConcurrencyTimeoutError: If semaphore acquisition times out.
        ValueError: If config is invalid (missing task/model).
    """
    # 0. Validate config
    config.validate()

    # 1. Depth check
    if parent_depth >= config.max_depth:
        raise DepthLimitExceededError(
            f"Sub-agent depth limit exceeded: parent_depth={parent_depth}, "
            f"max_depth={config.max_depth}"
        )

    # 2. Semaphore acquire with timeout
    if semaphore is not None:
        try:
            async with asyncio.timeout(concurrency_timeout):
                await semaphore.acquire()
        except TimeoutError:
            raise ConcurrencyTimeoutError(
                f"Timed out waiting for concurrency slot after {concurrency_timeout}s"
            )

    try:
        # 3. Build graph (lazy imports to avoid circular deps)
        from smartclaw.agent import graph as _graph_mod
        from smartclaw.providers.config import ModelConfig, parse_model_ref

        provider, model_name = parse_model_ref(config.model)
        model_config = ModelConfig(
            primary=config.model,
            fallbacks=[],
            temperature=0.0,
        )

        logger.info(
            "spawn_sub_agent",
            task=config.task[:100],
            model=config.model,
            parent_depth=parent_depth,
            max_depth=config.max_depth,
        )

        graph = _graph_mod.build_graph(model_config, config.tools)

        # 4. Run with timeout
        try:
            async with asyncio.timeout(config.timeout_seconds):
                result = await _graph_mod.invoke(
                    graph,
                    config.task,
                    max_iterations=config.max_iterations,
                    system_prompt=config.system_prompt,
                )
        except TimeoutError:
            error_msg = (
                f"Sub-agent timed out after {config.timeout_seconds}s "
                f"executing task: {config.task[:100]}"
            )
            logger.error("sub_agent_timeout", error=error_msg)
            return f"Error: {error_msg}"

        # 5. Return final_answer or error
        final_answer = result.get("final_answer")
        if final_answer:
            logger.info("sub_agent_complete", answer_len=len(final_answer))
            return final_answer

        error = result.get("error")
        if error:
            logger.error("sub_agent_error", error=error)
            return f"Error: {error}"

        return "Sub-agent completed without producing a final answer."

    except (DepthLimitExceededError, ConcurrencyTimeoutError, ValueError):
        raise
    except Exception as exc:
        error_msg = f"Sub-agent execution failed: {exc}"
        logger.error("sub_agent_exception", error=str(exc), exc_info=True)
        return f"Error: {error_msg}"
    finally:
        if semaphore is not None:
            try:
                semaphore.release()
            except ValueError:
                pass  # Already released or never acquired


# ---------------------------------------------------------------------------
# SpawnSubAgentTool — LangChain BaseTool
# ---------------------------------------------------------------------------


class SpawnSubAgentInput(BaseModel):
    """Input schema for SpawnSubAgentTool."""

    task: str = Field(description="Clear task description for the sub-agent to execute.")
    model: str = Field(
        default="",
        description="Optional LLM model reference in 'provider/model' format.",
    )


class SpawnSubAgentTool(BaseTool):
    """LangChain BaseTool: delegate a subtask to a sub-agent.

    The parent Agent invokes this tool via tool calls to spawn a child
    sub-agent that executes the given task independently.
    """

    name: str = "spawn_sub_agent"
    description: str = (
        "Delegate a subtask to a sub-agent. "
        "Provide a clear task description. "
        "Optionally specify a model reference."
    )
    args_schema: type[BaseModel] = SpawnSubAgentInput

    # Configuration fields (set at construction time)
    default_model: str = "openai/gpt-4o"
    parent_depth: int = 0
    semaphore: asyncio.Semaphore | None = None
    concurrency_timeout: float = 30.0
    max_depth: int = 3
    max_iterations: int = 25
    timeout_seconds: int = 300
    available_tools: list[BaseTool] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}

    def _run(self, **kwargs: Any) -> str:
        raise NotImplementedError("Use async _arun")

    async def _arun(self, task: str, model: str = "", **kwargs: Any) -> str:
        """Spawn a sub-agent for the given task."""
        effective_model = model if model else self.default_model

        config = SubAgentConfig(
            task=task,
            model=effective_model,
            tools=self.available_tools,
            max_iterations=self.max_iterations,
            timeout_seconds=self.timeout_seconds,
            max_depth=self.max_depth,
        )

        try:
            result = await spawn_sub_agent(
                config,
                parent_depth=self.parent_depth,
                semaphore=self.semaphore,
                concurrency_timeout=self.concurrency_timeout,
            )
            return result
        except DepthLimitExceededError as exc:
            return f"Error: {exc}"
        except ConcurrencyTimeoutError as exc:
            return f"Error: {exc}"
        except Exception as exc:
            logger.error("spawn_sub_agent_tool_error", error=str(exc))
            return f"Error: {exc}"
