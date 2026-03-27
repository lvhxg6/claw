# SmartClaw Orchestrator Mode 详细设计

## 1. 文档目的

本文档定义 SmartClaw 借鉴 DeerFlow 机制后的详细重构方案。

目标不是把 DeerFlow 接入 SmartClaw，而是：

- 保留 SmartClaw 作为最终系统和唯一产品壳
- 保留现有 `skills`、`tools`、`MCP`、`gateway`、`CLI`、`observability`、`context engine`
- 在 SmartClaw 内部新增 `orchestrator mode`
- 把 DeerFlow 中验证有效的机制迁移为 SmartClaw 自身机制

本文档重点回答四个问题：

1. 哪些能力必须原样保留
2. 哪些机制已经实现但没有进入主路径
3. SmartClaw 的目标运行时应该长什么样
4. 如何分阶段落地，且尽量不引入回归


## 2. 设计原则

### 2.1 核心原则

- 不替换 SmartClaw，只增强 SmartClaw
- 不推翻现有主链路，只在主链路上增加 orchestrator 能力
- 不让复杂业务继续堆到 prompt 里，而是收敛到 runtime / policy / state
- 不让编排逻辑污染原子工具层

### 2.2 兼容性原则

以下合同必须保留：

- `setup_agent_runtime()` 仍然是唯一初始化入口
- `ToolRegistry` 仍然是唯一工具注册中心
- `invoke()` 仍然是唯一会话装配、执行、回写入口
- `AgentRuntime` 返回结构尽量保持兼容
- 现有 hook 名称和主要语义保持稳定
- `gateway` 和 `CLI` 不应被迫分叉为两套入口

### 2.3 运行模式原则

建议将运行模式显式化：

- `auto`：默认模式，由后端根据任务特征自动路由
- `classic`：保留当前 ReAct 风格路径，适合简单任务
- `orchestrator`：显式规划、阶段执行、批次并发、结果综合

运行模式应当是 runtime 配置和请求级参数，而不是 prompt 暗约定。

补充原则：

- 最终用户不应被迫理解内部执行内核差异
- 默认应使用 `auto`
- `classic` 和 `orchestrator` 主要用于强制指定、调试、压测、排障
- 页面可以提供场景提示，但不应直接替代后端最终路由


## 3. 当前主路径梳理

### 3.1 当前真正处于主路径的能力

当前 SmartClaw 主路径比较清晰，入口集中在：

- `smartclaw/agent/runtime.py`
- `smartclaw/agent/graph.py`
- `smartclaw/agent/nodes.py`
- `smartclaw/gateway/routers/chat.py`
- `smartclaw/cli.py`

主链路如下：

1. `setup_agent_runtime()` 创建系统工具、MCP、skills、sub-agent tool、memory、summarizer、graph、context_engine
2. `gateway` / `CLI` 通过统一 `invoke()` 执行会话
3. `invoke()` 在执行前做历史装配，在执行后做消息回写和压缩
4. `graph` 内部用 `reasoning_node` + `action_node` 驱动工具调用
5. hooks / diagnostic bus / SSE 调试流围绕这条链路工作

这意味着：

- 真正需要保护的是 `runtime -> invoke -> graph -> hooks`
- 只要不破坏这条链路，多数既有能力都能保留


## 4. 已实现但未完全进入主路径的机制清单

这一部分是本次设计的关键。SmartClaw 当前不只是“功能少”，而是已经有不少机制代码存在，但没有完整接线或没有成为默认路径。

### 4.1 已实现但未完全接线

#### 4.1.1 ToolResultGuard

现状：

- 配置项已经存在于 `MemorySettings`
- `ToolResultGuard` 类已实现
- `build_graph()` / `action_node()` 已支持注入
- 但 `setup_agent_runtime()` 构图时没有实例化并传入

影响：

- L1 工具结果截断能力理论存在，主路径未必真正生效

设计要求：

- 在 runtime 初始化阶段统一实例化
- 所有 graph 构建路径都要接入，包括：
  - 默认 graph
  - model override 临时 graph
  - runtime `switch_model()` 重建 graph
  - sub-agent graph

#### 4.1.2 SessionPruner

现状：

- 配置项已经存在于 `MemorySettings`
- `SessionPruner` 类已实现
- `reasoning_node()` / `build_graph()` / `LegacyContextEngine` 已支持注入
- 但 runtime 侧没有统一实例化与传递

影响：

- L2 会话级裁剪理论存在，但当前主路径未必真正生效

设计要求：

- 统一实例化并接入 `context_engine` 和 graph
- 保证 pruner 只修剪 `ToolMessage`，不破坏用户消息和模型消息

#### 4.1.3 LoopDetector

现状：

- `LoopDetector` 已实现
- `action_node()` 和 `build_graph()` 已支持注入
- runtime 侧没有实例化与传递

影响：

- 当前主路径存在工具死循环风险时，保护机制未完全上线

设计要求：

- 纳入 runtime 的默认防护链
- 在 orchestrator mode 下同时覆盖：
  - 普通工具死循环
  - planner 反复重写计划
  - subagent 反复重复同类 dispatch

#### 4.1.4 ContextEngine.bootstrap / compact 生命周期

现状：

- `ContextEngine` 接口定义了 `bootstrap`、`compact`
- `LegacyContextEngine` 已实现这些方法
- 但 `invoke()` 当前只调用了 `assemble()` / `after_turn()`
- `bootstrap()` 看起来没有进入主路径

影响：

- context engine 生命周期不完整
- session 级状态可能没有在会话开始时显式初始化

设计要求：

- `invoke()` 开始前调用 `context_engine.bootstrap(session_key, system_prompt)`
- 在 context overflow、phase 切换、subagent 聚合等节点允许显式调用 `compact()`

#### 4.1.5 Session Hooks

现状：

- `session:start` / `session:end` hook 类型和合法 hook point 都已定义
- 但主路径中基本没有实际触发

影响：

- 调试和审计只能看到 agent 级事件，看不到完整会话生命周期

设计要求：

- 在 `invoke()` 外围补齐 `session:start` / `session:end`
- 区分“一个 session 的生命周期”和“一个 turn 的生命周期”

#### 4.1.6 SpawnSubAgentTool 可用性接线不完整

现状：

- `spawn_sub_agent()` 底层支持深度限制、超时、并发 semaphore、context engine 子任务 hook
- 但 runtime 注册 `SpawnSubAgentTool` 时没有显式传入 `available_tools`
- `_arun()` 调用 `spawn_sub_agent()` 时也没有传 `context_engine`

影响：

- 子 agent 可能拿不到父级工具集
- context engine 的 sub-agent 生命周期 hook 无法完整发挥作用

这是当前代码中最需要优先修正的问题之一。

设计要求：

- `SpawnSubAgentTool` 只作为底层 worker 启动器
- runtime 注册时传入受控工具集和 context_engine
- 编排层不要直接暴露原始 `spawn_sub_agent` 作为唯一高级机制

#### 4.1.7 临时 Graph / 切模型 Graph 的能力漂移

现状：

- `/api/chat` 中 model override 会临时 `build_graph(temp_config, runtime.tools)`
- `switch_model()` 也会直接 `build_graph(self.model_config, self.registry.get_all())`
- 这两条路径都没有保证自动继承 guard/pruner/loop detector/context 相关装配

影响：

- 默认 graph 与临时 graph 行为不一致
- 新能力接入后可能只在默认路径生效，切模型或临时图失效

设计要求：

- 引入统一的 `GraphFactory`
- 所有 graph 构建路径都必须走同一工厂

### 4.2 已实现但未进入主运行模式

#### 4.2.1 MultiAgent Coordinator

现状：

- `agent/multi_agent.py` 已存在
- 配置中也有 `multi_agent`
- 但主 runtime 不使用这条路径

影响：

- 它不是当前产品路径的一部分
- 不应该直接拿它当新的主架构

设计要求：

- 短期不并入主路径
- 作为参考实现保留
- 后续只抽取可复用机制，不直接升级为默认入口

#### 4.2.2 Bootstrap Loader

现状：

- `bootstrap/loader.py` 已实现
- 配置中也有 `bootstrap.enabled`
- 但 runtime 当前 system prompt 组装没有把 `SOUL.md` / `USER.md` / `TOOLS.md` 纳入默认主链

影响：

- 配置暴露了能力，但默认运行时没有真正吃进去

设计要求：

- 引入 `PromptComposer`
- 把 system prompt 组装收敛为：
  - base system prompt
  - bootstrap files
  - skills summary
  - mode-specific prompt fragments

#### 4.2.3 MemoryLoader / MemoryIndexManager / Facts

现状：

- `memory/loader.py`、`memory/index_manager.py`、facts schema 已实现
- `MemorySettings` 已暴露 `MEMORY.md` / `memory/` / hybrid search / fact extraction 配置
- 但主 runtime 没有看到这些组件被统一初始化并纳入上下文装配

影响：

- 这部分更像“已开发能力包”，不是“主路径能力”

设计要求：

- 在 orchestrator 重构中，不要直接强行并入主路径
- 应先作为可选 `context enrichment` 层接入 `ContextEngine`

#### 4.2.4 Skills / Config Hot Reload

现状：

- `skills/watcher.py`、`config/watcher.py`、`gateway/hot_reload.py` 都存在
- 但 gateway 生命周期没有形成一条完整的 watcher 启停链

影响：

- 热更新能力具备实现基础，但没有成为稳定的运行时合同

设计要求：

- 短期不与 orchestrator 深度耦合
- 单独做 runtime service 生命周期管理


## 5. 本次重构的非目标

为了控制风险，本次设计明确不做以下事情：

- 不引入 DeerFlow 代码作为运行时依赖
- 不直接废弃现有 ReAct graph
- 不把所有工具都改造成并发执行
- 不在第一阶段接入 memory vector index / facts 自动抽取
- 不把旧 `multi_agent` 直接升级为默认主路径
- 不同时改造所有 hot reload 机制


## 6. 目标架构

### 6.1 运行时分层

目标运行时建议分为六层：

1. `Runtime Assembly`
   - settings
   - registry
   - memory
   - context engine
   - guard / pruner / detector
   - prompt composer

2. `Conversation Lifecycle`
   - session bootstrap
   - invoke
   - persistence
   - session hooks

3. `Execution Mode`
   - classic mode
   - orchestrator mode

4. `Orchestration Layer`
   - plan state
   - phase state
   - batch dispatch
   - subagent limit policy

5. `Tool Execution Layer`
   - atomic tools
   - MCP tools
   - skills tools
   - subagent worker tools

6. `Observability Layer`
   - hooks
   - diagnostic bus
   - decision trace
   - SSE debug stream

### 6.2 新的核心组件

建议新增以下组件：

- `GraphFactory`
- `PromptComposer`
- `OrchestratorState`
- `PlanManager`
- `DispatchPolicy`
- `SubAgentDispatcher`
- `RuntimeServices`

组件职责如下：

#### GraphFactory

统一负责 graph 构建，避免默认图、临时图、切模型图能力不一致。

#### PromptComposer

统一负责 prompt 拼装，替代 scattered string format。

#### PlanManager

负责计划写入、状态迁移、phase 切换、结果归档。

#### DispatchPolicy

负责并发上限、批次切分、阶段边界、可并行类型判定。

#### SubAgentDispatcher

负责把“要执行哪些子任务”转换为受控并发 worker 调度。

#### RuntimeServices

统一托管：

- context engine
- mcp manager
- watchers
- future background maintenance jobs


## 7. Orchestrator Mode 详细设计

### 7.1 状态模型

建议在现有 `AgentState` 基础上扩展为：

- `mode`
- `plan`
- `todos`
- `current_phase`
- `phase_status`
- `dispatch_batches`
- `task_results`
- `execution_artifacts`
- `synthesis_notes`

推荐的 todo 结构：

- `id`
- `title`
- `kind`
- `status`
- `depends_on`
- `parallelizable`
- `tool_scope`
- `result_ref`
- `risk_level`

推荐状态值：

- `pending`
- `ready`
- `in_progress`
- `completed`
- `blocked`
- `failed`
- `cancelled`

### 7.2 执行流程

`orchestrator mode` 推荐使用下面的阶段流转：

1. `intake`
   - 理解用户目标
   - 判断是否需要 clarification
   - 判断是否需要 plan mode

2. `planning`
   - 生成 plan / todos / dependencies
   - 选择当前 phase

3. `dispatch`
   - 把 ready tasks 按 policy 切批
   - 生成一个或多个 batch

4. `execute`
   - 对 batch 内允许并行的任务执行 subagent / tool worker
   - 汇总结果

5. `review`
   - 判断是否需要重试、补充检查、下一阶段

6. `synthesize`
   - 汇总执行结果
   - 生成最终回答与结构化结果

当前实现状态：

- 已落地为 `planning -> dispatch -> execute -> review -> synthesize` 的 graph 流转
- `review` 节点会根据 todo 依赖和执行结果把 `pending / blocked` 推进到 `ready / completed / failed`
- `synthesize` 阶段统一复用 classic graph 做最终结果整合，避免出现第二套回答链路

### 7.3 并发模型

必须强调：不是“所有工具并发”，而是“编排层受控并发”。

推荐规则：

- 文件写入类工具：串行
- shell 修改类工具：串行
- 外部高风险操作：串行或需审批
- 只读检查类工具：可并行
- subagent worker：可并行，但受 `DispatchPolicy` 控制

推荐并发控制粒度：

- 每轮最大 subagent 数
- 每类任务最大并发数
- 每个工具组最大并发数
- 全局最大 worker 数

### 7.4 Subagent 语义重构

建议把当前单一 `spawn_sub_agent` 拆成两层：

- `spawn_sub_agent`
  - 底层 worker 启动器
  - 负责隔离、超时、深度、上下文传递、结果返回

- `dispatch_tasks`
  - 上层编排接口
  - 负责批量任务分发、限流、聚合、失败重试

也就是说：

- `spawn_sub_agent` 是执行原语
- `dispatch_tasks` 是编排机制

这是把 SmartClaw 从“会委派”升级到“会编排”的关键步骤。

当前实现状态：

- `spawn_sub_agent` 保持底层 worker 原语职责不变
- `dispatch_tasks` 已以内聚执行器模块落地，负责 batch fan-out、并发限流、结果聚合和诊断事件上报
- 当前是运行时内部编排接口，不额外暴露成用户直接调用的独立 tool


## 8. 与既有能力的兼容设计

### 8.1 Skills

兼容策略：

- 继续沿用 `SkillsLoader + SkillsRegistry + ToolRegistry`
- skill 不感知 classic / orchestrator mode
- 业务扩展继续通过 skill 增加 tool 能力，而不是修改主 graph

要求：

- orchestrator mode 也必须使用同一个 `ToolRegistry`
- skills summary 继续注入 prompt

### 8.2 Tools

兼容策略：

- 原子工具维持现有调用接口
- 不强迫已有 tools 理解 phase / plan
- 通过 policy 标注可并行性，而不是改 tool 签名

要求：

- 保留 `tool:before` / `tool:after`
- 并发执行时仍要逐工具发事件

### 8.3 MCP

兼容策略：

- MCP 继续作为普通 tools 注入 registry
- orchestrator 不直接接管 MCP 生命周期

要求：

- subagent 是否继承 MCP tool scope 必须可配置
- 对高风险 MCP tool 应支持 deny / allow policy

### 8.4 上下文压缩

兼容策略：

- `invoke()` 仍然是唯一会话装配入口
- context engine 仍然掌管 assemble / compact / after_turn

要求：

- 开始执行前 `bootstrap`
- phase 切换 / 大量子任务汇总后允许 `compact`
- 子任务结果回流要走统一压缩策略

### 8.5 LLM 行为观测

兼容策略：

- 保留既有 hooks 和 diagnostic events
- 新机制只新增事件，不替换旧事件

建议新增事件：

- `plan.created`
- `plan.updated`
- `phase.started`
- `phase.ended`
- `subagent.spawned`
- `subagent.completed`
- `dispatch.batch_started`
- `dispatch.batch_ended`

### 8.6 Gateway / CLI

兼容策略：

- `gateway` / `CLI` 继续调用统一 `invoke()`
- 不新增第二套业务入口

要求：

- mode 通过配置或请求参数选择
- SSE 继续复用现有 hook 流


## 9. Prompt 体系重构

当前 system prompt 组装过于集中在 `SYSTEM_PROMPT.format(...)`。

建议引入 `PromptComposer`，把 prompt 分成五部分：

1. `base prompt`
2. `bootstrap prompt`
3. `skills prompt`
4. `mode prompt`
5. `policy prompt`

推荐拼装顺序：

- base assistant identity
- bootstrap files
- tool and safety contract
- skills summary
- mode-specific instructions
- business capability pack prompt fragments

这样可以解决三个问题：

- bootstrap loader 有处可挂
- classic / orchestrator mode 可切换
- 业务扩展不再修改主模板字符串


## 10. Context 体系重构

### 10.1 总原则

长对话、复杂任务、并发子任务、业务扩展最终都在挤占 context。

因此 context 体系不能只靠 summarizer 单点承压，应当形成分层治理：

- L1：ToolResultGuard
- L2：SessionPruner
- L3：Summarizer
- L4：Explicit compact / phase compaction
- L5：Long-term memory enrichment

### 10.2 接线策略

#### L1

- 在工具结果写回前截断长文本

#### L2

- 在每次 LLM 调用前裁剪历史 `ToolMessage`

#### L3

- 在 turn 结束后基于阈值自动 summarization

#### L4

- 在阶段结束、批次回流、大任务综合前显式 compact

#### L5

- 后续再把 `MEMORY.md` / `memory/` / vector index 作为 context enrichment 接入


## 11. Runtime 详细改造点

### 11.1 setup_agent_runtime

建议新增以下初始化阶段：

1. registry assembly
2. bootstrap prompt assembly
3. memory service assembly
4. guard/pruner/detector assembly
5. context engine assembly
6. graph factory assembly
7. mode-specific graph build
8. runtime services assembly

`AgentRuntime` 建议增加：

- `mode`
- `graph_factory`
- `prompt_composer`
- `tool_result_guard`
- `session_pruner`
- `loop_detector_factory`
- `runtime_services`

### 11.2 invoke

`invoke()` 必须成为真正的会话壳：

执行前：

- emit `session:start`
- bootstrap context engine
- load history
- assemble context

执行中：

- choose graph by mode
- run graph

执行后：

- persist messages
- run `after_turn`
- emit `agent:end`
- emit `session:end`

### 11.3 GraphFactory

新增 `GraphFactory` 的目标是消除构图漂移。

所有以下场景统一走工厂：

- 默认 runtime.graph
- request model override
- runtime switch model
- subagent graph
- future worker graph


## 12. 配置设计建议

建议新增独立配置段，而不是把 orchestrator 配置散落在 `sub_agent` / `memory` 下：

```yaml
orchestrator:
  enabled: true
  mode: auto
  plan_enabled: true
  max_concurrent_workers: 4
  max_batch_size: 4
  max_phases: 8
  enable_explicit_compaction: true
  enable_dispatch_policy: true
```

建议增加路由控制配置：

```yaml
mode_router:
  enabled: true
  default_mode: classic
  allow_frontend_hint: true
  allow_user_override: true
  orchestrator_score_threshold: 0.7
  force_orchestrator_scenarios:
    - inspection
    - hardening
    - batch_job
```

建议新增 `sub_agent` 细化配置：

```yaml
sub_agent:
  enabled: true
  max_depth: 3
  max_concurrent: 5
  default_timeout_seconds: 300
  inherit_tools: scoped
  inherit_mcp: false
  inherit_context_summary: true
```

建议新增工具策略配置：

```yaml
tool_policy:
  parallelizable_tools:
    - check_baseline
    - check_weak_password
  serial_tools:
    - write_file
    - edit_file
    - exec_command
```


## 12.1 模式路由设计

运行模式不应只由页面决定，而应由前后端共同参与，后端最终裁决。

### 模式取值

推荐支持三种模式：

- `auto`
- `classic`
- `orchestrator`

### 前后端职责边界

前端负责提供上下文，不负责做最终执行内核判定。

前端可传递：

- `mode`
- `scenario_type`
- `task_profile`
- `skill_hint`
- `capability_pack`

推荐含义：

- `mode`
  - 用户或页面显式指定运行模式
- `scenario_type`
  - 业务场景类型，如 `chat`、`inspection`、`hardening`、`batch_job`
- `task_profile`
  - 页面侧已知任务特征，如 `simple`、`multi_stage`、`parallelizable`
- `skill_hint`
  - 当前偏向的 skill 或业务入口
- `capability_pack`
  - 当前业务能力包标识

后端负责：

- 接收前端 hint
- 做最终任务分类
- 决定 `classic` 或 `orchestrator`
- 在 `auto` 模式下记录路由原因，便于审计和调试

### 模式路由优先级

推荐优先级如下：

1. 用户显式指定 mode
2. 系统级强制策略
3. 页面 / 场景 hint
4. `TaskClassifier` 自动判定
5. 回退到 `default_mode`

推荐解释：

- 用户显式指定 `classic`
  - 直接走 `classic`
- 用户显式指定 `orchestrator`
  - 直接走 `orchestrator`
- 如果是 `auto`
  - 由后端结合页面 hint 和任务分类结果决定

### TaskClassifier 设计

建议在后端新增轻量 `TaskClassifier`，用于 `auto` 模式路由。

第一阶段不建议纯 LLM 自由判断，而建议先使用规则路由，后续再升级为“规则 + LLM 判定”。

#### 结构信号

满足越多，越倾向 `orchestrator`：

- 一个请求中包含多个子目标
- 明显存在阶段语义，如“先、再、最后”
- 存在条件执行，如“根据结果决定是否”
- 需要综合汇总、报告、闭环验证
- 需要重试、复检、回滚、审批

#### 规模信号

- 涉及多个对象，如多主机、多设备、多资产、多文件
- 明确提到批量处理
- 预计需要多个 tools 或多个 subagent
- 任务执行跨度明显超过单轮 ReAct

#### 业务信号

以下场景默认偏向 `orchestrator`：

- 巡检
- 合规检查
- 基线检查
- 弱口令治理
- 加固闭环
- 批量整改
- 多阶段工作流

#### 治理信号

- 高风险操作
- 需要结构化审计轨迹
- 需要阶段确认
- 需要结果标准化沉淀

### 推荐分类输出

`TaskClassifier` 建议输出：

```json
{
  "recommended_mode": "orchestrator",
  "reason_codes": [
    "multi_goal",
    "has_dependencies",
    "requires_parallel_checks",
    "needs_structured_report"
  ],
  "confidence": 0.92
}
```

### 路由决策建议

建议决策规则：

- `mode=classic`
  - 强制走 `classic`
- `mode=orchestrator`
  - 强制走 `orchestrator`
- `mode=auto`
  - 如果分类器推荐 `orchestrator` 且达到阈值，走 `orchestrator`
  - 否则走 `classic`

### 页面与模式的关系

页面可以强相关，但不应一一硬绑定。

推荐方式：

- 普通聊天页
  - 默认 `auto`
  - 场景偏向 `classic`
- 安全巡检页
  - 默认 `auto`
  - 场景偏向 `orchestrator`
- 批量任务页
  - 默认 `orchestrator` 或 `auto + force hint`

即使在偏 `orchestrator` 的页面中，如果用户只提了一个简单问题，后端仍可选择 `classic`。

### 为什么要这样设计

如果让页面直接决定 mode，会出现三个问题：

- 新业务一多，页面与执行模式耦合过深
- 同一页面中的简单任务和复杂任务无法自动分流
- 后端无法统一审计和优化路由策略

因此正确做法是：

- 页面提供上下文
- 后端做最终判定
- 默认使用 `auto`


## 13. 能力包扩展机制

未来扩展场景不应继续做“一个场景一条硬编码流程”，而应采用能力包。

推荐能力包组成：

- `tools`
- `skills`
- `schemas`
- `policies`
- `prompt_fragments`

例如安全治理能力包：

- 检查类 tools
- 加固类 tools
- 结构化结果 schema
- 哪些检查可并行、哪些加固串行的 policy
- 面向 orchestrator 的执行提示

这样扩展新场景时：

- 不改主 graph
- 不改核心 runtime
- 只增业务能力包和少量 policy


## 14. 分阶段实施方案

先说明一个执行原则：

- 本文档中的 5 个 phase 是风险分层和能力分层
- 不等于必须拆成 5 次独立实施
- 推荐实施方式是按 3 个批次推进

### 14.1 推荐实施批次

#### Batch 1：先稳主链路

对应范围：

- Phase 0
- Phase 1 的框架部分

建议包含：

- 接上 ToolResultGuard
- 接上 SessionPruner
- 接上 LoopDetector
- 给 `invoke()` 补 `context_engine.bootstrap`
- 补齐 `session:start` / `session:end`
- 修正 `spawn_sub_agent` 的 tools/context 继承
- 引入 `GraphFactory`
- 引入 `PromptComposer` 雏形
- 增加 `classic / orchestrator` 模式开关骨架

目标：

- 不改变现有产品对外形态
- 先把 runtime 主链路收口
- 为 orchestrator mode 提供稳定插口

#### Batch 2：上 orchestrator 真能力

对应范围：

- Phase 1 剩余部分
- Phase 2

建议包含：

- `PlanState`
- `PlanManager`
- `dispatch_tasks`
- `DispatchPolicy`
- phase / batch 执行
- subagent 并发调度
- orchestrator 相关 hooks / diagnostic events

目标：

- 让 SmartClaw 真正具备复杂任务规划和分阶段并行能力

当前实现状态：

- 已完成 `PlanState / PlanManager / DispatchPolicy / dispatch_tasks`
- 已完成 phase / batch 执行和 subagent 并发调度
- 已完成 `plan.created / plan.updated / dispatch.created / dispatch.batch_* / subagent.* / phase.*` 诊断事件
- 当前剩余工作不再属于 Batch 2 主体，而是后续增强项，例如失败重试策略、按工具组限流、能力包接入

#### Batch 3：扩展体系与记忆增强

对应范围：

- Phase 3
- Phase 4

建议包含：

- 能力包规范
- schema / policy 标准化
- memory enrichment 接入
- MEMORY.md / memory/ / vector index / facts 增强

目标：

- 让后续新业务场景以能力包方式接入
- 把长时记忆增强变成可选增强层，而不是侵入主链路

当前实现状态：

- 已完成 Phase 3 的基础设施和第一批治理增强
- 已新增 capability pack 机制：manifest 加载、registry、scenario 匹配、tool policy、prompt/schema 注入
- 已新增 pack 级审批门控、schema validation、synthesize 重试、task retry、group concurrency limit
- 当前未完成部分主要属于后续增强项：更细粒度审批、自动修复型 schema 治理、pack 级 memory enrichment 深化

### 14.2 为什么不建议一次性大改

一次性把 5 个 phase 全部并进去，最大风险不在“实现复杂”，而在：

- 容易破坏 `skills / tools / MCP` 现有兼容性
- 容易绕开 `invoke()` 导致上下文链路漂移
- 容易破坏 hooks / SSE / observability
- 容易出现默认 graph、临时 graph、subagent graph 行为不一致

因此推荐：

- 设计上保留 5 个 phase 的清晰边界
- 实施上按 3 个 batch 推进
- 每个 batch 都保证 classic mode 可回退

### Phase 0：主链路收口

目标：

- 不做 orchestrator
- 先把现有未接线机制补齐

任务：

- 接上 ToolResultGuard
- 接上 SessionPruner
- 接上 LoopDetector
- 给 invoke 补 `context_engine.bootstrap`
- 补 session hooks
- 修正 `spawn_sub_agent` 的 tools/context 传递
- 引入 GraphFactory

这是第一优先级。

### Phase 1：双模式运行时

目标：

- 保持 classic 不变
- 新增 orchestrator mode 框架

任务：

- mode 配置
- PromptComposer
- PlanState / PlanManager
- orchestrator graph skeleton

### Phase 2：受控并发调度

目标：

- 让 orchestrator 具备稳定的批次并发能力

任务：

- DispatchPolicy
- dispatch_tasks
- batch execution
- subagent results aggregation

当前实现状态：

- 已完成
- 当前 orchestrator 已具备受控并发批次执行能力，并可按依赖推进多阶段 todo

### Phase 3：业务能力包

目标：

- 让新业务按包扩展，不再改核心逻辑

任务：

- schema 标准化
- policy 标准化
- capability pack manifest

当前实现状态：

- 已完成基础版和首批治理增强
- `capability_pack` 已成为请求级 runtime 能力，可用于：
  - 默认模式提示
  - task profile 提示
  - request-scoped tool 过滤
  - active pack prompt / result schema 注入
  - approval gate
  - schema validation / synthesize retry
  - task retry / group concurrency policy

### Phase 4：长时记忆增强

目标：

- 把 MEMORY.md / memory/ / vector search / facts 作为增强层接入

任务：

- memory enrichment adapter
- retrieval-aware context assembly
- fact extraction policy


## 15. 测试策略

### 15.1 回归测试主轴

必须覆盖以下不回归能力：

- skills 仍可加载和执行
- MCP 仍可初始化和调用
- gateway chat 与 stream 不变
- CLI 不变
- hooks 和 SSE 事件仍然完整
- memory summarize 行为不退化
- 切模型路径和默认路径行为一致

### 15.2 新增测试类型

建议新增：

- GraphFactory 一致性测试
- ToolResultGuard 主链路接线测试
- SessionPruner 主链路接线测试
- ContextEngine bootstrap / compact 生命周期测试
- session hooks 触发测试
- subagent tools/context 继承测试
- orchestrator 批次并发测试
- plan state 转移测试
- tool event 在并发下的完整性测试


## 16. 风险与控制

### 16.1 高风险点

- 绕开 `invoke()` 另起入口
- 把 orchestration 写死在 prompt 层
- 改动原有 hook 事件名
- 所有 tools 一刀切改并发
- 在第一阶段就强行并入 memory vector / facts

### 16.2 控制策略

- 所有新能力都挂在兼容 runtime 上
- classic mode 始终可回退
- 任何 graph 构建都必须走工厂
- 先接线补齐，再加 orchestrator
- 先做机制，再做业务场景


## 17. 最终结论

SmartClaw 适合走的路线不是“接入 DeerFlow”，而是：

- 保留 SmartClaw 的产品壳和工程资产
- 用 DeerFlow 的机制重构 SmartClaw 的执行内核
- 先把当前已实现但未完全接线的能力补齐
- 再新增 orchestrator mode
- 最后用能力包承接未来业务扩展

这条路线的最大价值不是“支持一个安全治理场景”，而是：

- 让 SmartClaw 从“能执行工具的单 agent”演进为“可规划、可治理、可并发、可扩展的任务编排引擎”

同时保住现有：

- `skills`
- `tools`
- `MCP`
- `context compression`
- `observability`
- `gateway / CLI`

这才是后续承接多业务场景的正确底座。
