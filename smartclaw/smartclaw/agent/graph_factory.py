"""GraphFactory — centralised construction of request-scoped agent graphs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.tools import BaseTool

from smartclaw.agent.graph import build_graph
from smartclaw.agent.loop_detector import LoopDetector
from smartclaw.agent.orchestrator_graph import build_orchestrator_graph
from smartclaw.providers.config import ModelConfig, parse_model_ref


class GraphFactory:
    """Create graphs with consistent runtime wiring.

    The factory ensures every graph build path inherits the same guard,
    pruning, summarisation, and loop-detection policy instead of letting
    request overrides or model switches drift from the default runtime path.
    """

    def __init__(
        self,
        *,
        stream_callback: Callable[[str], None] | None = None,
        tool_result_guard: Any | None = None,
        session_pruner: Any | None = None,
        summarizer: Any | None = None,
        loop_detector_factory: Callable[[], Any] | None = None,
        build_graph_fn: Callable[..., Any] = build_graph,
        build_orchestrator_graph_fn: Callable[..., Any] = build_orchestrator_graph,
        orchestrator_batch_size: int = 4,
        orchestrator_max_concurrent_workers: int = 4,
        orchestrator_max_phases: int = 8,
    ) -> None:
        self._stream_callback = stream_callback
        self._tool_result_guard = tool_result_guard
        self._session_pruner = session_pruner
        self._summarizer = summarizer
        self._loop_detector_factory = loop_detector_factory or LoopDetector
        self._build_graph = build_graph_fn
        self._build_orchestrator_graph = build_orchestrator_graph_fn
        self._orchestrator_batch_size = max(1, orchestrator_batch_size)
        self._orchestrator_max_concurrent_workers = max(1, orchestrator_max_concurrent_workers)
        self._orchestrator_max_phases = max(1, orchestrator_max_phases)

    def create(
        self,
        model_config: ModelConfig,
        tools: list[BaseTool],
        *,
        session_key: str | None = None,
        mode: str | None = None,
    ) -> Any:
        """Build a graph with consistent runtime dependencies."""
        loop_detector = self._loop_detector_factory() if self._loop_detector_factory else None
        if mode == "orchestrator":
            return self._build_orchestrator_graph(
                model_config,
                tools,
                self._stream_callback,
                tool_result_guard=self._tool_result_guard,
                session_pruner=self._session_pruner,
                summarizer=self._summarizer,
                session_key=session_key,
                loop_detector=loop_detector,
                max_batch_size=self._orchestrator_batch_size,
                max_concurrent_workers=self._orchestrator_max_concurrent_workers,
                max_phases=self._orchestrator_max_phases,
            )
        return self._build_graph(
            model_config,
            tools,
            self._stream_callback,
            tool_result_guard=self._tool_result_guard,
            session_pruner=self._session_pruner,
            summarizer=self._summarizer,
            session_key=session_key,
            loop_detector=loop_detector,
        )

    def create_with_primary(
        self,
        primary_model: str,
        base_model_config: ModelConfig,
        tools: list[BaseTool],
        *,
        session_key: str | None = None,
        mode: str | None = None,
    ) -> Any:
        """Clone *base_model_config* with a new primary model and build a graph."""
        parse_model_ref(primary_model)
        temp_config = ModelConfig(
            primary=primary_model,
            fallbacks=list(base_model_config.fallbacks),
            temperature=base_model_config.temperature,
            max_tokens=base_model_config.max_tokens,
            auth_profiles=list(base_model_config.auth_profiles),
            session_sticky=base_model_config.session_sticky,
            compaction_model=base_model_config.compaction_model,
            identifier_policy=base_model_config.identifier_policy,
            identifier_patterns=list(base_model_config.identifier_patterns),
        )
        return self.create(temp_config, tools, session_key=session_key, mode=mode)
