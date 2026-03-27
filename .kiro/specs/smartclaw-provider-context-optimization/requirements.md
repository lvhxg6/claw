# 需求文档：Provider 配置化、上下文压缩与会话管理优化

## 简介

当前 SmartClaw 的 Provider 层（ProviderFactory）采用硬编码 if/elif 分支注册 LLM 提供商，新增提供商需要修改源码；FallbackChain 仅支持单 API Key 的提供商级别故障转移，无法在同一提供商的多个 API Key 之间轮转；上下文管理仅有 AutoSummarizer 的单层摘要压缩，缺乏写入时截断、会话级裁剪、预压缩记忆刷新、多阶段分块压缩等精细化控制；会话级模型覆盖和 Token 统计缺失；Sub-Agent 未继承父 Agent 的 fallback 配置；CooldownTracker 状态仅存于内存，重启后丢失。

本功能覆盖六大领域：(1) 配置驱动的多 Provider 注册；(2) AuthProfile 认证轮转 + 两阶段 FallbackChain；(3) 五层上下文压缩体系（L1 工具结果截断、L2 会话裁剪、L3 预压缩记忆刷新、L4 多阶段压缩、L5 ContextEngine 插件架构）；(4) 会话级模型覆盖与 Token 统计；(5) Sub-Agent fallback 继承与 EphemeralStore 轻量压缩；(6) CooldownTracker 状态持久化。

## 术语表

- **ProviderFactory**: LLM 提供商工厂，根据提供商名称创建 LangChain BaseChatModel 实例
- **ProviderSpec**: 声明式提供商规格定义，包含 LangChain 类路径、环境变量 Key、base_url、model 字段名等
- **AuthProfile**: 认证配置文件，同一提供商可拥有多个 AuthProfile（不同 API Key），用于 Key 轮转
- **FallbackChain**: 模型故障转移链，按优先级尝试候选模型，支持两阶段策略（先轮转 AuthProfile，再切换模型）
- **CooldownTracker**: 冷却追踪器，记录提供商/AuthProfile 的失败次数和冷却截止时间，支持指数退避
- **FallbackCandidate**: 故障转移候选项，包含 provider、model、profile_id 信息
- **L1_Truncation**: 第一层压缩——工具结果写入时截断，在 action_node 中对 ToolMessage 内容进行 head/tail 保留截断
- **L2_Session_Pruning**: 第二层压缩——会话裁剪，在每次 LLM 调用前对内存中的消息列表进行软裁剪（保留头尾）和硬清除（替换为占位符）
- **L3_Memory_Flush**: 第三层压缩——预压缩记忆刷新，在执行压缩前发起一次静默 LLM 调用，将关键上下文持久化到 MemoryStore 摘要
- **L4_Compaction**: 第四层压缩——多阶段压缩，将消息按 Token 上限分块 → 逐块摘要 → 拆分为部分摘要 → 合并部分摘要 → 渐进回退策略 → 标识符保留策略 → 溢出自动恢复
- **L5_ContextEngine**: 第五层——上下文引擎插件架构，定义 ContextEngine 接口（bootstrap、ingest、assemble、afterTurn、compact、maintain、dispose）及默认 LegacyContextEngine 实现
- **ContextEngine**: 上下文引擎接口，定义上下文生命周期的所有阶段方法
- **LegacyContextEngine**: 默认上下文引擎实现，封装现有 AutoSummarizer 逻辑为 ContextEngine 接口
- **MemoryStore**: 基于 SQLite 的异步对话历史持久化存储
- **AutoSummarizer**: 现有的 LLM 驱动自动摘要组件，将被 L4_Compaction 增强
- **EphemeralStore**: Sub-Agent 的内存消息存储
- **SessionConfig**: 会话级配置，包含模型覆盖、Token 统计等
- **IdentifierPolicy**: 标识符保留策略，控制压缩时是否保留文件路径、变量名等标识符（strict/custom/off）
- **CompactionModel**: 可配置的压缩专用模型，允许使用与主模型不同的 LLM 执行压缩任务
- **ToolResultGuard**: 工具结果截断守卫，负责 L1 层的 ToolMessage 内容截断逻辑
- **SessionPruner**: 会话裁剪器，负责 L2 层的消息列表裁剪逻辑

## 需求

### 需求 1：配置驱动的多 Provider 动态注册

**用户故事：** 作为开发者，我希望通过 config.yaml 声明式注册新的 LLM 提供商，无需修改 ProviderFactory 源码，以实现零代码接入 deepseek、ollama 等新提供商。

#### 验收标准

1. THE ProviderFactory SHALL 支持从 config.yaml 的 `providers` 字段读取 ProviderSpec 列表，每个 ProviderSpec 包含 `name`（提供商名称）、`class_path`（LangChain 类的完整 Python 导入路径）、`env_key`（API Key 环境变量名）、`base_url`（可选的 API 基础 URL）、`model_field`（模型参数字段名，默认 "model"）
2. THE ProviderFactory SHALL 内置 openai、anthropic、kimi 三个默认 ProviderSpec，当 config.yaml 中未定义同名提供商时使用内置默认值
3. WHEN config.yaml 中定义了与内置提供商同名的 ProviderSpec 时，THE ProviderFactory SHALL 使用 config.yaml 中的定义覆盖内置默认值
4. WHEN ProviderFactory.create 被调用时，THE ProviderFactory SHALL 根据 provider 名称查找对应的 ProviderSpec，通过 `importlib` 动态导入 `class_path` 指定的 LangChain 类，并使用 ProviderSpec 中的配置参数实例化该类
5. IF ProviderSpec 的 `class_path` 指定的模块或类不存在，THEN THE ProviderFactory SHALL 抛出 ValueError 并包含描述性错误信息，说明缺少哪个模块
6. IF ProviderSpec 的 `env_key` 对应的环境变量未设置且未提供 api_key 参数，THEN THE ProviderFactory SHALL 抛出 ValueError 并提示需要设置对应的环境变量
7. THE ProviderSpec 模型 SHALL 支持可选的 `extra_params` 字典字段，用于传递提供商特有的额外参数（如 kimi 的 `extra_body`）
8. THE ProviderFactory SHALL 保持现有 `create` 方法的函数签名不变（provider、model、api_key、api_base、temperature、max_tokens、streaming），确保所有现有调用方无需修改

### 需求 2：AuthProfile 认证轮转与两阶段 FallbackChain

**用户故事：** 作为运维人员，我希望为同一提供商配置多个 API Key（AuthProfile），当某个 Key 触发限流时自动轮转到下一个 Key，而非直接切换到其他提供商模型，以最大化利用已有的 API 配额。

#### 验收标准

1. THE config.yaml SHALL 支持在 `model` 配置下定义 `auth_profiles` 列表，每个 AuthProfile 包含 `profile_id`（唯一标识）、`provider`（提供商名称）、`env_key`（API Key 环境变量名）、`base_url`（可选的 API 基础 URL）
2. THE FallbackChain SHALL 实现两阶段故障转移策略：第一阶段在同一 provider 的不同 AuthProfile 之间轮转，第二阶段在不同 provider/model 之间切换
3. THE CooldownTracker 的冷却键 SHALL 从当前的 provider 名称变更为 profile_id，使得同一提供商的不同 AuthProfile 拥有独立的冷却状态
4. WHEN 某个 AuthProfile 触发 RATE_LIMIT 错误时，THE FallbackChain SHALL 将该 profile_id 标记为冷却状态，并尝试同一 provider 的下一个 AuthProfile
5. WHEN 同一 provider 的所有 AuthProfile 均处于冷却状态时，THE FallbackChain SHALL 进入第二阶段，尝试 fallbacks 列表中的下一个 provider/model
6. THE FallbackCandidate SHALL 扩展为包含 `profile_id` 字段，用于标识使用哪个 AuthProfile
7. WHEN AuthProfile 未配置时（auth_profiles 为空列表），THE FallbackChain SHALL 回退到当前的单 Key 行为，保持向后兼容
8. THE config.yaml SHALL 支持可选的 `session_sticky` 布尔字段（默认 False），WHEN 设为 True 时，THE FallbackChain SHALL 在同一会话内优先使用上次成功的 AuthProfile

### 需求 3：L1 工具结果写入时截断

**用户故事：** 作为开发者，我希望工具返回的超大结果在写入消息列表时被自动截断，以防止单次工具调用占用过多上下文窗口。

#### 验收标准

1. THE action_node SHALL 在将 ToolMessage 添加到消息列表前，对 ToolMessage 的 content 进行长度检查
2. WHEN ToolMessage 的 content 长度超过配置的 `tool_result_max_chars`（默认 30000 字符）时，THE action_node SHALL 截断 content，保留前 `head_chars`（默认 12000）字符和后 `tail_chars`（默认 8000）字符，中间插入截断后缀
3. THE 截断后缀 SHALL 包含原始内容长度和截断信息，格式为 `\n\n[... truncated {original_length} chars, showing first {head_chars} + last {tail_chars} ...]\n\n`
4. THE L1 截断配置 SHALL 支持按工具名称设置不同的截断阈值（`tool_overrides` 字典），允许特定工具使用更大或更小的截断限制
5. WHEN 工具名称在 `tool_overrides` 中有对应配置时，THE action_node SHALL 使用该工具的专属截断阈值替代全局默认值
6. THE L1 截断逻辑 SHALL 封装在独立的 `ToolResultGuard` 类中（新文件 `smartclaw/memory/tool_result_guard.py`），action_node 通过调用 ToolResultGuard 实例方法执行截断

### 需求 4：L2 会话裁剪

**用户故事：** 作为开发者，我希望在每次 LLM 调用前对消息列表进行智能裁剪，移除或压缩不重要的历史消息，以在不触发全量压缩的情况下控制上下文大小。

#### 验收标准

1. THE reasoning_node SHALL 在调用 LLM 前，通过 SessionPruner 对当前消息列表执行裁剪
2. THE SessionPruner SHALL 实现两级裁剪策略：软裁剪（soft-trim）保留消息的头部和尾部内容，硬清除（hard-clear）将消息内容替换为占位符文本
3. WHEN 消息列表的估算 Token 数超过 `soft_trim_threshold`（默认为 context_window 的 50%）时，THE SessionPruner SHALL 对超出部分的 ToolMessage 执行软裁剪，保留前 500 字符和后 300 字符
4. WHEN 消息列表的估算 Token 数超过 `hard_clear_threshold`（默认为 context_window 的 70%）时，THE SessionPruner SHALL 对超出部分的 ToolMessage 执行硬清除，将 content 替换为 `[tool result cleared - {tool_name}]`
5. THE SessionPruner SHALL 支持 `tool_allow_list` 和 `tool_deny_list` 配置，allow_list 中的工具结果永远不被裁剪，deny_list 中的工具结果优先被裁剪
6. THE SessionPruner SHALL 从消息列表的中间位置开始裁剪，保留最近的 `keep_recent`（默认 5）条消息和最早的 `keep_head`（默认 2）条消息不被裁剪
7. THE SessionPruner 逻辑 SHALL 封装在独立的 `SessionPruner` 类中（新文件 `smartclaw/memory/pruning.py`）

### 需求 5：L3 预压缩记忆刷新

**用户故事：** 作为开发者，我希望在执行上下文压缩前，系统自动发起一次静默 LLM 调用，将当前对话中的关键上下文（文件路径、变量名、决策要点）持久化到 MemoryStore 摘要中，以防止压缩过程丢失重要信息。

#### 验收标准

1. WHEN L4 多阶段压缩被触发前，THE AutoSummarizer SHALL 执行一次 L3 预压缩记忆刷新
2. THE L3 记忆刷新 SHALL 向 LLM 发送一个专用 prompt，要求 LLM 从当前消息列表中提取关键标识符（文件路径、变量名、函数名）、决策要点和未完成任务，生成结构化摘要
3. THE L3 记忆刷新生成的摘要 SHALL 通过 MemoryStore.set_summary 持久化，与现有摘要合并（追加到现有摘要末尾，以 `\n\n---\n\n` 分隔）
4. IF L3 记忆刷新的 LLM 调用失败，THEN THE AutoSummarizer SHALL 记录警告日志并继续执行 L4 压缩，不中断压缩流程
5. THE L3 记忆刷新 SHALL 使用与 L4 压缩相同的 CompactionModel 配置（如果已配置），否则使用主模型

### 需求 6：L4 多阶段压缩

**用户故事：** 作为开发者，我希望上下文压缩采用多阶段分块策略，支持渐进回退、标识符保留和溢出自动恢复，以替代当前 AutoSummarizer 的简单摘要方式，提供更可靠的压缩效果。

#### 验收标准

1. THE L4 压缩 SHALL 将待压缩消息按 `chunk_max_tokens`（默认 4000 Token）分块，每个块在 turn boundary（HumanMessage）处切分，确保不拆分工具调用序列
2. THE L4 压缩 SHALL 对每个块顺序调用 LLM 生成摘要，后续块的摘要 prompt 包含前序块的摘要作为上下文
3. WHEN 单个块的摘要结果超过 `part_max_tokens`（默认 2000 Token）时，THE L4 压缩 SHALL 将该块拆分为多个子块，分别生成部分摘要，然后合并部分摘要为最终块摘要
4. THE L4 压缩 SHALL 实现渐进回退策略：首先尝试完整压缩 → 如果压缩后仍超出上下文窗口，则过滤掉超大 ToolMessage → 如果仍超出，则使用硬编码回退文本替换全部历史
5. THE L4 压缩 SHALL 支持 `identifier_policy` 配置（strict/custom/off）：strict 模式在摘要 prompt 中要求 LLM 保留所有文件路径、变量名、函数名；custom 模式允许用户指定需要保留的标识符模式列表；off 模式不添加标识符保留指令
6. THE L4 压缩 SHALL 支持 `compaction_model` 配置，允许指定与主模型不同的 LLM 执行压缩任务（格式为 "provider/model"），未配置时使用主模型
7. WHEN L4 压缩完成后上下文仍超出窗口限制时，THE L4 压缩 SHALL 执行溢出自动恢复：最多重试 3 次，每次重试间隔按指数退避（1s、2s、4s），每次重试使用更激进的压缩参数（chunk_max_tokens 减半）
8. WHEN reasoning_node 检测到 LLM 返回上下文溢出错误（HTTP 400 且包含 "context"、"token"、"length" 等关键词）时，THE reasoning_node SHALL 触发 force_compression，然后重试当前 LLM 调用
9. THE L4 压缩 SHALL 增强现有 AutoSummarizer 类，在 `maybe_summarize` 方法中集成 L3 + L4 逻辑，替代当前的简单摘要实现

### 需求 7：L5 ContextEngine 插件架构

**用户故事：** 作为平台开发者，我希望上下文管理逻辑通过插件接口解耦，以便未来替换或扩展上下文引擎（如接入向量数据库、外部记忆服务），而不影响 Agent 核心循环。

#### 验收标准

1. THE ContextEngine 接口 SHALL 定义以下抽象方法：`bootstrap(session_key, system_prompt)` 初始化引擎、`ingest(message)` 接收新消息、`assemble()` 组装 LLM 调用上下文、`after_turn(messages)` 每轮结束后处理、`compact(force)` 执行压缩、`maintain()` 后台维护、`dispose()` 释放资源
2. THE ContextEngine 接口 SHALL 定义 Sub-Agent 生命周期钩子：`prepare_subagent_spawn(task, parent_context)` 在 Sub-Agent 创建前准备上下文、`on_subagent_ended(task, result)` 在 Sub-Agent 完成后处理结果
3. THE LegacyContextEngine SHALL 实现 ContextEngine 接口，将现有 AutoSummarizer 的 build_context、maybe_summarize、force_compression 逻辑封装为对应的 assemble、after_turn、compact 方法
4. THE ContextEngine 插件 SHALL 通过 `ContextEngineRegistry` 注册和获取，支持按名称注册自定义引擎实现
5. THE agent graph（build_graph 和 invoke）SHALL 通过 ContextEngine 接口调用上下文管理方法，替代直接调用 AutoSummarizer
6. WHEN config.yaml 中未指定 `context_engine` 配置时，THE 系统 SHALL 默认使用 LegacyContextEngine
7. THE ContextEngine 相关代码 SHALL 放置在新目录 `smartclaw/context_engine/` 下，包含 `interface.py`（接口定义）、`legacy.py`（默认实现）、`registry.py`（注册中心）

### 需求 8：会话级模型覆盖与 Token 统计

**用户故事：** 作为 API 调用方，我希望为特定会话持久化设置模型覆盖和查看 Token 使用统计，以便对不同会话使用不同模型并监控资源消耗。

#### 验收标准

1. THE MemoryStore SHALL 新增 `session_config` 表，存储每个会话的配置信息，包含 `session_key`（主键）、`model_override`（可选的模型引用字符串）、`config_json`（JSON 格式的扩展配置）、`updated_at`（更新时间戳）
2. THE Gateway SHALL 提供 `PUT /api/sessions/{key}/config` 端点，接受 JSON body 包含可选的 `model` 字段（模型引用字符串），将模型覆盖持久化到 MemoryStore 的 session_config 表
3. WHEN chat 端点处理请求时，IF 请求未指定 model 字段，THEN THE chat 端点 SHALL 查询 MemoryStore 的 session_config 表获取该会话的 model_override，如果存在则使用该模型
4. THE AgentState SHALL 新增 `token_stats` 字段（TypedDict），包含 `prompt_tokens`（输入 Token 数）、`completion_tokens`（输出 Token 数）、`total_tokens`（总 Token 数），每次 LLM 调用后累加
5. THE reasoning_node SHALL 在每次 LLM 调用后从 AIMessage 的 `usage_metadata` 中提取 Token 使用信息，累加到 AgentState 的 token_stats 中
6. THE ChatResponse SHALL 新增可选的 `token_stats` 字段，返回本次请求的 Token 使用统计
7. WHEN AIMessage 不包含 `usage_metadata` 时，THE reasoning_node SHALL 使用 AutoSummarizer 的 estimate_tokens 方法进行估算

### 需求 9：Sub-Agent Fallback 继承与 EphemeralStore 轻量压缩

**用户故事：** 作为开发者，我希望 Sub-Agent 继承父 Agent 的 fallback 配置（而非当前的空 fallbacks 列表），并在 EphemeralStore 消息过多时执行轻量压缩，以提高 Sub-Agent 的可靠性和上下文利用效率。

#### 验收标准

1. THE SpawnSubAgentTool SHALL 接受父 Agent 的 ModelConfig 作为构造参数，在创建 SubAgentConfig 时将父 Agent 的 fallbacks 列表传递给 Sub-Agent
2. WHEN Sub-Agent 的 ModelConfig 被构建时，THE SubAgentConfig SHALL 使用父 Agent 的 fallbacks 列表（而非当前的空列表 `[]`），除非 Sub-Agent 显式指定了不同的 fallbacks
3. THE EphemeralStore SHALL 支持可选的轻量压缩：WHEN 消息数量超过 `compact_threshold`（默认 max_size 的 80%）时，THE EphemeralStore SHALL 对中间的 ToolMessage 执行 L2 风格的软裁剪
4. THE L1 工具结果截断和 L2 会话裁剪 SHALL 自然应用于 Sub-Agent，因为 Sub-Agent 共享相同的 action_node 和 reasoning_node 实现
5. THE ContextEngine 接口的 `prepare_subagent_spawn` 和 `on_subagent_ended` 钩子 SHALL 在 spawn_sub_agent 函数中被调用（如果 ContextEngine 实例可用）

### 需求 10：CooldownTracker 状态持久化

**用户故事：** 作为运维人员，我希望 CooldownTracker 的冷却状态在进程重启后能够恢复，以避免重启后立即重试已知限流的提供商/AuthProfile。

#### 验收标准

1. THE MemoryStore SHALL 新增 `cooldown_state` 表，存储每个 profile_id 的冷却状态，包含 `profile_id`（主键）、`error_count`（错误计数）、`cooldown_end_utc`（冷却截止 UTC 时间戳）、`last_failure_utc`（最后失败 UTC 时间戳）、`failure_counts_json`（各失败原因计数的 JSON）
2. THE CooldownTracker SHALL 提供 `save_state(store)` 异步方法，将当前所有冷却条目序列化并写入 MemoryStore 的 cooldown_state 表
3. THE CooldownTracker SHALL 提供 `restore_state(store)` 异步方法，从 MemoryStore 的 cooldown_state 表读取冷却状态并恢复到内存
4. WHEN CooldownTracker.mark_failure 或 CooldownTracker.mark_success 被调用时，THE CooldownTracker SHALL 异步调用 save_state 将变更持久化（使用 fire-and-forget 模式，不阻塞主流程）
5. WHEN SmartClaw 启动时（setup_agent_runtime 中），THE CooldownTracker SHALL 调用 restore_state 从 MemoryStore 恢复冷却状态
6. THE CooldownTracker 的 restore_state SHALL 将持久化的 UTC 时间戳转换为 monotonic 时间偏移量，正确恢复冷却剩余时间
7. IF cooldown_state 表中的某条记录的 cooldown_end_utc 已过期（早于当前 UTC 时间），THEN THE restore_state SHALL 跳过该记录，不恢复已过期的冷却状态
