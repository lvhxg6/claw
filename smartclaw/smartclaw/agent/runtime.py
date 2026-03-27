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
from smartclaw.agent.graph_factory import GraphFactory
from smartclaw.agent.mode_router import ModeDecision, ModeRouter
from smartclaw.agent.prompt_composer import PromptComposer
from smartclaw.capabilities.governance import build_runtime_policy
from smartclaw.capabilities.models import CapabilityResolution
from smartclaw.capabilities.registry import CapabilityPackRegistry
from smartclaw.observability.logging import get_logger
from smartclaw.providers.config import ModelConfig
from smartclaw.providers.factory import ProviderFactory
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

Structured thinking process:
1. Understand the user's intent and context
2. Assess if clarification is needed before acting
3. Formulate an execution plan with clear steps
4. Select the most appropriate tool(s)
5. Execute, verify results, and iterate if needed

Clarification priority — use `ask_clarification` FIRST when:
- The request is ambiguous with multiple valid interpretations
- Critical parameters are missing for task execution
- The operation is destructive or irreversible (e.g. deleting files)

Tool decision tree:
- Information retrieval:
  - Known URL → `web_fetch`
  - General query → `web_search` (fallback: `web_fetch`)
- File operations:
  - Read → `read_file` / `list_directory`
  - Create/overwrite → `write_file`
  - Partial update → `edit_file` / `append_file`
- System commands → `exec_command`
- Complex subtask needing isolation → `spawn_sub_agent`
- Need user input → `ask_clarification`

Error recovery:
- Analyze the error message and root cause
- Try an alternative tool or adjusted parameters
- If repeated failures, explain the situation to the user and suggest next steps
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
    context_engine: Any | None = None  # ContextEngine | None
    graph_factory: GraphFactory | None = None
    prompt_composer: PromptComposer | None = None
    tool_result_guard: Any | None = None
    session_pruner: Any | None = None
    mode: str = "auto"
    mode_router: ModeRouter | None = None
    capability_registry: CapabilityPackRegistry | None = None
    skills_watcher: Any | None = None  # SkillsWatcher | None
    memory_loader: Any | None = None  # MemoryLoader | None
    bootstrap_loader: Any | None = None  # BootstrapLoader | None
    _active_requests: int = 0  # Track active requests for model switching
    _lock: asyncio.Lock | None = None  # Lock for thread-safe model switching

    def __post_init__(self) -> None:
        """Initialize the lock after dataclass creation."""
        object.__setattr__(self, "_lock", asyncio.Lock())

    @property
    def tools(self) -> list:
        """Return all registered tools."""
        return self.registry.get_all()

    @property
    def tool_names(self) -> list[str]:
        """Return sorted list of registered tool names."""
        return self.registry.list_tools()

    def resolve_mode(
        self,
        *,
        requested_mode: str | None = None,
        message: str = "",
        scenario_type: str | None = None,
        task_profile: str | None = None,
    ) -> ModeDecision:
        """Resolve request execution mode."""
        if self.mode_router is None:
            resolved = requested_mode if requested_mode in {"classic", "orchestrator"} else "classic"
            return ModeDecision(
                requested_mode=requested_mode,
                resolved_mode=resolved,
                reason="runtime_fallback",
                confidence=0.5,
            )
        return self.mode_router.resolve(
            requested_mode=requested_mode,
            message=message,
            scenario_type=scenario_type,
            task_profile=task_profile,
        )

    def create_graph(self, model_ref: str | None = None, *, mode: str | None = None) -> Any:
        """Create a request-scoped graph with consistent wiring."""
        return self.create_request_graph(model_ref=model_ref, mode=mode)

    def resolve_capability_pack(
        self,
        *,
        requested_name: str | None = None,
        scenario_type: str | None = None,
    ) -> CapabilityResolution:
        """Resolve the active capability pack for a request."""
        if self.capability_registry is None:
            return CapabilityResolution(
                requested_name=requested_name,
                resolved_name=None,
                reason="capabilities_disabled",
                pack=None,
            )
        return self.capability_registry.resolve(
            requested_name=requested_name,
            scenario_type=scenario_type,
        )

    def compose_system_prompt(self, *, capability_pack: str | None = None) -> str:
        """Compose a request-scoped system prompt."""
        if self.capability_registry is None or capability_pack is None:
            return self.system_prompt
        capability_context = self.capability_registry.render_context(capability_pack)
        if not capability_context:
            return self.system_prompt
        return f"{self.system_prompt}\n\n## Active Capability Pack\n{capability_context}"

    def build_capability_policy(self, *, capability_pack: str | None = None) -> dict[str, Any] | None:
        """Build runtime governance policy for the active capability pack."""
        if self.capability_registry is None or capability_pack is None:
            return None
        pack = self.capability_registry.get(capability_pack)
        return build_runtime_policy(pack)

    def create_request_graph(
        self,
        model_ref: str | None = None,
        *,
        mode: str | None = None,
        capability_pack: str | None = None,
    ) -> Any:
        """Create a request-scoped graph with mode and capability scoping."""
        resolved_mode = "orchestrator" if mode == "orchestrator" else "classic"
        tools = self.registry.get_all()
        if self.capability_registry is not None and capability_pack:
            tools = self.capability_registry.filter_tools(tools, pack_name=capability_pack)
        if self.graph_factory is None:
            if model_ref:
                from smartclaw.providers.config import parse_model_ref

                parse_model_ref(model_ref)
            return self.graph
        if model_ref:
            return self.graph_factory.create_with_primary(
                model_ref,
                self.model_config,
                tools,
                mode=resolved_mode,
            )
        return self.graph_factory.create(self.model_config, tools, mode=resolved_mode)

    @property
    def is_busy(self) -> bool:
        """Return True if there are active requests."""
        return self._active_requests > 0

    def increment_requests(self) -> None:
        """Increment active request counter."""
        object.__setattr__(self, "_active_requests", self._active_requests + 1)

    def decrement_requests(self) -> None:
        """Decrement active request counter."""
        object.__setattr__(self, "_active_requests", max(0, self._active_requests - 1))

    async def switch_model(self, new_primary: str) -> bool:
        """Switch the primary model. Returns False if busy.

        Args:
            new_primary: New primary model in 'provider/model' format.

        Returns:
            True if switch succeeded, False if busy with active requests.
        """
        if self._lock is None:
            object.__setattr__(self, "_lock", asyncio.Lock())

        async with self._lock:
            if self._active_requests > 0:
                logger.warning("model_switch_rejected", reason="active_requests", count=self._active_requests)
                return False

            # Validate model format
            from smartclaw.providers.config import parse_model_ref
            try:
                provider, model = parse_model_ref(new_primary)
                # Validate provider exists
                from smartclaw.providers.factory import ProviderFactory
                ProviderFactory.get_spec(provider)
            except ValueError as e:
                logger.warning("model_switch_rejected", reason="invalid_model", error=str(e))
                return False

            # Update model_config
            old_primary = self.model_config.primary
            object.__setattr__(self.model_config, "primary", new_primary)

            # Rebuild graph with new model config
            if self.graph_factory is not None:
                new_graph = self.graph_factory.create(self.model_config, self.registry.get_all())
            else:
                new_graph = build_graph(self.model_config, self.registry.get_all())
            object.__setattr__(self, "graph", new_graph)

            # Update summarizer if exists
            if self.summarizer is not None:
                object.__setattr__(self.summarizer, "model_config", self.model_config)

            logger.info("model_switched", old=old_primary, new=new_primary)
            return True

    def get_available_models(self) -> list[str]:
        """Return list of available models (primary + fallbacks)."""
        models = [self.model_config.primary]
        models.extend(self.model_config.fallbacks)
        return models

    async def close(self) -> None:
        """Release all resources. Never propagates exceptions."""
        # Stop SkillsWatcher first
        if self.skills_watcher is not None:
            try:
                self.skills_watcher.stop()
            except Exception:
                logger.error("skills_watcher_stop_failed", exc_info=True)
        if self.context_engine is not None:
            try:
                await self.context_engine.dispose()
            except Exception:
                logger.error("context_engine_dispose_failed", exc_info=True)
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
        3.1 SkillsWatcher (if hot_reload enabled)
        4. Sub-Agent tool (if enabled)
        5. BootstrapLoader (if enabled)
        6. MemoryLoader (if enabled)
        7. System prompt (with bootstrap, memory, skills)
        8. MemoryStore (if enabled)
        9. AutoSummarizer (if enabled and memory available)
        10. Build LangGraph

    Each step is wrapped in try/except — logs warning and continues on failure.
    """
    workspace = os.path.expanduser(settings.agent_defaults.workspace)

    # 0. Register custom ProviderSpecs from config (before any provider usage)
    if hasattr(settings, "providers") and settings.providers:
        ProviderFactory.register_specs(settings.providers)

    # 1. System tools — always created
    registry = create_system_tools(workspace)
    prompt_composer = PromptComposer()
    runtime_mode = getattr(getattr(settings, "orchestrator", None), "mode", "auto")
    default_mode = runtime_mode if runtime_mode in {"auto", "classic", "orchestrator"} else "auto"
    mode_router = ModeRouter(default_mode=default_mode)
    sub_agent_tool = None

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
    capability_summary = ""
    skills_watcher = None
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

            # 3.1 SkillsWatcher (hot reload)
            if getattr(settings.skills, "hot_reload", False):
                try:
                    from smartclaw.skills.watcher import SkillsWatcher

                    def on_skills_reload():
                        skills_reg.load_and_register_all()

                    skills_watcher = SkillsWatcher(
                        workspace_dir=ws_dir,
                        global_dir=settings.skills.global_dir,
                        debounce_ms=getattr(settings.skills, "debounce_ms", 250),
                        on_reload=on_skills_reload,
                        enabled=True,
                    )
                    skills_watcher.start()
                    logger.info("skills_watcher_started")
                except Exception as exc:
                    logger.warning("skills_watcher_init_failed", error=str(exc))
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
                parent_model_config=settings.model,
            )
            registry.register(tool)
            sub_agent_tool = tool
        except Exception as exc:
            logger.warning("sub_agent_setup_failed", error=str(exc))

    # 5. BootstrapLoader
    bootstrap_loader = None
    soul_content = ""
    user_content = ""
    tools_content = ""
    if getattr(settings, "bootstrap", None) and getattr(settings.bootstrap, "enabled", True):
        try:
            from smartclaw.bootstrap.loader import BootstrapLoader

            global_dir = getattr(settings.bootstrap, "global_dir", "~/.smartclaw")
            bootstrap_loader = BootstrapLoader(
                workspace_dir=workspace,
                global_dir=global_dir,
                enabled=True,
            )
            bootstrap_loader.load_all()
            soul_content = bootstrap_loader.get_soul_content()
            user_content = bootstrap_loader.get_user_content()
            tools_content = bootstrap_loader.get_tools_content()
            if soul_content or user_content or tools_content:
                logger.info(
                    "bootstrap_loaded",
                    has_soul=bool(soul_content),
                    has_user=bool(user_content),
                    has_tools=bool(tools_content),
                )
        except Exception as exc:
            logger.warning("bootstrap_load_failed", error=str(exc))

    # 6. MemoryLoader
    memory_loader = None
    memory_context = ""
    if settings.memory.enabled and getattr(settings.memory, "memory_file_enabled", True):
        try:
            from smartclaw.memory.loader import MemoryLoader

            memory_loader = MemoryLoader(
                workspace_dir=workspace,
                chunk_tokens=getattr(settings.memory, "chunk_tokens", 512),
                chunk_overlap=getattr(settings.memory, "chunk_overlap", 64),
                enabled=True,
            )
            memory_context = memory_loader.build_memory_context()
            if memory_context:
                logger.info("memory_loaded", context_length=len(memory_context))
        except Exception as exc:
            logger.warning("memory_load_failed", error=str(exc))

    # 7. System prompt
    capability_registry = None
    if getattr(settings, "capability_packs", None) and getattr(settings.capability_packs, "enabled", False):
        try:
            from smartclaw.capabilities.loader import CapabilityPackLoader
            from smartclaw.capabilities.registry import CapabilityPackRegistry

            capability_loader = CapabilityPackLoader(
                workspace_dir=settings.capability_packs.workspace_dir.replace("{workspace}", workspace),
                global_dir=settings.capability_packs.global_dir,
            )
            capability_registry = CapabilityPackRegistry(loader=capability_loader)
            capability_registry.load_all()
            capability_summary = capability_registry.build_summary()
            if capability_summary:
                logger.info("capability_packs_loaded", count=len(capability_registry.list_names()))
        except Exception as exc:
            logger.warning("capability_pack_load_failed", error=str(exc))
            capability_registry = None

    system_prompt = prompt_composer.compose(
        base_prompt=SYSTEM_PROMPT,
        skills_summary=skills_summary,
        capability_summary=capability_summary,
        soul_content=soul_content,
        user_content=user_content,
        tools_content=tools_content,
        memory_context=memory_context,
        mode=runtime_mode,
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

    tool_result_guard = None
    session_pruner = None
    if settings.memory.enabled:
        try:
            from smartclaw.memory.tool_result_guard import ToolResultGuard, ToolResultGuardConfig

            tool_result_guard = ToolResultGuard(
                ToolResultGuardConfig(
                    tool_result_max_chars=settings.memory.tool_result_max_chars,
                    head_chars=settings.memory.tool_result_head_chars,
                    tail_chars=settings.memory.tool_result_tail_chars,
                    tool_overrides=dict(settings.memory.tool_overrides),
                )
            )
        except Exception as exc:
            logger.warning("tool_result_guard_init_failed", error=str(exc))
            tool_result_guard = None

        if summarizer is not None:
            try:
                from smartclaw.memory.pruning import SessionPruner, SessionPrunerConfig

                session_pruner = SessionPruner(
                    SessionPrunerConfig(
                        soft_trim_threshold=settings.memory.soft_trim_threshold,
                        hard_clear_threshold=settings.memory.hard_clear_threshold,
                        keep_recent=settings.memory.pruner_keep_recent,
                        keep_head=settings.memory.pruner_keep_head,
                        tool_allow_list=list(settings.memory.tool_allow_list),
                        tool_deny_list=list(settings.memory.tool_deny_list),
                    ),
                    settings.memory.context_window,
                    summarizer.estimate_tokens,
                )
            except Exception as exc:
                logger.warning("session_pruner_init_failed", error=str(exc))
                session_pruner = None

    # 9. Create ContextEngine
    context_engine = None
    if settings.memory.enabled and memory_store is not None and summarizer is not None:
        try:
            from smartclaw.context_engine.registry import ContextEngineRegistry

            engine_name = getattr(settings, "context_engine", "legacy")
            context_engine = ContextEngineRegistry.create(
                engine_name,
                summarizer=summarizer,
                store=memory_store,
                pruner=session_pruner,
            )
            logger.info("context_engine_created", engine=engine_name)
        except Exception as exc:
            logger.warning("context_engine_init_failed", error=str(exc))
            context_engine = None

    graph_factory = GraphFactory(
        stream_callback=stream_callback,
        tool_result_guard=tool_result_guard,
        session_pruner=session_pruner,
        summarizer=summarizer,
        build_graph_fn=build_graph,
        orchestrator_batch_size=getattr(settings.orchestrator, "max_batch_size", 4),
        orchestrator_max_concurrent_workers=getattr(
            settings.orchestrator, "max_concurrent_workers", 4
        ),
        orchestrator_max_phases=getattr(settings.orchestrator, "max_phases", 8),
    )

    if sub_agent_tool is not None:
        try:
            sub_agent_tool.available_tools = [
                tool for tool in registry.get_all() if tool.name != sub_agent_tool.name
            ]
            sub_agent_tool.context_engine = context_engine
            sub_agent_tool.graph_factory = graph_factory
        except Exception as exc:
            logger.warning("sub_agent_runtime_binding_failed", error=str(exc))

    # 10. Build graph
    initial_mode = "orchestrator" if runtime_mode == "orchestrator" else "classic"
    graph = graph_factory.create(settings.model, registry.get_all(), mode=initial_mode)

    # 11. Restore CooldownTracker state from MemoryStore
    if settings.memory.enabled and memory_store is not None:
        try:
            from smartclaw.providers.fallback import CooldownTracker

            cooldown_tracker = CooldownTracker()
            await cooldown_tracker.restore_state(memory_store)
        except Exception as exc:
            logger.warning("cooldown_restore_failed", error=str(exc))

    return AgentRuntime(
        graph=graph,
        registry=registry,
        memory_store=memory_store,
        summarizer=summarizer,
        system_prompt=system_prompt,
        mcp_manager=mcp_manager,
        model_config=settings.model,
        context_engine=context_engine,
        graph_factory=graph_factory,
        prompt_composer=prompt_composer,
        tool_result_guard=tool_result_guard,
        session_pruner=session_pruner,
        mode=runtime_mode,
        mode_router=mode_router,
        capability_registry=capability_registry,
        skills_watcher=skills_watcher,
        memory_loader=memory_loader,
        bootstrap_loader=bootstrap_loader,
    )
