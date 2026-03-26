"""AgentRuntime — unified agent initialization and resource management.

Provides:
- ``AgentRuntime`` — dataclass encapsulating all agent resources
- ``setup_agent_runtime`` — async factory that initializes the full agent stack
- ``SYSTEM_PROMPT`` — shared system prompt template
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from smartclaw.agent.graph import build_graph
from smartclaw.observability.logging import get_logger
from smartclaw.providers.config import ModelConfig
from smartclaw.tools.registry import ToolRegistry, create_system_tools

logger = get_logger("agent.runtime")

SYSTEM_PROMPT = """\
You are SmartClaw, a helpful AI assistant with access to tools.

Tool usage guidelines:
- Use `web_fetch` to fetch content from a specific URL.
- Use `web_search` to search the web. If it fails, fall back to `web_fetch`.
- Use `exec_command` to run shell commands on the local system.
- Use `read_file`, `write_file`, `edit_file`, `append_file`, `list_directory` for file operations.
- Use `spawn_sub_agent` to delegate complex subtasks to a child agent (if available).
- When a tool returns an error, try an alternative approach instead of giving up.
- Always respond in the same language as the user's input.
{skills_section}"""


@dataclass
class AgentRuntime:
    """Encapsulates all resources needed to run the SmartClaw agent."""

    graph: Any  # CompiledStateGraph
    registry: ToolRegistry
    memory_store: Any | None  # MemoryStore | None
    summarizer: Any | None  # AutoSummarizer | None
    system_prompt: str
    mcp_manager: Any | None  # MCPManager | None
    model_config: ModelConfig

    @property
    def tools(self) -> list:
        """Return all registered tools."""
        return self.registry.get_all()

    @property
    def tool_names(self) -> list[str]:
        """Return sorted list of registered tool names."""
        return self.registry.list_tools()

    async def close(self) -> None:
        """Release all resources. Never propagates exceptions."""
        if self.memory_store is not None:
            try:
                await self.memory_store.close()
            except Exception:
                logger.error("memory_store_close_failed", exc_info=True)
        if self.mcp_manager is not None:
            try:
                await self.mcp_manager.close()
            except Exception:
                logger.error("mcp_manager_close_failed", exc_info=True)


async def setup_agent_runtime(
    settings: Any,
    *,
    stream_callback: Callable[[str], None] | None = None,
) -> AgentRuntime:
    """Initialize the full agent stack from settings.

    Initialization order:
        1. System tools (ToolRegistry)
        2. MCP tools (if enabled)
        3. Skills (if enabled)
        4. Sub-Agent tool (if enabled)
        5. System prompt (with skills_section)
        6. MemoryStore (if enabled)
        7. AutoSummarizer (if enabled and memory available)
        8. Build LangGraph

    Each step is wrapped in try/except — logs warning and continues on failure.
    """
    workspace = os.path.expanduser(settings.agent_defaults.workspace)

    # 1. System tools — always created
    registry = create_system_tools(workspace)

    # 2. MCP tools
    mcp_manager = None
    if settings.mcp.enabled:
        try:
            from smartclaw.mcp.manager import MCPManager
            from smartclaw.tools.mcp_tool import create_mcp_tools

            mcp_manager = MCPManager()
            await mcp_manager.initialize(settings.mcp)
            mcp_tools = create_mcp_tools(mcp_manager)
            if mcp_tools:
                mcp_registry = ToolRegistry()
                mcp_registry.register_many(mcp_tools)
                registry.merge(mcp_registry)
            logger.info("mcp_initialized", server_count=len(mcp_manager.get_connected_servers()))
        except Exception as exc:
            logger.warning("mcp_init_failed", error=str(exc))
            mcp_manager = None

    # 3. Skills
    skills_summary = ""
    if settings.skills.enabled:
        try:
            from smartclaw.skills.loader import SkillsLoader
            from smartclaw.skills.registry import SkillsRegistry

            ws_dir = settings.skills.workspace_dir.replace("{workspace}", workspace)
            loader = SkillsLoader(workspace_dir=ws_dir, global_dir=settings.skills.global_dir)
            skills_reg = SkillsRegistry(loader=loader, tool_registry=registry)
            skills_reg.load_and_register_all()
            skills_summary = loader.build_skills_summary()
            if skills_summary:
                logger.info("skills_loaded", count=len(skills_reg.list_skills()))
        except Exception as exc:
            logger.warning("skills_load_failed", error=str(exc))

    # 4. Sub-Agent tool
    if settings.sub_agent.enabled:
        try:
            from smartclaw.agent.sub_agent import SpawnSubAgentTool

            sem = asyncio.Semaphore(settings.sub_agent.max_concurrent)
            tool = SpawnSubAgentTool(
                default_model=settings.model.primary,
                max_depth=settings.sub_agent.max_depth,
                timeout_seconds=settings.sub_agent.default_timeout_seconds,
                semaphore=sem,
                concurrency_timeout=float(settings.sub_agent.concurrency_timeout_seconds),
            )
            registry.register(tool)
        except Exception as exc:
            logger.warning("sub_agent_setup_failed", error=str(exc))

    # 5. System prompt
    system_prompt = SYSTEM_PROMPT.format(
        skills_section=f"\n\nAvailable skills:\n{skills_summary}" if skills_summary else ""
    )

    # 6. MemoryStore
    memory_store = None
    summarizer = None
    if settings.memory.enabled:
        try:
            from smartclaw.memory.store import MemoryStore

            memory_store = MemoryStore(db_path=settings.memory.db_path)
            await memory_store.initialize()
        except Exception as exc:
            logger.warning("memory_store_init_failed", error=str(exc))
            memory_store = None

    # 7. AutoSummarizer (only if memory_store succeeded)
    if settings.memory.enabled and memory_store is not None:
        try:
            from smartclaw.memory.summarizer import AutoSummarizer

            summarizer = AutoSummarizer(
                store=memory_store,
                model_config=settings.model,
                message_threshold=settings.memory.summary_threshold,
                keep_recent=settings.memory.keep_recent,
                token_percent_threshold=settings.memory.summarize_token_percent,
                context_window=settings.memory.context_window,
            )
        except Exception as exc:
            logger.warning("summarizer_init_failed", error=str(exc))
            summarizer = None

    # 8. Build graph
    graph = build_graph(settings.model, registry.get_all(), stream_callback)

    return AgentRuntime(
        graph=graph,
        registry=registry,
        memory_store=memory_store,
        summarizer=summarizer,
        system_prompt=system_prompt,
        mcp_manager=mcp_manager,
        model_config=settings.model,
    )
