# Implementation Plan: Provider 配置化、上下文压缩与会话管理优化

## Overview

Incrementally implement the six major areas: (1) config-driven ProviderFactory, (2) AuthProfile + two-stage FallbackChain, (3) five-layer context compression (L1–L5), (4) session-level model override & token stats, (5) Sub-Agent fallback inheritance & EphemeralStore compaction, (6) CooldownTracker persistence. Each task builds on previous tasks; property-based tests use `hypothesis`.

## Tasks

- [x] 1. ProviderSpec model and config-driven ProviderFactory
  - [x] 1.1 Add ProviderSpec and AuthProfile models to `smartclaw/providers/config.py`
    - Add `ProviderSpec` Pydantic model with fields: `name`, `class_path`, `env_key`, `base_url`, `model_field`, `extra_params`
    - Add `AuthProfile` Pydantic model with fields: `profile_id`, `provider`, `env_key`, `base_url`
    - Extend `ModelConfig` with new fields: `auth_profiles`, `session_sticky`, `compaction_model`, `identifier_policy`, `identifier_patterns`
    - _Requirements: 1.1, 2.1_

  - [x] 1.2 Refactor ProviderFactory to use ProviderSpec + importlib dynamic loading in `smartclaw/providers/factory.py`
    - Add `_BUILTIN_SPECS` dict with openai, anthropic, kimi defaults
    - Add `_custom_specs` class var and `register_specs(specs)` classmethod
    - Add `get_spec(provider)` classmethod (custom > builtin, ValueError if not found)
    - Rewrite `create()` to use `get_spec` + `importlib.import_module` + `getattr` for dynamic class loading
    - Keep `create()` method signature unchanged (provider, model, api_key, api_base, temperature, max_tokens, streaming)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8_

  - [x] 1.3 Write property tests for ProviderSpec registration (Properties 1–5)
    - **Property 1: ProviderSpec 注册与查找一致性**
    - **Property 2: ProviderSpec 覆盖内置默认值**
    - **Property 3: 无效 class_path 抛出 ValueError**
    - **Property 4: 缺失 API Key 抛出 ValueError**
    - **Property 5: extra_params 透传**
    - **Validates: Requirements 1.1, 1.3, 1.5, 1.6, 1.7**

  - [x] 1.4 Add `providers` field to `SmartClawSettings` and wire `register_specs` in config loader
    - Add `providers: list[ProviderSpec]` field to `SmartClawSettings` in `smartclaw/config/settings.py`
    - Call `ProviderFactory.register_specs` during `setup_agent_runtime` in `smartclaw/agent/runtime.py`
    - Update `smartclaw/config/config.example.yaml` with `providers` section example
    - _Requirements: 1.1, 1.2_

- [x] 2. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. AuthProfile two-stage FallbackChain and CooldownTracker key change
  - [x] 3.1 Extend FallbackCandidate with `profile_id` and update CooldownTracker key logic in `smartclaw/providers/fallback.py`
    - Add `profile_id: str | None = None` to `FallbackCandidate` NamedTuple
    - Change CooldownTracker to use `profile_id` as cooldown key when present, fall back to `provider` when absent
    - Update `mark_failure`, `mark_success`, `is_available`, `cooldown_remaining` to accept/use the new key logic
    - _Requirements: 2.3, 2.6_

  - [x] 3.2 Implement two-stage FallbackChain execution in `smartclaw/providers/fallback.py`
    - Add `_build_two_stage_candidates` method that groups candidates by provider, interleaves AuthProfile rotation before provider switching
    - Modify `FallbackChain.execute` to accept optional `auth_profiles` parameter and implement two-stage logic
    - Stage 1: rotate AuthProfiles within same provider on RATE_LIMIT
    - Stage 2: switch to next provider/model when all profiles exhausted
    - When `auth_profiles` is empty, fall back to current single-key behavior
    - Add `session_sticky` support: track last successful profile_id per session
    - _Requirements: 2.2, 2.4, 2.5, 2.7, 2.8_

  - [x] 3.3 Wire AuthProfile into `_llm_call_with_fallback` in `smartclaw/agent/graph.py`
    - Build FallbackCandidate list including AuthProfile profile_ids from ModelConfig
    - Pass `api_key` from AuthProfile's env_key to `ProviderFactory.create`
    - _Requirements: 2.1, 2.2_

  - [x] 3.4 Write property tests for AuthProfile and FallbackChain (Properties 6–10)
    - **Property 6: AuthProfile 配置序列化往返**
    - **Property 7: 两阶段 FallbackChain 执行顺序**
    - **Property 8: CooldownTracker profile_id 独立性**
    - **Property 9: 空 AuthProfile 向后兼容**
    - **Property 10: session_sticky 优先使用上次成功的 AuthProfile**
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.7, 2.8**

- [x] 4. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. L1 ToolResultGuard — tool result truncation
  - [x] 5.1 Create `smartclaw/smartclaw/memory/tool_result_guard.py` with ToolResultGuard class
    - Implement `ToolResultGuardConfig` dataclass with `tool_result_max_chars`, `head_chars`, `tail_chars`, `tool_overrides`
    - Implement `ToolResultGuard` class with `cap_tool_result(content, tool_name)` and `_get_limits(tool_name)` methods
    - Truncation format: `\n\n[... truncated {original_length} chars, showing first {head_chars} + last {tail_chars} ...]\n\n`
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [x] 5.2 Integrate ToolResultGuard into action_node in `smartclaw/smartclaw/agent/nodes.py`
    - Call `ToolResultGuard.cap_tool_result` on ToolMessage content before appending to tool_messages
    - Accept ToolResultGuard instance as optional parameter to action_node
    - Wire ToolResultGuard creation in `build_graph` using MemorySettings config
    - _Requirements: 3.1, 3.6_

  - [x] 5.3 Write property tests for ToolResultGuard (Properties 11–13)
    - **Property 11: L1 工具结果截断 — head+tail 保留**
    - **Property 12: L1 截断不修改短内容**
    - **Property 13: L1 工具专属截断阈值**
    - **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

- [x] 6. L2 SessionPruner — session pruning
  - [x] 6.1 Create `smartclaw/smartclaw/memory/pruning.py` with SessionPruner class
    - Implement `SessionPrunerConfig` dataclass with `soft_trim_threshold`, `hard_clear_threshold`, `soft_trim_head`, `soft_trim_tail`, `keep_recent`, `keep_head`, `tool_allow_list`, `tool_deny_list`
    - Implement `SessionPruner` class with `prune(messages)`, `_soft_trim(content)`, `_should_skip(msg, tool_name)` methods
    - Prune from middle outward, preserving head and tail messages
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_

  - [x] 6.2 Integrate SessionPruner into reasoning_node in `smartclaw/smartclaw/agent/nodes.py`
    - Call `SessionPruner.prune` on messages before LLM invocation
    - Accept SessionPruner instance as optional parameter to reasoning_node
    - Wire SessionPruner creation in `build_graph` using MemorySettings config
    - _Requirements: 4.1_

  - [x] 6.3 Write property tests for SessionPruner (Properties 14–16)
    - **Property 14: L2 两级裁剪阈值行为**
    - **Property 15: L2 裁剪保留头尾消息**
    - **Property 16: L2 allow_list 消息不被裁剪**
    - **Validates: Requirements 4.2, 4.3, 4.4, 4.5, 4.6**

- [x] 7. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. L3 Pre-compaction memory flush and L4 multi-stage compaction
  - [x] 8.1 Extend AutoSummarizer constructor with L3/L4 config params in `smartclaw/smartclaw/memory/summarizer.py`
    - Add constructor params: `compaction_model`, `identifier_policy`, `identifier_patterns`, `chunk_max_tokens`, `part_max_tokens`
    - Add `_get_compaction_model_config()` helper method
    - Add `_build_identifier_instructions()` helper method
    - _Requirements: 5.5, 6.5, 6.6_

  - [x] 8.2 Implement L3 `_memory_flush` method in AutoSummarizer
    - Build specialized prompt to extract key identifiers (file paths, variable names, function names), decision points, and pending tasks
    - Call LLM via FallbackChain using compaction model config
    - Merge result with existing summary using `\n\n---\n\n` separator via `MemoryStore.set_summary`
    - On LLM failure: log warning, do not interrupt L4
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

  - [x] 8.3 Implement L4 `_multi_stage_compact` method in AutoSummarizer
    - Chunk messages by `chunk_max_tokens` at turn boundaries (HumanMessage)
    - Sequential per-chunk LLM summarization with prior chunk summaries as context
    - Split chunks exceeding `part_max_tokens` into sub-chunks, summarize parts, merge
    - Include identifier preservation instructions based on `identifier_policy`
    - _Requirements: 6.1, 6.2, 6.3, 6.5_

  - [x] 8.4 Implement `_summarize_with_fallback` progressive fallback strategy in AutoSummarizer
    - Attempt 1: full compression via `_multi_stage_compact`
    - Attempt 2: filter oversized ToolMessages, retry compression
    - Attempt 3: hardcoded fallback text replacing all history
    - _Requirements: 6.4_

  - [x] 8.5 Implement `_overflow_recovery` in AutoSummarizer
    - Retry up to 3 times with exponential backoff (1s, 2s, 4s)
    - Each retry halves `chunk_max_tokens`
    - _Requirements: 6.7_

  - [x] 8.6 Enhance `maybe_summarize` to integrate L3 + L4 logic in AutoSummarizer
    - After threshold check: execute L3 `_memory_flush`, then L4 `_multi_stage_compact` via `_summarize_with_fallback`
    - Replace current simple summarization with the new pipeline
    - _Requirements: 6.9_

  - [x] 8.7 Add context overflow detection and force_compression retry in `smartclaw/smartclaw/agent/nodes.py`
    - In reasoning_node: catch HTTP 400 errors containing "context", "token", or "length" keywords
    - Trigger `force_compression` on the summarizer, then retry the LLM call once
    - _Requirements: 6.8_

  - [x] 8.8 Write property tests for L3 and L4 (Properties 17–23)
    - **Property 17: L3 摘要追加合并**
    - **Property 18: L3 失败不中断 L4**
    - **Property 19: L4 分块在 turn boundary 切分**
    - **Property 20: L4 渐进回退策略**
    - **Property 21: L4 identifier_policy 指令生成**
    - **Property 22: L4 溢出自动恢复重试**
    - **Property 23: 上下文溢出错误检测触发 force_compression**
    - **Validates: Requirements 5.1, 5.3, 5.4, 6.1, 6.4, 6.5, 6.7, 6.8**

- [x] 9. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. L5 ContextEngine plugin architecture
  - [x] 10.1 Create `smartclaw/smartclaw/context_engine/__init__.py` with public API exports
    - Export `ContextEngine`, `LegacyContextEngine`, `ContextEngineRegistry`
    - _Requirements: 7.7_

  - [x] 10.2 Create `smartclaw/smartclaw/context_engine/interface.py` with ContextEngine ABC
    - Define abstract methods: `bootstrap`, `ingest`, `assemble`, `after_turn`, `compact`, `maintain`, `dispose`
    - Define Sub-Agent lifecycle hooks: `prepare_subagent_spawn`, `on_subagent_ended`
    - _Requirements: 7.1, 7.2_

  - [x] 10.3 Create `smartclaw/smartclaw/context_engine/legacy.py` with LegacyContextEngine
    - Implement ContextEngine interface wrapping AutoSummarizer
    - `assemble` → `summarizer.build_context`, `after_turn` → `summarizer.maybe_summarize`, `compact` → `summarizer.force_compression` or `maybe_summarize`
    - Optionally integrate SessionPruner in `assemble`
    - _Requirements: 7.3_

  - [x] 10.4 Create `smartclaw/smartclaw/context_engine/registry.py` with ContextEngineRegistry
    - Class-level `_engines` dict, `register(name, cls)`, `get(name)`, `create(name, **kwargs)` classmethods
    - Auto-register `LegacyContextEngine` as "legacy"
    - _Requirements: 7.4, 7.6_

  - [x] 10.5 Wire ContextEngine into agent graph in `smartclaw/agent/graph.py` and `smartclaw/agent/runtime.py`
    - Add `context_engine` field to `SmartClawSettings` (default "legacy")
    - Create ContextEngine instance in `setup_agent_runtime`
    - Use `context_engine.assemble` in `invoke` instead of direct `summarizer.build_context`
    - Use `context_engine.after_turn` instead of direct `summarizer.maybe_summarize`
    - Store ContextEngine in AgentRuntime, call `dispose` in `close`
    - _Requirements: 7.5, 7.6_

  - [x] 10.6 Write property test for ContextEngineRegistry (Property 24)
    - **Property 24: ContextEngineRegistry 注册往返**
    - **Validates: Requirements 7.4**

- [x] 11. Session-level model override and token statistics
  - [x] 11.1 Add `session_config` and `cooldown_state` tables to MemoryStore in `smartclaw/smartclaw/memory/store.py`
    - Add `session_config` table: `session_key TEXT PK`, `model_override TEXT`, `config_json TEXT`, `updated_at TIMESTAMP`
    - Add `cooldown_state` table: `profile_id TEXT PK`, `error_count INT`, `cooldown_end_utc TEXT`, `last_failure_utc TEXT`, `failure_counts_json TEXT`
    - Add methods: `get_session_config`, `set_session_config`, `get_cooldown_states`, `set_cooldown_state`, `delete_cooldown_state`
    - Create tables in `initialize()`
    - _Requirements: 8.1, 10.1_

  - [x] 11.2 Add `TokenStats` TypedDict and `token_stats` field to AgentState in `smartclaw/smartclaw/agent/state.py`
    - Define `TokenStats` TypedDict with `prompt_tokens`, `completion_tokens`, `total_tokens`
    - Add `token_stats: TokenStats | None` to `AgentState`
    - _Requirements: 8.4_

  - [x] 11.3 Accumulate token stats in reasoning_node in `smartclaw/smartclaw/agent/nodes.py`
    - After LLM call, extract `usage_metadata` from AIMessage
    - If present: accumulate `prompt_tokens`, `completion_tokens`, `total_tokens` into state's `token_stats`
    - If absent: use `AutoSummarizer.estimate_tokens` as fallback for prompt tokens
    - _Requirements: 8.5, 8.7_

  - [x] 11.4 Add `SessionConfigRequest` model and `token_stats` to ChatResponse in `smartclaw/smartclaw/gateway/models.py`
    - Add `SessionConfigRequest` with optional `model` field
    - Add `token_stats: dict[str, int] | None = None` to `ChatResponse`
    - _Requirements: 8.2, 8.6_

  - [x] 11.5 Add `PUT /api/sessions/{key}/config` endpoint and wire session model override in `smartclaw/smartclaw/gateway/routers/chat.py`
    - Add PUT endpoint that persists `model_override` to MemoryStore `session_config` table
    - In `chat` endpoint: if request has no `model`, query `session_config` for `model_override`
    - Return `token_stats` in ChatResponse from final AgentState
    - _Requirements: 8.2, 8.3, 8.6_

  - [x] 11.6 Write property tests for session config and token stats (Properties 25–26)
    - **Property 25: 会话模型覆盖解析**
    - **Property 26: Token 统计累加**
    - **Validates: Requirements 8.3, 8.5, 8.7**

- [x] 12. Checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Sub-Agent fallback inheritance and EphemeralStore compaction
  - [x] 13.1 Add `parent_model_config` to SpawnSubAgentTool and inherit fallbacks in `smartclaw/smartclaw/agent/sub_agent.py`
    - Add `parent_model_config: ModelConfig | None = None` field to `SpawnSubAgentTool`
    - Add `fallbacks: list[str]` field to `SubAgentConfig`
    - In `_arun`: build `ModelConfig` with `parent_model_config.fallbacks` instead of empty list
    - _Requirements: 9.1, 9.2_

  - [x] 13.2 Wire parent ModelConfig into SpawnSubAgentTool in `smartclaw/smartclaw/agent/runtime.py`
    - Pass `settings.model` as `parent_model_config` when constructing `SpawnSubAgentTool`
    - _Requirements: 9.1_

  - [x] 13.3 Add lightweight compaction to EphemeralStore in `smartclaw/smartclaw/agent/sub_agent.py`
    - Add `compact_threshold: float = 0.8` constructor param
    - Implement `_compact_if_needed`: when message count > `max_size * compact_threshold`, soft-trim middle ToolMessages (L2-style)
    - Call `_compact_if_needed` in `add_message` before truncation check
    - _Requirements: 9.3_

  - [x] 13.4 Call ContextEngine Sub-Agent hooks in `spawn_sub_agent` in `smartclaw/smartclaw/agent/sub_agent.py`
    - Accept optional `context_engine` parameter in `spawn_sub_agent`
    - Call `prepare_subagent_spawn` before graph build, `on_subagent_ended` after completion
    - _Requirements: 9.5_

  - [x] 13.5 Write property tests for Sub-Agent fallback and EphemeralStore (Properties 27–28)
    - **Property 27: Sub-Agent fallback 继承**
    - **Property 28: EphemeralStore 轻量压缩触发**
    - **Validates: Requirements 9.2, 9.3**

- [x] 14. CooldownTracker state persistence
  - [x] 14.1 Implement `save_state` and `restore_state` on CooldownTracker in `smartclaw/smartclaw/providers/fallback.py`
    - `save_state(store)`: serialize all `_CooldownEntry` to `cooldown_state` table (monotonic → UTC conversion)
    - `restore_state(store)`: read from `cooldown_state` table, skip expired records, convert UTC → monotonic offset
    - _Requirements: 10.2, 10.3, 10.6, 10.7_

  - [x] 14.2 Add fire-and-forget persistence to `mark_failure` and `mark_success` in CooldownTracker
    - Accept optional `store: MemoryStore | None` parameter
    - After state change, schedule `save_state` via `asyncio.create_task` (fire-and-forget)
    - _Requirements: 10.4_

  - [x] 14.3 Call `restore_state` during startup in `smartclaw/smartclaw/agent/runtime.py`
    - In `setup_agent_runtime`, after MemoryStore initialization, call `cooldown_tracker.restore_state(memory_store)`
    - Pass the CooldownTracker instance through to FallbackChain
    - _Requirements: 10.5_

  - [x] 14.4 Write property tests for CooldownTracker persistence (Properties 29–31)
    - **Property 29: CooldownTracker 状态持久化往返**
    - **Property 30: CooldownTracker mark_failure 触发持久化**
    - **Property 31: 过期冷却状态不恢复**
    - **Validates: Requirements 10.2, 10.3, 10.4, 10.6, 10.7**

- [x] 15. Update MemorySettings and config.example.yaml
  - [x] 15.1 Extend MemorySettings in `smartclaw/smartclaw/config/settings.py`
    - Add L1 fields: `tool_result_max_chars`, `tool_result_head_chars`, `tool_result_tail_chars`, `tool_overrides`
    - Add L2 fields: `soft_trim_threshold`, `hard_clear_threshold`, `pruner_keep_recent`, `pruner_keep_head`, `tool_allow_list`, `tool_deny_list`
    - Add L4 fields: `chunk_max_tokens`, `part_max_tokens`
    - Add `context_engine: str = "legacy"` to `SmartClawSettings`
    - _Requirements: 3.2, 4.2, 4.3, 6.1, 7.6_

  - [x] 15.2 Update `smartclaw/config/config.example.yaml` with all new configuration sections
    - Add `providers` section with deepseek example
    - Add `auth_profiles`, `session_sticky`, `compaction_model`, `identifier_policy` under `model`
    - Add L1/L2/L4 config fields under `memory`
    - Add `context_engine` top-level field
    - _Requirements: 1.1, 2.1, 6.5, 6.6_

  - [x] 15.3 Update `smartclaw/smartclaw/providers/__init__.py` exports
    - Add `ProviderSpec`, `AuthProfile`, `FallbackCandidate` (with profile_id) to `__all__`
    - _Requirements: 1.1, 2.1, 2.6_

- [x] 16. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- All tasks are required, including property-based tests
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation after each major area
- Property tests validate universal correctness properties using `hypothesis`
- Unit tests validate specific examples and edge cases
- All 31 correctness properties from the design document are covered across tasks 1.3, 3.4, 5.3, 6.3, 8.8, 10.6, 11.6, 13.5, and 14.4
