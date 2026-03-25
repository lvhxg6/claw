"""Agent graph construction, invocation, and vision message helpers.

Provides:

- ``build_graph`` — constructs a compiled LangGraph StateGraph for the ReAct loop.
- ``invoke`` — runs the agent graph with a user message and returns the final state.
- ``create_vision_message`` — constructs a multimodal HumanMessage (text + base64 image).
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph as _CompiledStateGraph

from smartclaw.agent.nodes import action_node, reasoning_node, should_continue
from smartclaw.agent.state import AgentState
from smartclaw.browser.actions import ActionExecutor
from smartclaw.browser.engine import BrowserConfig, BrowserEngine
from smartclaw.browser.page_parser import PageParser
from smartclaw.browser.screenshot import ScreenshotCapturer
from smartclaw.browser.session import SessionManager
from smartclaw.observability.logging import get_logger
from smartclaw.providers.config import ModelConfig, parse_model_ref
from smartclaw.providers.factory import ProviderFactory
from smartclaw.providers.fallback import (
    FallbackCandidate,
    FallbackChain,
)
from smartclaw.security.path_policy import PathPolicy
from smartclaw.tools.browser_tools import get_all_browser_tools

# Use Any-parameterized alias to satisfy mypy strict mode
type CompiledStateGraph = _CompiledStateGraph[Any, Any, Any, Any]

logger = get_logger("agent.graph")


# ---------------------------------------------------------------------------
# Internal: LLM call via FallbackChain
# ---------------------------------------------------------------------------


async def _llm_call_with_fallback(
    messages: list[BaseMessage],
    *,
    tools: list[BaseTool] | None = None,
    model_config: ModelConfig,
    fallback_chain: FallbackChain,
    stream_callback: Callable[[str], None] | None = None,
) -> AIMessage:
    """Call the LLM through the FallbackChain.

    Builds candidates from model_config, creates a ChatModel per candidate,
    optionally binds tools, and invokes via the fallback chain.
    """
    # Build candidate list: primary + fallbacks
    primary_provider, primary_model = parse_model_ref(model_config.primary)
    candidates = [FallbackCandidate(provider=primary_provider, model=primary_model)]
    for ref in model_config.fallbacks:
        p, m = parse_model_ref(ref)
        candidates.append(FallbackCandidate(provider=p, model=m))

    async def run(provider: str, model: str) -> AIMessage:
        llm = ProviderFactory.create(
            provider,
            model,
            temperature=model_config.temperature,
            max_tokens=model_config.max_tokens,
            streaming=stream_callback is not None,
        )
        if tools:
            llm = llm.bind_tools(tools)  # type: ignore[assignment]

        if stream_callback is not None:
            accumulated = ""
            async for chunk in llm.astream(messages):
                if isinstance(chunk.content, str) and chunk.content:
                    accumulated += chunk.content
                    stream_callback(accumulated)
            # Return the final accumulated message
            return AIMessage(content=accumulated)

        result = await llm.ainvoke(messages)
        if not isinstance(result, AIMessage):
            return AIMessage(content=str(result.content))
        return result

    fb_result = await fallback_chain.execute(candidates, run)
    return fb_result.response


# ---------------------------------------------------------------------------
# build_graph
# ---------------------------------------------------------------------------


def build_graph(
    model_config: ModelConfig,
    tools: list[BaseTool],
    stream_callback: Callable[[str], None] | None = None,
) -> CompiledStateGraph:
    """Build a compiled LangGraph StateGraph for the ReAct agent loop.

    Args:
        model_config: Model configuration (primary, fallbacks, temperature, etc.).
        tools: List of LangChain Tool objects to bind to the LLM.
        stream_callback: Optional callback invoked with accumulated text during streaming.

    Returns:
        A compiled StateGraph ready for invocation.
    """
    fallback_chain = FallbackChain()
    tools_by_name = {t.name: t for t in tools}

    # Create partial functions with injected dependencies
    llm_call = partial(
        _llm_call_with_fallback,
        model_config=model_config,
        fallback_chain=fallback_chain,
        stream_callback=stream_callback,
    )

    async def _reasoning(state: AgentState) -> dict[str, Any]:
        return await reasoning_node(state, llm_call=llm_call, tools=tools or None)

    async def _action(state: AgentState) -> dict[str, Any]:
        return await action_node(state, tools_by_name=tools_by_name)

    # Build the graph
    graph = StateGraph(AgentState)
    graph.add_node("reasoning", _reasoning)
    graph.add_node("action", _action)

    graph.set_entry_point("reasoning")
    graph.add_conditional_edges(
        "reasoning",
        should_continue,
        {"action": "action", "end": END},
    )
    graph.add_edge("action", "reasoning")

    return graph.compile()


# ---------------------------------------------------------------------------
# invoke
# ---------------------------------------------------------------------------


async def invoke(
    graph: CompiledStateGraph,
    user_message: str,
    *,
    max_iterations: int | None = None,
    system_prompt: str | None = None,
) -> AgentState:
    """Run the agent graph and return the final AgentState.

    Args:
        graph: Compiled LangGraph StateGraph.
        user_message: The user's input message.
        max_iterations: Optional override for max iterations (default 50).
        system_prompt: Optional system prompt prepended to messages.

    Returns:
        The final AgentState after the graph completes.
    """
    from langchain_core.messages import SystemMessage

    _max = max_iterations if max_iterations is not None else 50

    messages: list[BaseMessage] = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))
    messages.append(HumanMessage(content=user_message))

    initial_state: AgentState = {
        "messages": messages,
        "iteration": 0,
        "max_iterations": _max,
        "final_answer": None,
        "error": None,
    }

    logger.info("invoke start", user_message=user_message[:100], max_iterations=_max)
    result = await graph.ainvoke(initial_state)
    logger.info("invoke done", iteration=result.get("iteration", 0))
    return result  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# create_vision_message
# ---------------------------------------------------------------------------


def create_vision_message(
    text: str,
    image_base64: str,
    media_type: str = "image/png",
) -> HumanMessage:
    """Construct a multimodal HumanMessage with text and a base64 image.

    Args:
        text: The text content.
        image_base64: Base64-encoded image data.
        media_type: MIME type of the image (default "image/png").

    Returns:
        A HumanMessage with a content list containing a text block and an image_url block.
    """
    return HumanMessage(
        content=[
            {"type": "text", "text": text},
            {
                "type": "image_url",
                "image_url": {"url": f"data:{media_type};base64,{image_base64}"},
            },
        ]
    )


# ---------------------------------------------------------------------------
# create_browser_tools
# ---------------------------------------------------------------------------


def create_browser_tools(
    engine: BrowserEngine,
    session: SessionManager,
    *,
    browser_config: BrowserConfig | None = None,
) -> list[BaseTool]:
    """Instantiate browser components and return all browser LangChain Tools.

    This is the integration point for wiring browser tools into the Agent Graph.
    Call this function to produce browser tools, then pass them (along with any
    other tools) to ``build_graph``.

    Args:
        engine: An initialized BrowserEngine instance.
        session: A SessionManager wrapping the engine.
        browser_config: Optional BrowserConfig (uses engine's config if omitted).

    Returns:
        A list of BaseTool instances for browser automation.
    """
    parser = PageParser()
    actions = ActionExecutor()
    capturer = ScreenshotCapturer()

    return get_all_browser_tools(session, parser, actions, capturer)


# ---------------------------------------------------------------------------
# create_all_tools — merge browser + system tools
# ---------------------------------------------------------------------------


def create_all_tools(
    browser_tools: list[BaseTool],
    workspace: str,
    *,
    path_policy: PathPolicy | None = None,
    mcp_manager: Any | None = None,
) -> list[BaseTool]:
    """Merge browser tools with system tools (and optionally MCP tools) into a single list for build_graph.

    Args:
        browser_tools: List of browser BaseTool instances.
        workspace: Workspace directory path for system tools.
        path_policy: Optional PathPolicy for filesystem access control.
        mcp_manager: Optional MCPManager instance for MCP tool integration.

    Returns:
        Combined list of all BaseTool instances.
    """
    from smartclaw.tools.registry import ToolRegistry, create_system_tools

    system_registry = create_system_tools(workspace, path_policy)

    # Merge browser tools into the system registry
    browser_registry = ToolRegistry()
    browser_registry.register_many(browser_tools)
    system_registry.merge(browser_registry)

    # Merge MCP tools if manager is provided
    if mcp_manager is not None:
        from smartclaw.tools.mcp_tool import create_mcp_tools

        mcp_tools = create_mcp_tools(mcp_manager)
        if mcp_tools:
            mcp_registry = ToolRegistry()
            mcp_registry.register_many(mcp_tools)
            system_registry.merge(mcp_registry)

    return system_registry.get_all()
