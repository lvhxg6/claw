# Requirements Document

## Introduction

SmartClaw P1 增强能力是 SmartClaw AI Agent 项目的第二阶段开发，在 P0 核心 MVP（LLM 集成、Agent ReAct 循环、浏览器引擎、工具系统、MCP 协议、安全策略、配置管理）全部完成的基础上，新增 6 个增强模块：

1. **记忆存储（Memory Store）** — 基于 SQLite 的对话记忆持久化，支持跨会话历史存取
2. **自动摘要（Auto Summary）** — LLM 驱动的长对话摘要压缩，降低 Token 消耗
3. **技能加载器（Skills Loader）** — YAML 技能定义文件的发现与动态加载
4. **技能注册表（Skills Registry）** — 技能的注册、管理与 ToolRegistry 集成
5. **子 Agent（Sub-Agent）** — LangGraph SubGraph 任务委托，父 Agent 可派生子 Agent 执行子任务
6. **多 Agent 协同（Multi-Agent Coordination）** — LangGraph Multi-Agent 编排，多个 Agent 协作完成复杂任务

参考架构：PicoClaw `pkg/memory/`、`pkg/skills/`、`pkg/agent/subturn.go`；OpenClaw `subagent-*.ts`。

技术栈：Python 3.12+、LangGraph >= 0.4、LangChain、SQLite（LangGraph SqliteSaver）、YAML、asyncio、structlog、pytest + hypothesis。

## Glossary

- **Memory_Store**: 对话记忆持久化存储模块，基于 SQLite 实现，负责保存和检索跨会话的对话历史
- **Session_Key**: 会话标识符，用于区分不同对话会话的唯一字符串
- **Conversation_Summary**: 对话摘要，由 LLM 生成的长对话压缩文本，用于减少上下文 Token 消耗
- **Auto_Summarizer**: 自动摘要模块，监控对话长度并在超过阈值时触发 LLM 摘要压缩
- **Token_Threshold**: Token 阈值，触发自动摘要的对话消息数量上限
- **Skills_Loader**: 技能加载器，负责从文件系统发现和加载 YAML 格式的技能定义文件
- **Skill_Definition**: 技能定义，YAML 格式的文件，描述技能的名称、描述、参数和入口点
- **Skills_Registry**: 技能注册表，管理已加载技能的注册、查询和生命周期
- **ToolRegistry**: P0 已实现的工具注册中心（`smartclaw/tools/registry.py`），管理 LangChain BaseTool 实例
- **Sub_Agent**: 子 Agent，由父 Agent 派生的独立 Agent 实例，通过 LangGraph SubGraph 执行特定子任务
- **Sub_Agent_Config**: 子 Agent 配置，定义子 Agent 的模型、工具集、系统提示词和执行约束
- **Multi_Agent_Coordinator**: 多 Agent 协调器，编排多个 Agent 协作完成复杂任务的调度模块
- **Agent_Role**: Agent 角色定义，描述多 Agent 协同中每个 Agent 的职责和能力范围
- **AgentState**: P0 已实现的 LangGraph 状态 TypedDict（`smartclaw/agent/state.py`），包含 messages、iteration 等字段
- **SmartClawSettings**: P0 已实现的 Pydantic Settings 根配置（`smartclaw/config/settings.py`）

## Requirements

### Requirement 1: Memory Store — 对话记忆持久化存储

**User Story:** As an AI Agent, I want to persist conversation history across sessions using SQLite, so that I can recall previous interactions and maintain context continuity.

#### Acceptance Criteria

1. THE Memory_Store SHALL provide an `add_message` async method that accepts a Session_Key, role string, and content string, and appends the message to the session history in SQLite
2. THE Memory_Store SHALL provide a `get_history` async method that accepts a Session_Key and returns all messages for that session in insertion order as a list of LangChain BaseMessage objects
3. WHEN `get_history` is called with a Session_Key that does not exist, THE Memory_Store SHALL return an empty list
4. THE Memory_Store SHALL provide a `get_summary` async method that accepts a Session_Key and returns the stored Conversation_Summary string for that session
5. WHEN `get_summary` is called for a session with no summary, THE Memory_Store SHALL return an empty string
6. THE Memory_Store SHALL provide a `set_summary` async method that accepts a Session_Key and a summary string, and stores the Conversation_Summary for that session
7. THE Memory_Store SHALL provide a `truncate_history` async method that accepts a Session_Key and a `keep_last` integer, removing all but the last `keep_last` messages from the session
8. WHEN `truncate_history` is called with `keep_last` less than or equal to zero, THE Memory_Store SHALL remove all messages from the session
9. THE Memory_Store SHALL provide an `add_full_message` async method that accepts a Session_Key and a LangChain BaseMessage object (including AIMessage with tool_calls, ToolMessage with tool_call_id), and appends the complete message to the session history
10. THE Memory_Store SHALL provide a `set_history` async method that accepts a Session_Key and a list of BaseMessage objects, and atomically replaces all messages in the session with the provided list (used for emergency compression)
11. THE Memory_Store SHALL provide a `close` async method that releases the SQLite connection resources
10. THE Memory_Store SHALL use LangGraph `SqliteSaver` or `aiosqlite` as the SQLite backend, supporting async operations
11. THE Memory_Store SHALL accept a configurable `db_path` parameter for the SQLite database file location, defaulting to `~/.smartclaw/memory.db`
12. THE Memory_Store SHALL create the database file and required tables automatically on first use if the database does not exist
13. THE Memory_Store SHALL serialize LangChain BaseMessage objects to JSON for storage and deserialize them back on retrieval, preserving message type (HumanMessage, AIMessage, ToolMessage), tool_calls, tool_call_id, and metadata

### Requirement 2: Auto Summary — 自动摘要

**User Story:** As an AI Agent, I want to automatically summarize long conversations when they exceed a token threshold, so that I can reduce context window consumption while preserving important information.

#### Acceptance Criteria

1. THE Auto_Summarizer SHALL accept a configurable Token_Threshold parameter (integer, default 20 messages) that defines the message count at which summarization is triggered
2. THE Auto_Summarizer SHALL accept a configurable token percentage threshold (integer, default 70, representing percentage of context window) as a secondary trigger condition based on estimated token count
3. WHEN the message count in a session exceeds the Token_Threshold OR the estimated token count exceeds the token percentage threshold of the model's context window, THE Auto_Summarizer SHALL invoke the LLM to generate a Conversation_Summary from the older messages
4. THE Auto_Summarizer SHALL use the same LLM provider configuration (ModelConfig from SmartClawSettings) as the main Agent for summary generation
5. WHEN summarization completes, THE Auto_Summarizer SHALL store the generated summary via `Memory_Store.set_summary` and truncate the summarized messages via `Memory_Store.truncate_history`, keeping only the most recent messages
6. THE Auto_Summarizer SHALL preserve a configurable number of recent messages (default 5) after summarization to maintain immediate conversation context
7. WHEN a session has an existing Conversation_Summary, THE Auto_Summarizer SHALL include the previous summary in the LLM prompt to produce an incremental summary that incorporates both old and new context
8. THE Auto_Summarizer SHALL provide a `maybe_summarize` async method that accepts a Session_Key and the current message list, checks both thresholds, and triggers summarization only when at least one threshold is exceeded
9. IF the LLM summarization call fails, THEN THE Auto_Summarizer SHALL log the error via structlog and skip summarization without affecting the ongoing conversation
10. THE Auto_Summarizer SHALL prepend the Conversation_Summary as a SystemMessage at the beginning of the message list (after any existing system prompt) when building context for LLM calls
11. THE Auto_Summarizer SHALL provide a `force_compression` async method that aggressively reduces context when the context limit is hit, dropping the oldest ~50% of messages aligned to turn boundaries (user→assistant→tool cycles), recording a compression note in the session summary via `Memory_Store.set_summary`, and replacing the session history via `Memory_Store.set_history`
12. WHEN the conversation history has fewer than 4 messages, THE `force_compression` SHALL skip compression and return without modification
13. WHEN `force_compression` cannot find a safe turn boundary to split on, THE `force_compression` SHALL fall back to keeping only the most recent user message as a last resort

### Requirement 3: Memory 配置集成

**User Story:** As a developer, I want Memory Store and Auto Summary settings to be configurable via SmartClawSettings, so that I can customize memory behavior through YAML config or environment variables.

#### Acceptance Criteria

1. THE SmartClawSettings SHALL include a `memory` field of type MemorySettings with sub-fields: `enabled` (bool, default True), `db_path` (string, default "~/.smartclaw/memory.db"), `summary_threshold` (integer, default 20), `keep_recent` (integer, default 5), `summarize_token_percent` (integer, default 70, percentage of context window), and `context_window` (integer, default 128000, model context window size in tokens)
2. WHEN `memory.enabled` is False, THE Agent Graph SHALL skip memory loading and summarization, operating in stateless mode identical to P0 behavior
3. THE MemorySettings SHALL support environment variable overrides with prefix `SMARTCLAW_MEMORY__` (e.g., `SMARTCLAW_MEMORY__DB_PATH`, `SMARTCLAW_MEMORY__SUMMARY_THRESHOLD`)

### Requirement 4: Memory-Agent 集成

**User Story:** As a developer, I want the Memory Store and Auto Summarizer to integrate seamlessly with the existing Agent Graph, so that conversation persistence and summarization happen transparently during agent execution.

#### Acceptance Criteria

1. WHEN the Agent Graph starts processing a user message and memory is enabled, THE Agent Graph SHALL load the session history from Memory_Store and prepend any existing Conversation_Summary to the message context
2. WHEN the Agent Graph completes a turn (reasoning + action cycle), THE Agent Graph SHALL persist new messages to Memory_Store via `add_message`
3. WHEN the Agent Graph completes a turn and memory is enabled, THE Agent Graph SHALL call `Auto_Summarizer.maybe_summarize` to check and trigger summarization if the threshold is exceeded
4. THE `invoke` function in `smartclaw/agent/graph.py` SHALL accept an optional `session_key` parameter to enable cross-session memory persistence
5. WHEN `session_key` is not provided, THE Agent Graph SHALL operate in stateless mode without memory persistence, maintaining backward compatibility with P0 behavior

### Requirement 5: Skills Loader — 技能加载器

**User Story:** As a developer, I want to define skills in YAML files and dynamically load them at runtime, so that I can extend the Agent's capabilities without modifying core code.

#### Acceptance Criteria

1. THE Skills_Loader SHALL discover Skill_Definition files by scanning configured skill directories for YAML files matching the pattern `{skill_name}/skill.yaml`
2. THE Skills_Loader SHALL support three skill source directories with priority order: workspace skills (`{workspace}/skills/`) > global skills (`~/.smartclaw/skills/`) > builtin skills (package-bundled)
3. WHEN a skill with the same name exists in multiple source directories, THE Skills_Loader SHALL use the highest-priority source and ignore lower-priority duplicates
4. THE Skill_Definition YAML format SHALL include required fields: `name` (string, kebab-case, max 64 characters), `description` (string, max 1024 characters), and `entry_point` (string, Python dotted module path with function name, e.g., `mypackage.mymodule:my_function`)
5. THE Skill_Definition YAML format SHALL include optional fields: `version` (string), `author` (string), `tools` (list of tool definitions), and `parameters` (dict of configurable parameters with defaults)
6. WHEN a Skill_Definition file contains invalid YAML syntax, THE Skills_Loader SHALL log a warning via structlog and skip the invalid skill without affecting other skills
7. WHEN a Skill_Definition file has missing required fields or field values exceeding length limits, THE Skills_Loader SHALL log a validation warning and skip the invalid skill
8. THE Skills_Loader SHALL validate that `name` matches the pattern `^[a-zA-Z0-9]+(-[a-zA-Z0-9]+)*$` (alphanumeric with hyphens)
9. THE Skills_Loader SHALL provide a `list_skills` method that returns a list of SkillInfo objects (name, path, source, description) for all discovered valid skills
10. THE Skills_Loader SHALL provide a `load_skill` method that accepts a skill name and uses `importlib.import_module` to dynamically load the Python module specified by the `entry_point` field
11. WHEN the `entry_point` module cannot be imported, THE Skills_Loader SHALL raise a descriptive error indicating the module path and the import failure reason
12. THE Skills_Loader SHALL provide a `load_skill` method that returns a callable (the entry point function) and the parsed Skill_Definition metadata
13. THE Skills_Loader SHALL provide a `build_skills_summary` method that returns a formatted string summarizing all discovered skills (name, description, source) suitable for injection into the Agent's system prompt, enabling the LLM to know which skills are available
14. THE Skills_Loader SHALL provide a `load_skills_for_context` method that accepts a list of skill names and returns the concatenated skill content for injection into the LLM context

### Requirement 6: Skill Definition 序列化往返

**User Story:** As a developer, I want to ensure that Skill Definition YAML files can be parsed and re-serialized without data loss, so that tooling can safely read and write skill configurations.

#### Acceptance Criteria

1. THE Skills_Loader SHALL provide a `parse_skill_yaml` function that accepts a YAML string and returns a SkillDefinition object
2. THE Skills_Loader SHALL provide a `serialize_skill_yaml` function that accepts a SkillDefinition object and returns a YAML string
3. FOR ALL valid SkillDefinition objects, parsing the serialized YAML output and comparing with the original object SHALL produce an equivalent SkillDefinition (round-trip property)

### Requirement 7: Skills Registry — 技能注册表

**User Story:** As a developer, I want a central registry to manage loaded skills and integrate their tools with the existing ToolRegistry, so that skill-provided tools are available to the Agent Graph.

#### Acceptance Criteria

1. THE Skills_Registry SHALL provide a `register` method that accepts a skill name and a loaded skill module, and stores the skill in the registry
2. THE Skills_Registry SHALL provide an `unregister` method that accepts a skill name and removes the skill from the registry
3. THE Skills_Registry SHALL provide a `get` method that accepts a skill name and returns the registered skill, or None if the skill is not registered
4. THE Skills_Registry SHALL provide a `list_skills` method that returns all registered skill names as a sorted list of strings
5. WHEN a skill provides tools (via the `tools` field in Skill_Definition), THE Skills_Registry SHALL create LangChain BaseTool instances from the tool definitions and register them in the ToolRegistry
6. WHEN a skill is unregistered, THE Skills_Registry SHALL remove the skill's tools from the ToolRegistry
7. THE Skills_Registry SHALL provide a `load_and_register_all` method that uses Skills_Loader to discover and load all available skills, registering each valid skill and its tools
8. WHEN a skill's entry point function returns a list of BaseTool instances, THE Skills_Registry SHALL register those tools in the ToolRegistry
9. IF a skill registration fails (import error, validation error), THEN THE Skills_Registry SHALL log the error via structlog and continue registering remaining skills

### Requirement 8: Skills 配置集成

**User Story:** As a developer, I want Skills settings to be configurable via SmartClawSettings, so that I can customize skill directories and enable/disable the skills system.

#### Acceptance Criteria

1. THE SmartClawSettings SHALL include a `skills` field of type SkillsSettings with sub-fields: `enabled` (bool, default True), `workspace_dir` (string, default "{workspace}/skills"), `global_dir` (string, default "~/.smartclaw/skills")
2. WHEN `skills.enabled` is False, THE Agent Graph SHALL skip skill loading and registration, operating without skill-provided tools
3. THE SkillsSettings SHALL support environment variable overrides with prefix `SMARTCLAW_SKILLS__`

### Requirement 9: Sub-Agent — 子 Agent 任务委托

**User Story:** As an AI Agent, I want to spawn sub-agents for specific subtasks using LangGraph SubGraph, so that I can delegate complex work to specialized child agents while maintaining overall task coordination.

#### Acceptance Criteria

1. THE Sub_Agent module SHALL provide a `spawn_sub_agent` async function that accepts a Sub_Agent_Config and returns the sub-agent's final response string
2. THE Sub_Agent_Config SHALL include required fields: `task` (string, the task description for the sub-agent) and `model` (string, the LLM model reference to use)
3. THE Sub_Agent_Config SHALL include optional fields: `tools` (list of BaseTool, tools available to the sub-agent), `system_prompt` (string, custom system prompt), `max_iterations` (integer, default 25), `timeout_seconds` (integer, default 300), and `max_depth` (integer, maximum nesting depth)
4. THE Sub_Agent module SHALL construct a LangGraph SubGraph for each spawned sub-agent, using the same `build_graph` infrastructure from `smartclaw/agent/graph.py` with the sub-agent's specific tool set and model configuration
5. WHEN a sub-agent exceeds the configured `timeout_seconds`, THE Sub_Agent module SHALL cancel the sub-agent execution and return a timeout error message
6. THE Sub_Agent module SHALL enforce a configurable maximum nesting depth (default 3) to prevent infinite recursive sub-agent spawning
7. WHEN a sub-agent spawn request exceeds the maximum nesting depth, THE Sub_Agent module SHALL return an error indicating the depth limit has been exceeded without spawning the sub-agent
8. THE Sub_Agent module SHALL track the parent-child relationship between agents, recording the parent turn ID and child turn ID for observability
9. THE Sub_Agent module SHALL provide a `spawn_sub_agent_tool` LangChain BaseTool that the parent Agent can invoke via tool calls to delegate subtasks, accepting `task` (string) and optional `model` (string) parameters
10. WHEN the sub-agent completes execution, THE `spawn_sub_agent_tool` SHALL return the sub-agent's final answer as the tool result string
11. IF the sub-agent execution fails with an exception, THEN THE Sub_Agent module SHALL catch the exception, log the error via structlog, and return an error message string describing the failure
12. THE Sub_Agent module SHALL use an ephemeral in-memory message store for sub-agent sessions, preventing sub-agent conversation history from polluting the parent agent's persistent memory
13. THE ephemeral in-memory message store SHALL enforce a configurable maximum history size (default 50 messages) and automatically truncate older messages when the limit is exceeded, preventing memory accumulation in long-running sub-agents

### Requirement 10: Sub-Agent 并发控制

**User Story:** As a system operator, I want to limit the number of concurrent sub-agents, so that system resources are protected from excessive parallel agent execution.

#### Acceptance Criteria

1. THE Sub_Agent module SHALL enforce a configurable maximum concurrent sub-agent count (default 5) using an asyncio Semaphore
2. WHEN the concurrent sub-agent limit is reached, THE Sub_Agent module SHALL wait up to a configurable timeout (default 30 seconds) for a slot to become available
3. WHEN the concurrency wait timeout is exceeded, THE Sub_Agent module SHALL return an error indicating all concurrency slots are occupied

### Requirement 11: Sub-Agent 配置集成

**User Story:** As a developer, I want Sub-Agent settings to be configurable via SmartClawSettings, so that I can tune sub-agent behavior through configuration.

#### Acceptance Criteria

1. THE SmartClawSettings SHALL include a `sub_agent` field of type SubAgentSettings with sub-fields: `enabled` (bool, default True), `max_depth` (integer, default 3), `max_concurrent` (integer, default 5), `default_timeout_seconds` (integer, default 300), and `concurrency_timeout_seconds` (integer, default 30)
2. WHEN `sub_agent.enabled` is False, THE Agent Graph SHALL not register the `spawn_sub_agent_tool`, preventing sub-agent spawning
3. THE SubAgentSettings SHALL support environment variable overrides with prefix `SMARTCLAW_SUB_AGENT__`

### Requirement 12: Multi-Agent Coordination — 多 Agent 协同

**User Story:** As an AI Agent system, I want to orchestrate multiple specialized agents working together on complex tasks, so that different agents can contribute their expertise to solve problems that require diverse capabilities.

#### Acceptance Criteria

1. THE Multi_Agent_Coordinator SHALL provide a `create_multi_agent_graph` function that accepts a list of Agent_Role definitions and returns a compiled LangGraph StateGraph for multi-agent orchestration
2. THE Agent_Role definition SHALL include required fields: `name` (string, unique agent identifier), `description` (string, agent's capability description), `model` (string, LLM model reference), and `tools` (list of BaseTool, agent-specific tools)
3. THE Agent_Role definition SHALL include optional fields: `system_prompt` (string, role-specific system prompt) and `max_iterations` (integer, per-agent iteration limit, default 25)
4. THE Multi_Agent_Coordinator SHALL implement a supervisor pattern where a coordinator agent receives the user task, decomposes it into subtasks, assigns subtasks to appropriate specialized agents, and synthesizes the final result
5. THE Multi_Agent_Coordinator SHALL use LangGraph's conditional routing to direct tasks to the appropriate specialized agent based on the supervisor's assignment decisions
6. WHEN a specialized agent completes its subtask, THE Multi_Agent_Coordinator SHALL return the result to the supervisor agent for evaluation and potential further delegation
7. THE Multi_Agent_Coordinator SHALL support a configurable maximum total iterations across all agents (default 100) to prevent runaway multi-agent loops
8. WHEN the total iteration limit is reached, THE Multi_Agent_Coordinator SHALL terminate the multi-agent graph and return the best available partial result with a warning message
9. THE Multi_Agent_Coordinator SHALL share the same Memory_Store instance across all agents in a multi-agent session, enabling agents to access shared conversation context
10. IF any specialized agent fails during execution, THEN THE Multi_Agent_Coordinator SHALL report the failure to the supervisor agent, which can reassign the subtask or adjust the plan

### Requirement 13: Multi-Agent 配置集成

**User Story:** As a developer, I want Multi-Agent settings to be configurable via SmartClawSettings, so that I can define agent roles and orchestration parameters through configuration.

#### Acceptance Criteria

1. THE SmartClawSettings SHALL include a `multi_agent` field of type MultiAgentSettings with sub-fields: `enabled` (bool, default False), `max_total_iterations` (integer, default 100), and `roles` (list of AgentRoleConfig, default empty list)
2. THE AgentRoleConfig SHALL include fields: `name` (string), `description` (string), `model` (string), `system_prompt` (string, optional), and `tools` (list of string tool names, optional)
3. WHEN `multi_agent.enabled` is False, THE Multi_Agent_Coordinator SHALL not be available, and the system SHALL operate in single-agent mode
4. THE MultiAgentSettings SHALL support environment variable overrides with prefix `SMARTCLAW_MULTI_AGENT__`

### Requirement 14: P1 模块与现有系统的向后兼容

**User Story:** As a developer, I want all P1 modules to be backward compatible with the existing P0 system, so that existing functionality continues to work without modification when P1 modules are disabled.

#### Acceptance Criteria

1. WHEN all P1 module settings (`memory.enabled`, `skills.enabled`, `sub_agent.enabled`, `multi_agent.enabled`) are set to False, THE SmartClaw system SHALL behave identically to the P0 system with no functional differences
2. THE P1 modules SHALL not modify any existing P0 module interfaces (AgentState, build_graph, ToolRegistry, SmartClawSettings existing fields)
3. THE P1 modules SHALL extend AgentState with optional new fields (e.g., `session_key`, `summary`) using default values of None, maintaining compatibility with existing graph nodes
4. THE P1 modules SHALL be importable independently without requiring all P1 dependencies to be installed, using lazy imports for optional dependencies
