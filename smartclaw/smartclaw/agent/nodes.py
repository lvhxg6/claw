"""Agent graph nodes: reasoning, action, and routing.

Provides the three core functions wired into the LangGraph ReAct StateGraph:

- ``reasoning_node`` — calls the LLM (via FallbackChain) and returns an AIMessage.
- ``action_node`` — executes tool calls and returns ToolMessage results.
- ``should_continue`` — conditional router based on tool_calls presence.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from smartclaw.agent.loop_detector import LoopDetector, LoopStatus
from smartclaw.agent.state import AgentState
from smartclaw.observability.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from langchain_core.tools import BaseTool

logger = get_logger("agent.nodes")


# ---------------------------------------------------------------------------
# Reasoning node
# ---------------------------------------------------------------------------


def _is_context_overflow_error(exc: Exception) -> bool:
    """Check if an exception looks like an HTTP 400 context overflow error.

    Returns True when the error message contains context/token/length
    keywords AND appears to be an HTTP 400 error.
    """
    msg = str(exc).lower()
    # Check for context overflow keywords
    overflow_keywords = ("context", "token", "length")
    has_keyword = any(kw in msg for kw in overflow_keywords)
    if not has_keyword:
        return False
    # Check for HTTP 400 indicators
    status = getattr(exc, "status_code", None)
    if status == 400:
        return True
    resp = getattr(exc, "response", None)
    if resp is not None:
        sc = getattr(resp, "status_code", None)
        if sc == 400:
            return True
    # Also check the message for "400" pattern
    if "400" in msg:
        return True
    return False


async def reasoning_node(
    state: AgentState,
    *,
    llm_call: Callable[..., Any],
    tools: list[BaseTool] | None = None,
    session_pruner: Any | None = None,
    summarizer: Any | None = None,
    session_key: str | None = None,
) -> dict[str, Any]:
    """Reasoning node: invoke the LLM and return the AIMessage.

    Args:
        state: Current agent state.
        llm_call: Async callable that takes messages (and optionally tools)
            and returns an AIMessage.
        tools: Optional list of tools to bind to the LLM.
        session_pruner: Optional SessionPruner instance for L2 session pruning.
        summarizer: Optional AutoSummarizer instance for context overflow recovery.
        session_key: Optional session key for force_compression on overflow.

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

        # L2: Apply SessionPruner before LLM invocation
        if session_pruner is not None:
            messages = session_pruner.prune(messages)

        # P2A: trigger llm:before hook before LLM call
        try:
            import smartclaw.hooks.registry as _hook_registry
            from smartclaw.hooks.events import LLMBeforeEvent
            _llm_before = LLMBeforeEvent(
                model="",
                message_count=len(messages),
                has_tools=tools is not None and len(tools) > 0,
            )
            await _hook_registry.trigger("llm:before", _llm_before)
        except Exception:
            pass

        _llm_start = time.monotonic()
        response: AIMessage = await llm_call(messages, tools=tools)
        _llm_duration_ms = (time.monotonic() - _llm_start) * 1000.0

        # P2A: trigger llm:after hook after LLM call (success)
        try:
            import smartclaw.hooks.registry as _hook_registry
            from smartclaw.hooks.events import LLMAfterEvent
            _llm_after = LLMAfterEvent(
                model="",
                has_tool_calls=bool(response.tool_calls),
                duration_ms=_llm_duration_ms,
                error=None,
            )
            await _hook_registry.trigger("llm:after", _llm_after)
        except Exception:
            pass

        logger.info("reasoning_node done", iteration=iteration, has_tool_calls=bool(response.tool_calls))

        # Accumulate token stats from usage_metadata
        existing_stats = state.get("token_stats") or {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        usage = getattr(response, "usage_metadata", None)
        if usage and isinstance(usage, dict):
            new_stats = {
                "prompt_tokens": existing_stats["prompt_tokens"] + usage.get("input_tokens", 0),
                "completion_tokens": existing_stats["completion_tokens"] + usage.get("output_tokens", 0),
                "total_tokens": existing_stats["total_tokens"] + usage.get("total_tokens", 0),
            }
        else:
            # Fallback: estimate tokens from messages
            try:
                from smartclaw.memory.summarizer import AutoSummarizer

                est = AutoSummarizer.estimate_tokens(None, messages)  # type: ignore[arg-type]
                resp_content = response.content if isinstance(response.content, str) else str(response.content)
                resp_est = len(resp_content) * 2 // 5
                new_stats = {
                    "prompt_tokens": existing_stats["prompt_tokens"] + est,
                    "completion_tokens": existing_stats["completion_tokens"] + resp_est,
                    "total_tokens": existing_stats["total_tokens"] + est + resp_est,
                }
            except Exception:
                new_stats = existing_stats

        result: dict[str, Any] = {
            "messages": [response],
            "iteration": iteration + 1,
            "token_stats": new_stats,
        }

        # If no tool calls, this is the final answer
        if not response.tool_calls:
            content = response.content if isinstance(response.content, str) else str(response.content)
            result["final_answer"] = content

        # Decision capture: record the LLM decision for observability
        try:
            from smartclaw.observability.decision_record import (
                DecisionRecord,
                DecisionType,
                _utc_now_iso,
            )
            from smartclaw.observability import decision_collector

            # Extract input_summary from the last message with content
            _input_summary = ""
            for _m in reversed(messages):
                if hasattr(_m, "content") and isinstance(_m.content, str):
                    _input_summary = _m.content[:512]
                    break

            # Extract reasoning: prefer thinking/reasoning_content from
            # additional_kwargs (GLM-5, Kimi K2.5 thinking mode), fall back
            # to response.content if not available.
            _reasoning = ""
            _additional = getattr(response, "additional_kwargs", {}) or {}
            _thinking = _additional.get("reasoning_content") or _additional.get("thinking")
            if _thinking and isinstance(_thinking, str):
                _reasoning = _thinking[:2048]
            elif isinstance(response.content, str):
                _reasoning = response.content[:2048]

            # Determine decision_type and tool_calls
            if response.tool_calls:
                _dt = DecisionType.TOOL_CALL
                _tc = [
                    {"tool_name": tc["name"], "tool_args": tc.get("args", {})}
                    for tc in response.tool_calls
                ]
            else:
                _dt = DecisionType.FINAL_ANSWER
                _tc = []

            _record = DecisionRecord(
                timestamp=_utc_now_iso(),
                iteration=iteration,
                decision_type=_dt,
                input_summary=_input_summary,
                reasoning=_reasoning,
                tool_calls=_tc,
                session_key=session_key or state.get("session_key"),
            )
            await decision_collector.add(_record)
        except Exception:
            pass  # Silent failure — must not disrupt agent main flow

        return result

    except Exception as exc:
        error_msg = str(exc) or type(exc).__name__
        logger.error("reasoning_node error", iteration=iteration, error=error_msg, error_type=type(exc).__name__)

        # Context overflow detection: catch HTTP 400 with context/token/length keywords
        _resolved_session_key = session_key or state.get("session_key")
        if (
            summarizer is not None
            and _resolved_session_key
            and _is_context_overflow_error(exc)
        ):
            logger.warning(
                "context_overflow_detected",
                iteration=iteration,
                session_key=_resolved_session_key,
            )
            try:
                compressed_messages = await summarizer.force_compression(
                    _resolved_session_key, messages
                )
                # Retry LLM call once with compressed messages
                if session_pruner is not None:
                    compressed_messages = session_pruner.prune(compressed_messages)
                retry_response: AIMessage = await llm_call(compressed_messages, tools=tools)
                logger.info(
                    "context_overflow_retry_succeeded",
                    iteration=iteration,
                )
                retry_result: dict[str, Any] = {
                    "messages": [retry_response],
                    "iteration": iteration + 1,
                }
                if not retry_response.tool_calls:
                    content = retry_response.content if isinstance(retry_response.content, str) else str(retry_response.content)
                    retry_result["final_answer"] = content
                return retry_result
            except Exception as retry_exc:
                logger.error(
                    "context_overflow_retry_failed",
                    iteration=iteration,
                    error=str(retry_exc),
                )

        # P2A: trigger llm:after hook on error
        try:
            import smartclaw.hooks.registry as _hook_registry
            from smartclaw.hooks.events import LLMAfterEvent
            _llm_after_err = LLMAfterEvent(
                model="",
                has_tool_calls=False,
                duration_ms=0.0,
                error=error_msg,
            )
            await _hook_registry.trigger("llm:after", _llm_after_err)
        except Exception:
            pass

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
    tool_result_guard: Any | None = None,
    loop_detector: LoopDetector | None = None,
) -> dict[str, Any]:
    """Action node: execute tool calls from the last AIMessage.

    Args:
        state: Current agent state.
        tools_by_name: Mapping of tool name → BaseTool instance.
        tool_result_guard: Optional ToolResultGuard instance for L1 truncation.
        loop_detector: Optional LoopDetector instance for loop detection.

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

    tool_messages: list[ToolMessage | HumanMessage] = []
    clarification_request = None
    for tool_call in last_ai.tool_calls:
        tool_name = tool_call["name"]
        tool_call_id = tool_call["id"]
        tool_args = tool_call.get("args", {})

        # Intercept ask_clarification: extract request, emit ToolMessage, skip remaining calls
        if tool_name == "ask_clarification":
            question = tool_args.get("question", "")
            options = tool_args.get("options")
            clarification_request = {"question": question, "options": options}
            tool_messages.append(
                ToolMessage(
                    content=f"Clarification requested: {question}",
                    tool_call_id=tool_call_id,
                )
            )
            logger.info("action_node intercepted ask_clarification", question=question)
            break

        tool = tools_by_name.get(tool_name)
        if tool is None:
            tool_messages.append(
                ToolMessage(
                    content=f"Error: Tool '{tool_name}' not found.",
                    tool_call_id=tool_call_id,
                )
            )
            continue

        # P2A: trigger tool:before hook
        try:
            import smartclaw.hooks.registry as _hook_registry
            from smartclaw.hooks.events import ToolBeforeEvent
            _tool_before = ToolBeforeEvent(
                tool_name=tool_name,
                tool_args=tool_args,
                tool_call_id=tool_call_id,
            )
            await _hook_registry.trigger("tool:before", _tool_before)
        except Exception:
            pass

        _tool_start = time.monotonic()
        try:
            logger.info("action_node executing tool", tool=tool_name, tool_call_id=tool_call_id)
            result = await tool.ainvoke(tool_args)
            content = str(result) if not isinstance(result, str) else result
            _tool_duration_ms = (time.monotonic() - _tool_start) * 1000.0

            # P2A: trigger tool:after hook (success) and emit tool.executed
            try:
                import smartclaw.hooks.registry as _hook_registry
                from smartclaw.hooks.events import ToolAfterEvent
                _tool_after = ToolAfterEvent(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_call_id=tool_call_id,
                    result=content[:2048],
                    duration_ms=_tool_duration_ms,
                    error=None,
                )
                await _hook_registry.trigger("tool:after", _tool_after)
            except Exception:
                pass
            try:
                from smartclaw.observability import diagnostic_bus as _dbus
                await _dbus.emit("tool.executed", {
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "duration_ms": _tool_duration_ms,
                    "error": None,
                })
            except Exception:
                pass

            # L1: Apply ToolResultGuard truncation before creating ToolMessage
            if tool_result_guard is not None:
                content = tool_result_guard.cap_tool_result(content, tool_name)

            tool_messages.append(
                ToolMessage(content=content, tool_call_id=tool_call_id)
            )

            # Loop detection: record tool call after successful execution
            if loop_detector is not None:
                loop_status = loop_detector.record(tool_name, tool_args)
                if loop_status == LoopStatus.STOP:
                    error_msg = (
                        f"Loop detected: tool '{tool_name}' has been called "
                        f"with the same arguments too many times. "
                        f"Stopping to prevent infinite loop."
                    )
                    logger.warning("action_node loop_stop", tool=tool_name)
                    result_dict: dict[str, Any] = {
                        "messages": tool_messages,
                        "error": error_msg,
                    }
                    if clarification_request is not None:
                        result_dict["clarification_request"] = clarification_request
                    return result_dict
                elif loop_status == LoopStatus.WARN:
                    logger.warning("action_node loop_warn", tool=tool_name)
                    tool_messages.append(
                        HumanMessage(
                            content=(
                                "[System Warning] Repetitive behavior detected: "
                                f"tool '{tool_name}' has been called with the same "
                                "arguments multiple times. Please try a different "
                                "approach or different parameters to make progress."
                            )
                        )
                    )
        except Exception as exc:
            _tool_duration_ms = (time.monotonic() - _tool_start) * 1000.0
            error_msg = str(exc)
            logger.error("action_node tool error", tool=tool_name, error=error_msg)

            # P2A: trigger tool:after hook (error) and emit tool.executed
            try:
                import smartclaw.hooks.registry as _hook_registry
                from smartclaw.hooks.events import ToolAfterEvent
                _tool_after_err = ToolAfterEvent(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_call_id=tool_call_id,
                    result="",
                    duration_ms=_tool_duration_ms,
                    error=error_msg,
                )
                await _hook_registry.trigger("tool:after", _tool_after_err)
            except Exception:
                pass
            try:
                from smartclaw.observability import diagnostic_bus as _dbus
                await _dbus.emit("tool.executed", {
                    "tool_name": tool_name,
                    "tool_call_id": tool_call_id,
                    "duration_ms": _tool_duration_ms,
                    "error": error_msg,
                })
            except Exception:
                pass

            tool_messages.append(
                ToolMessage(
                    content=f"Error executing tool '{tool_name}': {exc}",
                    tool_call_id=tool_call_id,
                )
            )

    result: dict[str, Any] = {"messages": tool_messages}
    if clarification_request is not None:
        result["clarification_request"] = clarification_request
    return result


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

    # Check for clarification_request
    if state.get("clarification_request") is not None:
        return "end"

    messages = state.get("messages", [])
    if not messages:
        return "end"

    last_msg = messages[-1]
    if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
        return "action"

    return "end"
