# Implementation Plan: SmartClaw P1 增强能力

## Overview

实现 SmartClaw P1 阶段 6 个增强模块：记忆存储（Memory Store）、自动摘要（Auto Summary）、技能加载器（Skills Loader）、技能注册表（Skills Registry）、子 Agent（Sub-Agent）、多 Agent 协同（Multi-Agent Coordination）。

所有新代码位于 `smartclaw/smartclaw/memory/`、`smartclaw/smartclaw/skills/`、`smartclaw/smartclaw/agent/`（新增文件），测试位于 `smartclaw/tests/memory/`、`smartclaw/tests/skills/`、`smartclaw/tests/agent/`（新增文件）。需新增 `aiosqlite` 依赖到 `pyproject.toml`。

实现按依赖顺序推进：MemoryStore → AutoSummarizer → Memory-Agent 集成 → Skills 模型/加载器 → Skills 注册表 → SubAgent → MultiAgent → 配置集成 → 最终集成与向后兼容验证。

## Tasks

- [x] 1. 项目脚手架与 MemoryStore 基础
  - [x] 1.1 添加 `aiosqlite` 依赖并创建 memory 包结构
    - 在 `pyproject.toml` 的 `[project.dependencies]` 中添加 `aiosqlite>=0.20.0`
    - 创建 `smartclaw/smartclaw/memory/__init__.py` 导出 `MemoryStore`, `AutoSummarizer`
    - 创建 `smartclaw/tests/memory/__init__.py` 测试包
    - _Requirements: 1.12_

  - [x] 1.2 实现 `MemoryStore` 核心类 (`smartclaw/smartclaw/memory/store.py`)
    - 实现 `__init__(db_path)` 接受可配置数据库路径，默认 `~/.smartclaw/memory.db`
    - 实现 `initialize()` 异步方法：创建数据库文件、messages 表和 summaries 表（含索引）
    - 实现 `add_message(session_key, role, content)` 追加简单文本消息
    - 实现 `add_full_message(session_key, message)` 追加完整 BaseMessage（含 tool_calls、tool_call_id）
    - 实现 `get_history(session_key)` 返回按插入顺序排列的 BaseMessage 列表，不存在返回空列表
    - 实现 `get_summary(session_key)` 返回摘要字符串，不存在返回空字符串
    - 实现 `set_summary(session_key, summary)` 设置/更新摘要
    - 实现 `truncate_history(session_key, keep_last)` 保留最后 N 条，keep_last<=0 清空全部
    - 实现 `set_history(session_key, messages)` 原子替换会话全部消息
    - 实现 `close()` 释放 SQLite 连接
    - 使用 `message_to_dict` / `messages_from_dict` 序列化/反序列化 BaseMessage
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 1.12, 1.13, 1.14, 1.15_

  - [x] 1.3 编写属性测试：消息存储往返 (`tests/memory/test_store_props.py`)
    - **Property 1: 消息存储往返 (Message Storage Round-Trip)**
    - 对任意 session_key 和 (role, content) 序列，add_message 后 get_history 返回相同顺序和内容
    - **Validates: Requirements 1.1, 1.2**

  - [x] 1.4 编写属性测试：完整消息序列化往返 (`tests/memory/test_store_props.py`)
    - **Property 2: 完整消息序列化往返 (Full Message Serialization Round-Trip)**
    - 对任意 BaseMessage（HumanMessage、AIMessage with tool_calls、ToolMessage with tool_call_id），add_full_message 后 get_history 返回等价消息
    - **Validates: Requirements 1.9, 1.15**

  - [x] 1.5 编写属性测试：摘要存取往返 (`tests/memory/test_store_props.py`)
    - **Property 3: 摘要存取往返 (Summary Round-Trip)**
    - 对任意 session_key 和非空 summary 字符串，set_summary 后 get_summary 返回完全相同的字符串
    - **Validates: Requirements 1.4, 1.6**

  - [x] 1.6 编写属性测试：历史截断保留最近消息 (`tests/memory/test_store_props.py`)
    - **Property 4: 历史截断保留最近消息 (Truncate Preserves Recent Messages)**
    - 对任意 N 条消息和 keep_last (1 <= keep_last < N)，truncate_history 后 get_history 返回最后 keep_last 条
    - **Validates: Requirements 1.7**

  - [x] 1.7 编写属性测试：历史替换往返 (`tests/memory/test_store_props.py`)
    - **Property 5: 历史替换往返 (Set History Round-Trip)**
    - 对任意 session_key 和 BaseMessage 列表，set_history 后 get_history 返回等价列表
    - **Validates: Requirements 1.10**

  - [x] 1.8 编写单元测试 (`tests/memory/test_store.py`)
    - 测试空会话 get_history 返回空列表 (Req 1.3)
    - 测试空摘要 get_summary 返回空字符串 (Req 1.5)
    - 测试 keep_last<=0 清空全部消息 (Req 1.8)
    - 测试数据库文件自动创建 (Req 1.14)
    - 测试 close 后资源释放
    - _Requirements: 1.3, 1.5, 1.8, 1.14_

- [x] 2. Checkpoint — 确认 MemoryStore 测试通过
  - Ensure all tests pass, ask the user if questions arise.

- [x] 3. AutoSummarizer — 自动摘要
  - [x] 3.1 实现 `AutoSummarizer` 类 (`smartclaw/smartclaw/memory/summarizer.py`)
    - 实现 `__init__(store, model_config, *, message_threshold, token_percent_threshold, context_window, keep_recent)`
    - 实现 `estimate_tokens(messages)` 启发式 token 估算（2.5 字符/token）
    - 实现 `find_safe_boundary(messages, target_index)` 找到最近的 turn 边界（user 消息起始位置）
    - 实现 `maybe_summarize(session_key, messages)` 检查消息数和 token 百分比双阈值，超过时调用 LLM 生成摘要
    - 摘要完成后调用 `store.set_summary` 存储摘要，调用 `store.truncate_history` 保留最近 keep_recent 条消息
    - 已有摘要时在 LLM prompt 中包含旧摘要实现增量摘要
    - LLM 调用失败时 structlog 记录错误，跳过摘要返回原始消息列表
    - 实现 `force_compression(session_key, messages)` 紧急压缩：丢弃最旧 ~50% 消息对齐 turn 边界
    - 少于 4 条消息时跳过压缩；无安全边界时保留最近 user 消息
    - 压缩后通过 `store.set_history` 替换会话历史，通过 `store.set_summary` 记录压缩说明
    - 实现 `build_context(session_key, messages, system_prompt)` 在消息列表前插入摘要 SystemMessage
    - 使用与主 Agent 相同的 ModelConfig 和 FallbackChain 调用 LLM
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11, 2.12, 2.13_

  - [x] 3.2 编写属性测试：摘要触发阈值 (`tests/memory/test_summarizer_props.py`)
    - **Property 6: 摘要触发阈值 (Summarization Trigger Threshold)**
    - 对任意消息列表和阈值配置，maybe_summarize 当且仅当消息数超过 message_threshold 或 token 估算超过 token_percent_threshold 时触发
    - **Validates: Requirements 2.3, 2.8**

  - [x] 3.3 编写属性测试：摘要后保留最近消息数 (`tests/memory/test_summarizer_props.py`)
    - **Property 7: 摘要后保留最近消息数 (Keep Recent After Summarization)**
    - 对任意触发摘要的消息列表（keep_recent=K），摘要完成后剩余历史恰好包含 K 条最近消息
    - **Validates: Requirements 2.6**

  - [x] 3.4 编写属性测试：摘要上下文构建 (`tests/memory/test_summarizer_props.py`)
    - **Property 8: 摘要上下文构建 (Summary Context Prepend)**
    - 对任意有非空摘要的会话和消息列表，build_context 返回的列表中摘要 SystemMessage 出现在所有非系统消息之前
    - **Validates: Requirements 2.10**

  - [x] 3.5 编写属性测试：强制压缩对齐 Turn 边界 (`tests/memory/test_summarizer_props.py`)
    - **Property 9: 强制压缩对齐 Turn 边界 (Force Compression Turn Boundary Alignment)**
    - 对任意 >= 4 条消息且含至少 2 个 turn 边界的列表，force_compression 丢弃约 50% 消息，保留部分从 user 消息开始
    - **Validates: Requirements 2.11**

  - [x] 3.6 编写单元测试 (`tests/memory/test_summarizer.py`)
    - 测试 LLM 调用失败时跳过摘要返回原始消息 (Req 2.9)
    - 测试少于 4 条消息时 force_compression 跳过 (Req 2.12)
    - 测试无安全 turn 边界时回退保留最近 user 消息 (Req 2.13)
    - 测试增量摘要包含旧摘要 (Req 2.7)
    - 测试 token 百分比阈值触发 (Req 2.2)
    - _Requirements: 2.2, 2.7, 2.9, 2.12, 2.13_

- [x] 4. Memory-Agent 集成
  - [x] 4.1 扩展 `AgentState` 添加 P1 可选字段 (`smartclaw/smartclaw/agent/state.py`)
    - 添加 `session_key: str | None = None`
    - 添加 `summary: str | None = None`
    - 添加 `sub_agent_depth: int | None = None`
    - 所有新字段默认 None，保持与 P0 graph nodes 的向后兼容
    - _Requirements: 14.3_

  - [x] 4.2 扩展 `invoke` 函数支持 memory 集成 (`smartclaw/smartclaw/agent/graph.py`)
    - `invoke` 新增可选 `session_key` 参数
    - 当 session_key 提供且 memory 启用时：从 MemoryStore 加载历史，通过 AutoSummarizer.build_context 构建上下文
    - 每轮完成后通过 add_full_message 持久化新消息
    - 每轮完成后调用 maybe_summarize 检查摘要触发
    - session_key 未提供时保持 P0 无状态行为
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [x] 4.3 编写单元测试 (`tests/agent/test_memory_integration.py`)
    - 测试 session_key 未提供时无状态行为与 P0 一致 (Req 4.5)
    - 测试 session_key 提供时加载历史和摘要 (Req 4.1)
    - 测试每轮消息持久化 (Req 4.2)
    - 测试摘要触发检查 (Req 4.3)
    - _Requirements: 4.1, 4.2, 4.3, 4.5_

- [x] 5. Checkpoint — 确认 Memory 模块全部测试通过
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Skills 数据模型与加载器
  - [x] 6.1 创建 skills 包结构并实现数据模型 (`smartclaw/smartclaw/skills/models.py`)
    - 创建 `smartclaw/smartclaw/skills/__init__.py` 导出 `SkillsLoader`, `SkillsRegistry`, `SkillDefinition`, `SkillInfo`
    - 创建 `smartclaw/tests/skills/__init__.py` 测试包
    - 实现 `SkillDefinition` dataclass：name (kebab-case, max 64), description (max 1024), entry_point, version, author, tools, parameters
    - 实现 `ToolDef` dataclass：name, description, function
    - 实现 `SkillInfo` dataclass：name, path, source, description
    - 实现 `SkillDefinition.validate()` 返回验证错误列表
    - 验证 name 匹配 `^[a-zA-Z0-9]+(-[a-zA-Z0-9]+)*$`，长度 <= 64，description <= 1024，必填字段非空
    - _Requirements: 5.4, 5.5, 5.7, 5.8_

  - [x] 6.2 实现 `SkillsLoader` 类 (`smartclaw/smartclaw/skills/loader.py`)
    - 实现 `__init__(workspace_dir, global_dir, builtin_dir)` 接受三级技能目录
    - 实现 `list_skills()` 扫描目录发现 `{skill_name}/skill.yaml`，按优先级 workspace > global > builtin 去重
    - 实现 `load_skill(name)` 通过 `importlib.import_module` 动态加载 entry_point，返回 (callable, SkillDefinition)
    - 实现 `build_skills_summary()` 生成技能摘要字符串（name + description + source）
    - 实现 `load_skills_for_context(skill_names)` 加载多个技能内容拼接
    - 实现 `parse_skill_yaml(yaml_str)` 静态方法解析 YAML 为 SkillDefinition
    - 实现 `serialize_skill_yaml(definition)` 静态方法序列化 SkillDefinition 为 YAML
    - 无效 YAML 或验证失败时 structlog 记录警告并跳过
    - entry_point 导入失败时抛出描述性 ImportError
    - _Requirements: 5.1, 5.2, 5.3, 5.6, 5.7, 5.8, 5.9, 5.10, 5.11, 5.12, 5.13, 5.14, 6.1, 6.2, 6.3_

  - [x] 6.3 编写属性测试：技能目录优先级 (`tests/skills/test_loader_props.py`)
    - **Property 10: 技能目录优先级 (Skill Directory Priority)**
    - 对任意同名技能存在于多个目录，list_skills 仅返回最高优先级源
    - **Validates: Requirements 5.2, 5.3**

  - [x] 6.4 编写属性测试：技能定义验证 (`tests/skills/test_loader_props.py`)
    - **Property 11: 技能定义验证 (Skill Definition Validation)**
    - 对任意 SkillDefinition，name 不匹配模式、超长、description 超长、必填字段缺失时 validate() 返回非空错误列表
    - **Validates: Requirements 5.4, 5.8**

  - [x] 6.5 编写属性测试：技能摘要包含所有技能信息 (`tests/skills/test_loader_props.py`)
    - **Property 12: 技能摘要包含所有技能信息 (Skills Summary Contains All Skills)**
    - 对任意有效技能集合，build_skills_summary 返回的字符串包含每个技能的 name 和 description
    - **Validates: Requirements 5.13**

  - [x] 6.6 编写属性测试：技能定义 YAML 往返 (`tests/skills/test_loader_props.py`)
    - **Property 13: 技能定义 YAML 往返 (Skill Definition YAML Round-Trip)**
    - 对任意有效 SkillDefinition，serialize_skill_yaml 后 parse_skill_yaml 返回等价对象
    - **Validates: Requirements 6.3**

  - [x] 6.7 编写单元测试 (`tests/skills/test_loader.py`)
    - 测试无效 YAML 跳过并记录警告 (Req 5.6)
    - 测试必填字段缺失跳过 (Req 5.7)
    - 测试 entry_point 导入失败抛出 ImportError (Req 5.11)
    - 测试技能目录不存在时静默跳过
    - _Requirements: 5.6, 5.7, 5.11_

- [x] 7. Skills Registry — 技能注册表
  - [x] 7.1 实现 `SkillsRegistry` 类 (`smartclaw/smartclaw/skills/registry.py`)
    - 实现 `__init__(loader, tool_registry)` 接受 SkillsLoader 和 ToolRegistry
    - 实现 `register(name, module)` 注册技能模块，提取并注册其提供的 BaseTool 到 ToolRegistry
    - 实现 `unregister(name)` 注销技能，从 ToolRegistry 移除其工具
    - 实现 `get(name)` 按名称获取已注册技能，不存在返回 None
    - 实现 `list_skills()` 返回排序的技能名称列表
    - 实现 `load_and_register_all()` 发现并加载所有技能，单个失败不影响其余
    - 当 entry_point 返回 `list[BaseTool]` 时注册这些工具
    - 注册失败时 structlog 记录错误并继续
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9_

  - [x] 7.2 编写属性测试：技能注册/获取往返 (`tests/skills/test_registry_props.py`)
    - **Property 14: 技能注册/获取往返 (Skill Register/Get Round-Trip)**
    - 对任意 skill name 和 module，register 后 get 返回该 module；未注册的 name 返回 None
    - **Validates: Requirements 7.1, 7.3**

  - [x] 7.3 编写属性测试：技能注销移除技能及工具 (`tests/skills/test_registry_props.py`)
    - **Property 15: 技能注销移除技能及工具 (Unregister Removes Skill and Tools)**
    - 对任意已注册技能及其工具，unregister 后 get 返回 None，工具不再出现在 ToolRegistry
    - **Validates: Requirements 7.2, 7.6**

  - [x] 7.4 编写属性测试：技能列表排序 (`tests/skills/test_registry_props.py`)
    - **Property 16: 技能列表排序 (Skill List Sorted)**
    - 对任意已注册技能集合，list_skills 返回升序排列的名称列表
    - **Validates: Requirements 7.4**

  - [x] 7.5 编写单元测试 (`tests/skills/test_registry.py`)
    - 测试注册失败时继续注册其余技能 (Req 7.9)
    - 测试重复注册同名技能覆盖旧注册
    - 测试 load_and_register_all 集成流程 (Req 7.7)
    - _Requirements: 7.7, 7.9_

- [x] 8. Checkpoint — 确认 Skills 模块全部测试通过
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. SubAgent — 子 Agent 与 EphemeralStore
  - [x] 9.1 实现 `EphemeralStore` 和 `SubAgentConfig` (`smartclaw/smartclaw/agent/sub_agent.py`)
    - 实现 `SubAgentConfig` dataclass：task, model, tools, system_prompt, max_iterations, timeout_seconds, max_depth
    - 实现 `EphemeralStore` 内存临时消息存储：add_message, get_history, truncate, set_history
    - EphemeralStore 接受 `max_size` 参数（默认 50），超过时自动截断保留最近消息
    - _Requirements: 9.2, 9.3, 9.12, 9.13_

  - [x] 9.2 实现 `spawn_sub_agent` 异步函数 (`smartclaw/smartclaw/agent/sub_agent.py`)
    - 接受 SubAgentConfig、parent_depth、semaphore、concurrency_timeout 参数
    - 深度检查：parent_depth >= max_depth 时返回深度限制错误
    - 并发控制：通过 asyncio.Semaphore 限制并发数，等待超时返回并发限制错误
    - 使用 `build_graph` 构建子 Agent SubGraph，配置 EphemeralStore
    - 通过 `asyncio.timeout` 实现超时控制，超时时取消执行返回超时错误
    - 执行异常时捕获并 structlog 记录错误，返回错误描述字符串
    - 记录 parent-child 关系用于可观测性
    - _Requirements: 9.1, 9.4, 9.5, 9.6, 9.7, 9.8, 9.11, 10.1, 10.2, 10.3_

  - [x] 9.3 实现 `SpawnSubAgentTool` LangChain BaseTool (`smartclaw/smartclaw/agent/sub_agent.py`)
    - name="spawn_sub_agent"，接受 task (str) 和可选 model (str) 参数
    - `_arun` 调用 spawn_sub_agent，返回子 Agent 最终响应字符串
    - `_run` 抛出 NotImplementedError
    - _Requirements: 9.9, 9.10_

  - [x] 9.4 编写属性测试：子 Agent 深度限制 (`tests/agent/test_sub_agent_props.py`)
    - **Property 17: 子 Agent 深度限制 (Sub-Agent Depth Limit)**
    - 对任意 parent_depth >= max_depth 的 spawn 请求，spawn_sub_agent 返回深度限制错误而不派生子 Agent
    - **Validates: Requirements 9.6, 9.7**

  - [x] 9.5 编写属性测试：临时存储自动截断 (`tests/agent/test_sub_agent_props.py`)
    - **Property 18: 临时存储自动截断 (Ephemeral Store Auto-Truncation)**
    - 对任意消息序列和 max_size=M 的 EphemeralStore，存储永远不超过 M 条消息，超限时保留最近 M 条
    - **Validates: Requirements 9.13**

  - [x] 9.6 编写属性测试：子 Agent 并发限制 (`tests/agent/test_sub_agent_props.py`)
    - **Property 19: 子 Agent 并发限制 (Sub-Agent Concurrency Limit)**
    - 对任意超过 max_concurrent 的并发 spawn_sub_agent 调用，同时执行的子 Agent 不超过 max_concurrent
    - **Validates: Requirements 10.1, 10.2**

  - [x] 9.7 编写单元测试 (`tests/agent/test_sub_agent.py`)
    - 测试超时取消执行返回超时错误 (Req 9.5)
    - 测试 SubAgentConfig 缺少 task/model 时报错
    - 测试并发等待超时返回错误 (Req 10.3)
    - 测试执行异常捕获并返回错误描述 (Req 9.11)
    - 测试 EphemeralStore 不污染父 Agent 持久化记忆 (Req 9.12)
    - _Requirements: 9.5, 9.11, 9.12, 10.3_

- [x] 10. Checkpoint — 确认 SubAgent 测试通过
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. MultiAgentCoordinator — 多 Agent 协同
  - [x] 11.1 实现 `AgentRole` 和 `MultiAgentState` 数据模型 (`smartclaw/smartclaw/agent/multi_agent.py`)
    - 实现 `AgentRole` dataclass：name, description, model, tools, system_prompt, max_iterations
    - 实现 `MultiAgentState` TypedDict：messages, current_agent, task_plan, agent_results, total_iterations, max_total_iterations, final_answer, error
    - _Requirements: 12.2, 12.3_

  - [x] 11.2 实现 `MultiAgentCoordinator` 类 (`smartclaw/smartclaw/agent/multi_agent.py`)
    - 实现 `__init__(roles, *, max_total_iterations, memory_store)` 接受角色列表和配置
    - 实现 `create_multi_agent_graph()` 构建 LangGraph StateGraph：Supervisor 节点 + 各专业 Agent 节点 + 条件路由
    - Supervisor 模式：接收任务 → 分解子任务 → 分配给专业 Agent → 综合结果
    - 使用 LangGraph conditional routing 根据 Supervisor 决策路由到对应 Agent
    - 专业 Agent 完成后结果返回 Supervisor 评估
    - 全局迭代计数，达到 max_total_iterations 时终止并返回最佳部分结果 + 警告
    - 共享 MemoryStore 实例跨所有 Agent
    - 专业 Agent 失败时向 Supervisor 报告，Supervisor 可重新分配
    - 实现 `invoke(user_message, *, session_key)` 执行多 Agent 协同任务
    - _Requirements: 12.1, 12.4, 12.5, 12.6, 12.7, 12.8, 12.9, 12.10_

  - [x] 11.3 编写属性测试：多 Agent 全局迭代上限 (`tests/agent/test_multi_agent_props.py`)
    - **Property 20: 多 Agent 全局迭代上限 (Multi-Agent Total Iteration Limit)**
    - 对任意 max_total_iterations=N 的多 Agent 执行，所有 Agent 的总迭代次数不超过 N
    - **Validates: Requirements 12.7**

  - [x] 11.4 编写单元测试 (`tests/agent/test_multi_agent.py`)
    - 测试全局迭代上限达到时终止并返回部分结果 (Req 12.8)
    - 测试专业 Agent 失败时向 Supervisor 报告 (Req 12.10)
    - 测试无可用 Agent 角色时抛出 ValueError
    - 测试共享 MemoryStore 跨 Agent 访问 (Req 12.9)
    - _Requirements: 12.7, 12.8, 12.9, 12.10_

- [x] 12. Checkpoint — 确认 MultiAgent 测试通过
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. 配置集成 — 扩展 SmartClawSettings
  - [x] 13.1 实现 P1 配置模型并扩展 SmartClawSettings (`smartclaw/smartclaw/config/settings.py`)
    - 实现 `MemorySettings(BaseSettings)`: enabled, db_path, summary_threshold, keep_recent, summarize_token_percent, context_window
    - 实现 `SkillsSettings(BaseSettings)`: enabled, workspace_dir, global_dir
    - 实现 `SubAgentSettings(BaseSettings)`: enabled, max_depth, max_concurrent, default_timeout_seconds, concurrency_timeout_seconds
    - 实现 `AgentRoleConfig(BaseSettings)`: name, description, model, system_prompt, tools
    - 实现 `MultiAgentSettings(BaseSettings)`: enabled (default False), max_total_iterations, roles
    - 在 `SmartClawSettings` 中添加 `memory`, `skills`, `sub_agent`, `multi_agent` 字段
    - 支持环境变量覆盖：`SMARTCLAW_MEMORY__*`, `SMARTCLAW_SKILLS__*`, `SMARTCLAW_SUB_AGENT__*`, `SMARTCLAW_MULTI_AGENT__*`
    - _Requirements: 3.1, 3.2, 3.3, 8.1, 8.2, 8.3, 11.1, 11.2, 11.3, 13.1, 13.2, 13.3, 13.4_

  - [x] 13.2 编写单元测试 (`tests/config/test_p1_settings.py`)
    - 测试所有 P1 配置字段默认值正确 (Req 3.1, 8.1, 11.1, 13.1)
    - 测试环境变量覆盖生效 (Req 3.3, 8.3, 11.3, 13.4)
    - 测试 memory.enabled=False 时 Agent Graph 跳过 memory 加载 (Req 3.2)
    - 测试 skills.enabled=False 时跳过技能加载 (Req 8.2)
    - 测试 sub_agent.enabled=False 时不注册 spawn_sub_agent_tool (Req 11.2)
    - 测试 multi_agent.enabled=False 时系统以单 Agent 模式运行 (Req 13.3)
    - _Requirements: 3.1, 3.2, 3.3, 8.1, 8.2, 8.3, 11.1, 11.2, 11.3, 13.1, 13.3, 13.4_

- [x] 14. 最终集成与向后兼容验证
  - [x] 14.1 集成 Skills 到 Agent Graph (`smartclaw/smartclaw/agent/graph.py`)
    - 当 skills.enabled 时，在 `create_all_tools` 中通过 SkillsRegistry.load_and_register_all 加载技能工具
    - 将技能摘要注入 system prompt（通过 build_skills_summary）
    - skills.enabled=False 时跳过，保持 P0 行为
    - _Requirements: 8.2, 5.13_

  - [x] 14.2 集成 SubAgent tool 到 Agent Graph (`smartclaw/smartclaw/agent/graph.py`)
    - 当 sub_agent.enabled 时，创建 SpawnSubAgentTool 并注册到 ToolRegistry
    - 传递 SubAgentSettings 配置（max_depth, max_concurrent, timeout 等）
    - sub_agent.enabled=False 时不注册该工具
    - _Requirements: 11.2, 9.9_

  - [x] 14.3 向后兼容验证
    - 确认所有 P1 模块禁用时（memory/skills/sub_agent/multi_agent 全部 enabled=False），系统行为与 P0 完全一致
    - 确认 P1 模块未修改任何 P0 模块接口（AgentState 仅添加可选字段、build_graph 签名不变、ToolRegistry 接口不变）
    - 确认 P1 模块可独立导入，使用 lazy import 处理可选依赖
    - _Requirements: 14.1, 14.2, 14.3, 14.4_

  - [x] 14.4 编写向后兼容集成测试 (`tests/test_p1_backward_compat.py`)
    - 测试所有 P1 开关关闭时 invoke 行为与 P0 一致 (Req 14.1)
    - 测试 AgentState 新字段默认 None 不影响现有 graph nodes (Req 14.3)
    - 测试 P1 模块独立导入不报错 (Req 14.4)
    - 测试 SmartClawSettings 现有 P0 字段未被修改 (Req 14.2)
    - _Requirements: 14.1, 14.2, 14.3, 14.4_

- [x] 15. Final checkpoint — 确认全部测试通过
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- All tasks are required — no optional tasks in this plan
- 每个属性测试必须运行至少 100 次迭代 (`@settings(max_examples=100)`)
- 每个属性测试必须包含注释标注：`# Feature: smartclaw-p1-enhanced-capabilities, Property {N}: {title}`
- 属性测试使用 hypothesis 库，MemoryStore 测试使用临时数据库（`tmp_path`），AutoSummarizer 测试 mock LLM 调用
- 单元测试使用 `pytest-asyncio` 支持异步测试，`AsyncMock` mock 外部依赖
- 所有 14 个需求（Requirements 1–14）均被实现和测试任务覆盖
- 所有 20 个正确性属性（Properties 1–20）均有对应的属性测试任务
- 实现按依赖顺序推进，每个主要模块后设置 checkpoint 确保增量验证
- Python 为实现语言（与设计文档一致）
