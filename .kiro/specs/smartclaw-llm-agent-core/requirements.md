# Requirements Document

## Introduction

SmartClaw LLM + Agent Core（Spec 2）定义了 SmartClaw 浏览器自动化 Agent 的 LLM 接入层和 Agent 编排核心。本模块通过 LangChain ChatModel 接入多个 LLM 提供商（默认 Kimi 2.5，备选 GPT-4o / Claude Sonnet 4），通过 LangGraph ReAct StateGraph 实现 think-act-observe 循环，并提供 Provider 工厂模式、Fallback 容错机制和流式响应支持。

本模块与 Spec 1（项目骨架）中已实现的配置系统（Pydantic Settings + YAML）和日志系统（structlog）集成。

参考架构：PicoClaw `pkg/providers/`（Provider 工厂 + Fallback）、PicoClaw `pkg/agent/loop.go`（ReAct 主循环）。

## Glossary

- **Provider_Factory**: LLM 提供商工厂，根据提供商名称创建对应的 LangChain ChatModel 实例
- **Fallback_Chain**: 容错链，当主模型调用失败时按优先级依次尝试备选模型
- **Cooldown_Tracker**: 冷却追踪器，记录失败提供商的冷却状态，避免短时间内重复请求已知故障的提供商
- **Agent_Graph**: LangGraph ReAct StateGraph，实现 think-act-observe 循环的有向图
- **Agent_State**: Agent 运行时状态，包含消息历史、工具调用结果、迭代计数等
- **Reasoning_Node**: 推理节点，调用 LLM 生成下一步行动决策
- **Action_Node**: 行动节点，执行 LLM 决定的工具调用
- **Observation_Node**: 观察节点，收集工具执行结果并反馈给 LLM
- **Model_Config**: 模型配置，定义主模型、备选模型列表、API 密钥引用和模型参数
- **Failover_Reason**: 故障分类枚举，标识失败原因（认证失败、速率限制、超时、格式错误等）
- **SmartClaw_Settings**: Spec 1 中已实现的 Pydantic Settings 根配置对象
- **Stream_Callback**: 流式回调函数，接收 LLM 生成的增量 token 文本

## Requirements

### Requirement 1: Provider Factory — 创建 LLM 提供商实例

**User Story:** As a developer, I want a factory that creates LLM provider instances by name, so that I can switch between different LLM providers without changing business logic.

#### Acceptance Criteria

1. WHEN a valid provider name ("openai", "anthropic", "kimi") is provided, THE Provider_Factory SHALL return a configured LangChain ChatModel instance for that provider
2. WHEN an unknown provider name is provided, THE Provider_Factory SHALL raise a `ValueError` with the unsupported provider name included in the error message
3. THE Provider_Factory SHALL read API keys from environment variables or the SmartClaw_Settings credential configuration, not from hardcoded values
4. THE Provider_Factory SHALL accept optional model parameters (temperature, max_tokens) and pass them to the created ChatModel instance
5. WHEN the "kimi" provider is requested, THE Provider_Factory SHALL create a `ChatOpenAI` instance configured with the Kimi 2.5 API base URL
6. WHEN the "openai" provider is requested, THE Provider_Factory SHALL create a `ChatOpenAI` instance configured for the OpenAI API
7. WHEN the "anthropic" provider is requested, THE Provider_Factory SHALL create a `ChatAnthropic` instance configured for the Anthropic API

### Requirement 2: Model Configuration — 模型配置集成

**User Story:** As a developer, I want model configuration integrated into the existing YAML + Pydantic Settings system, so that I can configure LLM providers and models through config files and environment variables.

#### Acceptance Criteria

1. THE Model_Config SHALL define a `primary` field specifying the default model in "provider/model" format (e.g., "kimi/moonshot-v1-auto")
2. THE Model_Config SHALL define a `fallbacks` list field specifying backup models in priority order
3. THE Model_Config SHALL be nested under the existing SmartClaw_Settings as a `model` section
4. WHEN environment variables with the `SMARTCLAW_MODEL__` prefix are set, THE SmartClaw_Settings SHALL override the corresponding model configuration fields
5. THE Model_Config SHALL define default values: primary as "kimi/moonshot-v1-auto", fallbacks as ["openai/gpt-4o", "anthropic/claude-sonnet-4-20250514"]
6. THE Model_Config SHALL include a `temperature` field (default 0.0) and a `max_tokens` field (default 32768)

### Requirement 3: Fallback Chain — 模型容错机制

**User Story:** As a developer, I want automatic fallback to backup models when the primary model fails, so that the agent remains operational during provider outages.

#### Acceptance Criteria

1. WHEN the primary model call fails with a retriable error, THE Fallback_Chain SHALL attempt the next candidate in the fallback list
2. WHEN a model call fails with a non-retriable error (format error, invalid request), THE Fallback_Chain SHALL abort immediately and return the error
3. WHEN all candidates in the fallback list have been tried and failed, THE Fallback_Chain SHALL raise a `FallbackExhaustedError` containing all attempt details
4. THE Fallback_Chain SHALL classify errors into Failover_Reason categories: auth, rate_limit, timeout, format, overloaded, unknown
5. THE Cooldown_Tracker SHALL mark a failed provider as unavailable for a cooldown period after repeated failures
6. WHEN a provider is in cooldown, THE Fallback_Chain SHALL skip that provider and log the skip reason
7. WHEN a provider call succeeds, THE Cooldown_Tracker SHALL reset the cooldown state for that provider
8. THE Fallback_Chain SHALL record each attempt (provider, model, error, duration, skipped status) and include the attempt list in the result
9. WHEN no candidates are configured, THE Fallback_Chain SHALL raise a `ValueError` indicating no candidates are available

### Requirement 4: Streaming Response Support

**User Story:** As a developer, I want streaming LLM responses, so that the agent can display incremental output to users in real time.

#### Acceptance Criteria

1. WHEN streaming mode is requested, THE Provider_Factory SHALL create a ChatModel instance with streaming enabled
2. WHEN the LLM generates tokens in streaming mode, THE Agent_Graph SHALL invoke the Stream_Callback with each accumulated text chunk
3. THE Stream_Callback SHALL receive the accumulated text (not individual deltas) to simplify downstream consumption
4. WHEN streaming mode is not requested, THE Agent_Graph SHALL return the complete response after LLM generation finishes
5. IF a streaming connection is interrupted mid-response, THEN THE Agent_Graph SHALL treat the partial response as a failed attempt and trigger fallback

### Requirement 5: Agent State Definition

**User Story:** As a developer, I want a well-defined agent state schema, so that the LangGraph StateGraph can track conversation history, tool calls, and iteration progress.

#### Acceptance Criteria

1. THE Agent_State SHALL contain a `messages` field storing the full conversation history as a list of LangChain message objects
2. THE Agent_State SHALL contain an `iteration` field tracking the current think-act-observe loop count
3. THE Agent_State SHALL contain a `max_iterations` field defining the upper bound for loop iterations (default from SmartClaw_Settings agent_defaults.max_tool_iterations)
4. THE Agent_State SHALL contain a `final_answer` field storing the agent's final text response when the loop completes
5. THE Agent_State SHALL contain an `error` field storing error information when the agent loop terminates abnormally
6. THE Agent_State SHALL be implemented as a TypedDict compatible with LangGraph StateGraph state schema

### Requirement 6: Agent Graph — ReAct StateGraph 编排

**User Story:** As a developer, I want a LangGraph ReAct StateGraph that orchestrates the think-act-observe loop, so that the agent can reason about tasks, invoke tools, and observe results iteratively.

#### Acceptance Criteria

1. THE Agent_Graph SHALL define three nodes: Reasoning_Node, Action_Node, and Observation_Node
2. THE Reasoning_Node SHALL invoke the LLM (via Fallback_Chain) with the current message history and available tool definitions
3. WHEN the LLM response contains tool calls, THE Agent_Graph SHALL route to the Action_Node
4. WHEN the LLM response contains no tool calls (final answer), THE Agent_Graph SHALL route to the END node and store the response in Agent_State.final_answer
5. THE Action_Node SHALL execute each tool call and append the results as tool messages to Agent_State.messages
6. AFTER the Action_Node completes, THE Agent_Graph SHALL route back to the Reasoning_Node for the next iteration
7. WHEN Agent_State.iteration reaches Agent_State.max_iterations, THE Agent_Graph SHALL stop the loop and return the last LLM response as the final answer
8. THE Agent_Graph SHALL accept a list of LangChain Tool objects at construction time for binding to the LLM
9. IF an unhandled exception occurs in any node, THEN THE Agent_Graph SHALL store the error in Agent_State.error and route to the END node

### Requirement 7: Agent Graph Construction and Invocation

**User Story:** As a developer, I want a clean API to build and run the agent graph, so that I can integrate the agent core into the SmartClaw application.

#### Acceptance Criteria

1. THE Agent_Graph SHALL provide a `build_graph` function that accepts Model_Config, a list of tools, and optional Stream_Callback, and returns a compiled LangGraph StateGraph
2. THE Agent_Graph SHALL provide an `invoke` async method that accepts a user message string and returns the final Agent_State
3. WHEN `invoke` is called, THE Agent_Graph SHALL initialize Agent_State with the user message appended to messages and iteration set to 0
4. THE Agent_Graph SHALL use the existing structlog logger (from `smartclaw.observability.logging`) to log each iteration's reasoning, action, and observation steps
5. THE `build_graph` function SHALL use Provider_Factory and Fallback_Chain internally, requiring only Model_Config as input for LLM setup

### Requirement 8: Multimodal Vision Support

**User Story:** As a developer, I want the LLM integration to support multimodal input (text + images), so that the agent can understand browser screenshots and visual page content for browser automation tasks.

#### Acceptance Criteria

1. THE Provider_Factory SHALL create ChatModel instances that support multimodal input (text + image) when the provider supports Vision capabilities
2. WHEN a message contains image content (base64 encoded or URL), THE Agent_Graph SHALL pass the image as part of the LangChain HumanMessage content list alongside text
3. THE Agent_State SHALL support messages containing mixed content types (text blocks and image blocks)
4. WHEN the "kimi" provider is used, THE Provider_Factory SHALL verify that the configured model supports Vision and log a warning if it does not
5. WHEN the "openai" provider is used with a Vision-capable model (e.g., gpt-4o), THE Provider_Factory SHALL enable image input support
6. WHEN the "anthropic" provider is used with a Vision-capable model (e.g., claude-sonnet-4), THE Provider_Factory SHALL enable image input support
7. THE Agent_Graph SHALL provide a helper function `create_vision_message(text: str, image_base64: str, media_type: str) -> HumanMessage` to construct multimodal messages

