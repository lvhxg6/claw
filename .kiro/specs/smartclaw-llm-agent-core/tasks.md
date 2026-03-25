# Implementation Plan: SmartClaw LLM + Agent Core

## Overview

实现 SmartClaw 的 LLM 接入层（providers/）和 Agent 编排核心（agent/）。基于 LangChain ChatModel 接入多 LLM 提供商，通过 LangGraph ReAct StateGraph 实现 think-act-observe 循环，包含 Provider 工厂、Fallback 容错链、CooldownTracker、流式响应和多模态 Vision 支持。所有新模块在 `smartclaw/smartclaw/` 下创建，与 Spec 1 已有的 config/、observability/、credentials.py 集成。

## Tasks

- [x] 1. Add LLM dependencies and create module structure
  - [x] 1.1 Update `smartclaw/pyproject.toml` to add dependencies: `langgraph>=0.4`, `langchain-openai`, `langchain-anthropic`
    - Add to `[project.dependencies]` section
    - _Requirements: 1.1, 6.1_
  - [x] 1.2 Create package directories and `__init__.py` files
    - Create `smartclaw/smartclaw/providers/__init__.py`
    - Create `smartclaw/smartclaw/agent/__init__.py`
    - Create `smartclaw/tests/providers/__init__.py`
    - Create `smartclaw/tests/agent/__init__.py`
    - _Requirements: 1.1, 6.1_

- [x] 2. Implement Model Configuration (`smartclaw/smartclaw/providers/config.py`)
  - [x] 2.1 Create `ModelConfig` Pydantic Settings class and `parse_model_ref` function
    - `ModelConfig` with fields: `primary` (default "kimi/moonshot-v1-auto"), `fallbacks` (list), `temperature` (0.0), `max_tokens` (32768)
    - `parse_model_ref(raw: str) -> tuple[str, str]` to split "provider/model" format
    - _Requirements: 2.1, 2.2, 2.5, 2.6_
  - [x] 2.2 Extend `SmartClawSettings` in `smartclaw/smartclaw/config/settings.py` to nest `ModelConfig` as `model` field
    - Add `model: ModelConfig = Field(default_factory=ModelConfig)` to `SmartClawSettings`
    - Ensure env var override with `SMARTCLAW_MODEL__` prefix works
    - _Requirements: 2.3, 2.4_
  - [x] 2.3 Write unit tests for ModelConfig (`smartclaw/tests/providers/test_config.py`)
    - Test default values, fallbacks list, nested in SmartClawSettings
    - _Requirements: 2.2, 2.3, 2.5, 2.6_
  - [x] 2.4 Write property test for model reference round-trip parsing
    - **Property 3: Model reference round-trip parsing**
    - **Validates: Requirements 2.1**
  - [x] 2.5 Write property test for environment variable overrides
    - **Property 4: Environment variable overrides model configuration**
    - **Validates: Requirements 2.4**

- [x] 3. Implement Provider Factory (`smartclaw/smartclaw/providers/factory.py`)
  - [x] 3.1 Create `ProviderFactory` class with static `create()` method
    - Support "openai" → `ChatOpenAI`, "anthropic" → `ChatAnthropic`, "kimi" → `ChatOpenAI` with Kimi base_url
    - Accept `provider`, `model`, `api_key`, `api_base`, `temperature`, `max_tokens`, `streaming` parameters
    - Raise `ValueError` for unknown provider names
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 4.1_
  - [x] 3.2 Write unit tests for ProviderFactory (`smartclaw/tests/providers/test_factory.py`)
    - Test each provider creates correct ChatModel subclass
    - Test Kimi base_url configuration
    - Test API key reading from env/settings
    - Test streaming flag propagation
    - _Requirements: 1.3, 1.5, 1.6, 1.7, 4.1_
  - [x] 3.3 Write property test for factory creating correctly configured instances
    - **Property 1: Factory creates correctly configured ChatModel instances**
    - **Validates: Requirements 1.1, 1.4, 4.1**
  - [x] 3.4 Write property test for factory rejecting unknown providers
    - **Property 2: Factory rejects unknown provider names**
    - **Validates: Requirements 1.2**

- [x] 4. Checkpoint — Ensure config and factory tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement Fallback Chain and CooldownTracker (`smartclaw/smartclaw/providers/fallback.py`)
  - [x] 5.1 Create error classification types and `classify_error` function
    - `FailoverReason` enum: AUTH, RATE_LIMIT, TIMEOUT, FORMAT, OVERLOADED, UNKNOWN
    - `FailoverError` dataclass with `is_retriable()` method (FORMAT is non-retriable)
    - `FallbackAttempt` dataclass, `FallbackResult` dataclass, `FallbackExhaustedError` exception
    - `classify_error(error, provider, model) -> FailoverError` mapping HTTP status codes to reasons
    - _Requirements: 3.2, 3.3, 3.4, 3.8_
  - [x] 5.2 Create `CooldownTracker` class
    - Thread-safe per-provider cooldown tracking with `mark_failure()`, `mark_success()`, `is_available()`, `cooldown_remaining()`
    - Exponential backoff: standard `min(1h, 1min × 5^min(n-1, 3))`, billing `min(24h, 5h × 2^min(n-1, 10))`
    - Accept injectable `now_func` for testing
    - _Requirements: 3.5, 3.6, 3.7_
  - [x] 5.3 Create `FallbackChain` class with `execute()` async method
    - Try candidates in order, skip cooldown providers, record attempts
    - Non-retriable errors (FORMAT) abort immediately
    - Successful call resets cooldown via `CooldownTracker.mark_success()`
    - Raise `FallbackExhaustedError` when all candidates fail
    - Raise `ValueError` for empty candidate list
    - _Requirements: 3.1, 3.2, 3.3, 3.6, 3.8, 3.9_
  - [x] 5.4 Write unit tests for fallback and cooldown (`smartclaw/tests/providers/test_fallback.py`, `smartclaw/tests/providers/test_cooldown.py`)
    - Test empty candidate list, single candidate success, context cancellation
    - Test CooldownTracker initial availability, concurrent safety, multi-provider isolation
    - _Requirements: 3.5, 3.7, 3.9_
  - [x] 5.5 Write property test for fallback execution order and attempt recording
    - **Property 5: Fallback chain execution order and attempt recording**
    - **Validates: Requirements 3.1, 3.3, 3.6, 3.8**
  - [x] 5.6 Write property test for non-retriable error abort
    - **Property 6: Non-retriable errors abort fallback immediately**
    - **Validates: Requirements 3.2**
  - [x] 5.7 Write property test for error classification
    - **Property 7: Error classification maps to correct FailoverReason**
    - **Validates: Requirements 3.4**
  - [x] 5.8 Write property test for cooldown tracker round-trip
    - **Property 8: Cooldown tracker round-trip (failure then success resets)**
    - **Validates: Requirements 3.5, 3.7**

- [x] 6. Checkpoint — Ensure all provider tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement Agent State (`smartclaw/smartclaw/agent/state.py`)
  - [x] 7.1 Create `AgentState` TypedDict
    - Fields: `messages` (with `add_messages` reducer), `iteration`, `max_iterations`, `final_answer`, `error`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_
  - [x] 7.2 Write unit tests for AgentState (`smartclaw/tests/agent/test_state.py`)
    - Test field existence, TypedDict compatibility with LangGraph
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

- [x] 8. Implement Agent Nodes (`smartclaw/smartclaw/agent/nodes.py`)
  - [x] 8.1 Create `reasoning_node`, `action_node`, and `should_continue` functions
    - `reasoning_node`: invoke LLM via FallbackChain, return AIMessage, increment iteration
    - `action_node`: execute tool calls, return ToolMessage list
    - `should_continue`: route to "action" if tool_calls present, "end" otherwise
    - Handle max_iterations check, unhandled exceptions → store in `error` field
    - Use structlog logger for iteration logging
    - _Requirements: 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.9, 7.4_
  - [x] 8.2 Write unit tests for agent nodes (`smartclaw/tests/agent/test_nodes.py`)
    - Test reasoning_node with mock LLM, action_node tool execution, routing logic, exception handling
    - _Requirements: 6.2, 6.5, 6.6, 6.9_
  - [x] 8.3 Write property test for agent routing
    - **Property 10: Agent routing determined by tool_calls presence**
    - **Validates: Requirements 6.3, 6.4**
  - [x] 8.4 Write property test for action node producing matching ToolMessages
    - **Property 11: Action node produces matching ToolMessages**
    - **Validates: Requirements 6.5**

- [x] 9. Implement Agent Graph (`smartclaw/smartclaw/agent/graph.py`)
  - [x] 9.1 Create `build_graph`, `invoke`, and `create_vision_message` functions
    - `build_graph(model_config, tools, stream_callback)` → compiled LangGraph StateGraph
    - Wire reasoning_node → should_continue → action_node → reasoning_node loop
    - `invoke(graph, user_message, max_iterations)` → final AgentState
    - `create_vision_message(text, image_base64, media_type)` → HumanMessage with content list
    - Integrate ProviderFactory + FallbackChain internally
    - Support streaming via callback
    - _Requirements: 7.1, 7.2, 7.3, 7.5, 4.2, 4.3, 4.4, 4.5, 8.2, 8.7_
  - [x] 9.2 Write unit tests for agent graph (`smartclaw/tests/agent/test_graph.py`)
    - Test build_graph API, invoke API, streaming callback, non-streaming return, log integration
    - _Requirements: 7.1, 7.2, 7.4, 7.5, 4.2, 4.4, 4.5_
  - [x] 9.3 Write unit tests for vision message (`smartclaw/tests/agent/test_vision.py`)
    - Test create_vision_message output structure, mixed content in AgentState
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6_
  - [x] 9.4 Write property test for streaming callback accumulated text
    - **Property 9: Streaming callback receives accumulated text**
    - **Validates: Requirements 4.3**
  - [x] 9.5 Write property test for max iterations bounds
    - **Property 12: Max iterations bounds the agent loop**
    - **Validates: Requirements 6.7**
  - [x] 9.6 Write property test for invoke state initialization
    - **Property 13: Invoke initializes state correctly**
    - **Validates: Requirements 7.3**
  - [x] 9.7 Write property test for vision message construction
    - **Property 14: Vision message construction**
    - **Validates: Requirements 8.2, 8.7**

- [x] 10. Checkpoint — Ensure all agent tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Integration wiring and final validation
  - [x] 11.1 Update `smartclaw/config/config.example.yaml` with model configuration section
    - Add `model:` section with `primary`, `fallbacks`, `temperature`, `max_tokens` examples
    - _Requirements: 2.1, 2.2, 2.5_
  - [x] 11.2 Verify all modules import correctly and wire together end-to-end
    - Ensure `providers/__init__.py` exports ProviderFactory, ModelConfig, FallbackChain, CooldownTracker
    - Ensure `agent/__init__.py` exports build_graph, invoke, AgentState, create_vision_message
    - Run full test suite to confirm no import or integration issues
    - _Requirements: 7.5, 6.8_

- [x] 12. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- All tasks are required — no optional tasks in this plan
- All 14 correctness properties from the design are covered as required property-based test tasks
- Property tests use `hypothesis` with `@settings(max_examples=100)` minimum
- Property test annotations follow format: `# Feature: smartclaw-llm-agent-core, Property {N}: {title}`
- LLM calls are mocked in all tests using `unittest.mock.AsyncMock`
- CooldownTracker accepts injectable `now_func` for deterministic property testing
- Each task references specific requirements for traceability
