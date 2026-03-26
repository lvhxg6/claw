"""Agent graph nodes: reasoning, action, and routing.

Provides the three core functions wired into the LangGraph ReAct StateGraph:

- ``reasoning_node`` — calls the LLM (via FallbackChain) and returns an AIMessage.
- ``action_node`` — executes tool calls and returns ToolMessage results.
- ``should_continue`` — conditional router based on tool_calls presence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, ToolMessage

from smartclaw.agent.state import AgentState
from smartclaw.observability.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from langchain_core.tools import BaseTool

logger = get_logger("agent.nodes")


# ---------------------------------------------------------------------------
# Reasoning node
# ---------------------------------------------------------------------------


async def reasoning_node(
    state: AgentState,
    *,
    llm_call: Callable[..., Any],
    tools: list[BaseTool] | None = None,
) -> dict[str, Any]:
    """Reasoning node: invoke the LLM and return the AIMessage.

    Args:
        state: Current agent state.
        llm_call: Async callable that takes messages (and optionally tools)
            and returns an AIMessage.
        tools: Optional list of tools to bind to the LLM.

    Returns:
        Dict with ``messages`` (list containing the AIMessage) and
        incremented ``iteration``.
    """
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 50)

    # Check max iterations — if reached, force end
    if iteration >= max_iterations:
        logger.info("max_iterations reached", iteration=iteration, max_iterations=max_iterations)
        last_content = ""
        for msg in reversed(state.get("messages", [])):
            if isinstance(msg, AIMessage) and isinstance(msg.content, str):
                last_content = msg.content
                break
        return {
            "messages": [AIMessage(content=last_content or "Max iterations reached.")],
            "iteration": iteration,
            "final_answer": last_content or "Max iterations reached.",
        }

    try:
        logger.info("reasoning_node start", iteration=iteration)
        messages = state.get("messages", [])
        response: AIMessage = await llm_call(messages, tools=tools)
        logger.info("reasoning_node done", iteration=iteration, has_tool_calls=bool(response.tool_calls))

        result: dict[str, Any] = {
            "messages": [response],
            "iteration": iteration + 1,
        }

        # If no tool calls, this is the final answer
        if not response.tool_calls:
            content = response.content if isinstance(response.content, str) else str(response.content)
            result["final_answer"] = content

        return result

    except Exception as exc:
        error_msg = str(exc) or type(exc).__name__
        logger.error("reasoning_node error", iteration=iteration, error=error_msg, error_type=type(exc).__name__)
        return {
            "messages": [AIMessage(content=f"Error: {error_msg}")],
            "iteration": iteration + 1,
            "error": error_msg,
        }


# ---------------------------------------------------------------------------
# Action node
# ---------------------------------------------------------------------------


async def action_node(
    state: AgentState,
    *,
    tools_by_name: dict[str, BaseTool] | None = None,
) -> dict[str, Any]:
    """Action node: execute tool calls from the last AIMessage.

    Args:
        state: Current agent state.
        tools_by_name: Mapping of tool name → BaseTool instance.

    Returns:
        Dict with ``messages`` containing one ToolMessage per tool call.
    """
    tools_by_name = tools_by_name or {}
    messages = state.get("messages", [])

    # Find the last AIMessage with tool_calls
    last_ai: AIMessage | None = None
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.tool_calls:
            last_ai = msg
            break

    if last_ai is None:
        return {"messages": []}

    tool_messages: list[ToolMessage] = []
    for tool_call in last_ai.tool_calls:
        tool_name = tool_call["name"]
        tool_call_id = tool_call["id"]
        tool_args = tool_call.get("args", {})

        tool = tools_by_name.get(tool_name)
        if tool is None:
            tool_messages.append(
                ToolMessage(
                    content=f"Error: Tool '{tool_name}' not found.",
                    tool_call_id=tool_call_id,
                )
            )
            continue

        try:
            logger.info("action_node executing tool", tool=tool_name, tool_call_id=tool_call_id)
            result = await tool.ainvoke(tool_args)
            content = str(result) if not isinstance(result, str) else result
            tool_messages.append(
                ToolMessage(content=content, tool_call_id=tool_call_id)
            )
        except Exception as exc:
            logger.error("action_node tool error", tool=tool_name, error=str(exc))
            tool_messages.append(
                ToolMessage(
                    content=f"Error executing tool '{tool_name}': {exc}",
                    tool_call_id=tool_call_id,
                )
            )

    return {"messages": tool_messages}


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def should_continue(state: AgentState) -> str:
    """Conditional router: 'action' if last AIMessage has tool_calls, else 'end'.

    Also routes to 'end' if max_iterations reached, or if an error is set.
    """
    # Check for error
    if state.get("error"):
        return "end"

    # Check for final_answer
    if state.get("final_answer") is not None:
        return "end"

    messages = state.get("messages", [])
    if not messages:
        return "end"

    last_msg = messages[-1]
    if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
        return "action"

    return "end"
