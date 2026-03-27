# SmartClaw 借鉴 DeerFlow 机制的重构方案

## 1. 正确认知

本方案的目标不是：

- 把 DeerFlow 接入 SmartClaw
- 用 DeerFlow 替代 SmartClaw
- 让 SmartClaw 变成 DeerFlow 的壳

本方案的目标是：

- **SmartClaw 继续作为最终系统**
- **SmartClaw 保留自己的配置、网关、工具、MCP、观测、产品形态**
- **只吸收 DeerFlow 中已经验证有效的机制**
- **用这些机制重构 SmartClaw 的任务规划、并行 subagent、治理和扩展体系**

一句话：

- **保留 SmartClaw 主体**
- **迁移 DeerFlow 机制**
- **不迁移 DeerFlow 身份**


## 2. 这次真正应该学 DeerFlow 的是什么

不是学它的项目壳，而是学它的四类机制。

### 2.1 规划机制

DeerFlow 的有效点：

- `plan mode`
- `write_todos`
- 复杂任务先拆步骤
- 执行过程中持续更新计划

SmartClaw 当前问题：

- 有“Structured thinking”提示
- 但没有真正的计划状态和计划工具
- 计划不可观测、不可持久化、不可约束

应迁移的机制：

- 为 SmartClaw 增加显式 `plan mode`
- 引入 `write_todos` / `update_plan` 一类工具
- 把计划作为 state 的一部分，而不是只放在 prompt 里

### 2.2 并行 subagent 机制

DeerFlow 的有效点：

- 主 agent 明确承担 orchestrator 角色
- 通过 `task` 工具启动子任务
- 限制单轮并发数
- 超过并发上限时强制分批

SmartClaw 当前问题：

- 有 `spawn_sub_agent`
- 但主图默认不是“阶段式并发编排”
- `action_node` 是串行执行 tool call
- `multi_agent` 是独立模块，不是默认主流程

应迁移的机制：

- 把 SmartClaw 的 `spawn_sub_agent` 升级成“编排工具”而不是普通工具
- 增加单轮并发限制中间件
- 增加 phase/batch 执行约束
- 把并行子任务作为主路径能力，而不是“模型偶尔会调用的一个工具”

### 2.3 治理机制

DeerFlow 的有效点：

- middleware 链是主扩展点
- 限流、标题、memory、clarification、subagent limit 都是 middleware

SmartClaw 当前问题：

- 有 hooks、observability、context_engine
- 但治理点还没有收敛成统一执行链

应迁移的机制：

- 把更多运行时约束前移到 middleware / runtime policy 层
- 减少只靠 prompt 控制高风险行为

### 2.4 扩展机制

DeerFlow 的有效点：

- tools / skills / agents / config 边界清晰
- 运行时开关明确：`is_plan_mode`、`subagent_enabled`

SmartClaw 当前问题：

- 有 skills、tools、MCP
- 但新增业务场景时，容易继续往主 agent prompt 和 runtime 里堆逻辑

应迁移的机制：

- 统一把业务扩展沉到底层能力包
- 主流程只负责编排，不直接承载业务细节


## 3. SmartClaw 应保留什么

下面这些仍然应该是 SmartClaw 的主体资产。

### 3.1 产品壳

- `smartclaw.gateway.*`
- CLI / API / 前端入口
- 配置体系
- 部署方式

### 3.2 工具资产

- `smartclaw.tools.*`
- `smartclaw.skills.*`
- `smartclaw.mcp.*`

### 3.3 治理与观测资产

- `smartclaw.observability.*`
- `smartclaw.hooks.*`
- `smartclaw.security.path_policy`
- `smartclaw.context_engine.*`

### 3.4 兼容层

- 现有 runtime 先不删除
- 进入兼容维护态
- 新机制逐步切入


## 4. SmartClaw 应该改什么

重点不是“引入 DeerFlow 代码”，而是“重构 SmartClaw 的主运行机制”。

### 4.1 把当前单 Agent ReAct Runtime 升级为“可规划编排 Runtime”

建议新主线不是替换整个项目，而是在 SmartClaw 内新增一条主运行模式：

- `classic mode`
- `orchestrator mode`

其中：

- `classic mode`：保留当前简单任务能力
- `orchestrator mode`：用于复杂任务、业务编排、并发子任务

建议通过配置开启：

- `smartclaw.agent.mode = classic | orchestrator`
- `smartclaw.plan.enabled = true | false`
- `smartclaw.sub_agent.enabled = true | false`

### 4.2 增加显式 Plan State

建议在 `AgentState` 中新增：

- `plan`
- `todos`
- `current_phase`
- `task_batches`
- `task_results`

不要让“计划”只存在于模型输出文本里。

### 4.3 增加 Plan Tool

参考 DeerFlow 的 `write_todos` 思路，在 SmartClaw 中增加：

- `write_plan`
- `update_plan`
- `set_phase`

建议能力：

- 创建任务列表
- 标记 `pending / in_progress / completed / blocked`
- 标记当前 phase
- 记录依赖关系

### 4.4 升级 `spawn_sub_agent`

现在的 `spawn_sub_agent` 更像普通工具。

建议升级成两层语义：

- `spawn_sub_agent`：底层执行器
- `dispatch_tasks`：上层编排器接口

其中：

- `spawn_sub_agent` 继续负责深度、超时、隔离、上下文传递
- `dispatch_tasks` 负责批量调度、并发限制、阶段边界、结果汇总

这一步很关键。否则所有业务都会直接堆到 `spawn_sub_agent` 上，越来越乱。

### 4.5 把 Action Node 从串行改为“可控并发”

当前 SmartClaw 的 `action_node` 是逐个执行 tool call。

建议改成：

- 默认串行
- 对被标记为 `parallelizable` 的工具支持并发
- 对 subagent 调度类工具启用批量并发

但不是“全工具并发”，而是“受控并发”。

建议规则：

- 文件写入类：默认串行
- shell 变更类：默认串行
- 检查类 subagent：允许并发
- 纯读工具：可配置并发

### 4.6 增加 Subagent Limit Middleware

这个机制很值得直接学。

建议 SmartClaw 新增：

- `SubAgentLimitMiddleware`

作用：

- 限制单轮模型响应里最多允许发起多少个 subagent
- 超过上限时自动裁剪
- 记录告警事件

建议初始上限：

- `max_concurrent_subagents = 3`


## 5. 推荐的 SmartClaw 新运行模型

建议形成下面这条主链路：

1. 用户请求进入 SmartClaw
2. 路由器判断是否为复杂任务
3. 若复杂任务，进入 `orchestrator mode`
4. planner 先生成 todo/plan
5. orchestrator 按 phase 组织子任务
6. subagent 并发执行
7. 汇总结果
8. 如需整改，进入 remediation phase
9. 最终验证并产出报告

### 5.1 Phase 机制

建议明确引入阶段执行，不允许自由散射式并发。

推荐 phase：

- `intake`
- `discovery`
- `analysis`
- `remediation`
- `verification`
- `reporting`

这样未来新增业务时，不改主架构，只改每个 phase 的 skill/tool 组合。

### 5.2 Batch 机制

建议：

- 一个 phase 内允许多个 batch
- 一个 batch 内允许多个并发 subagent
- batch 完成后才能进入下一批

这就是 DeerFlow 真正值得学的地方，不是它的目录结构，而是这个执行约束。


## 6. 面向未来业务的扩展逻辑

你的目标不是扩一个场景，而是扩很多场景。所以要从“场景开发”改成“能力包开发”。

### 6.1 能力包规范

建议每个业务能力包包含：

- `manifest.yaml`
- `tools/`
- `skills/`
- `schemas/`
- `policies/`
- `tests/`

### 6.2 Tool 只做原子动作

例如：

- `check_baseline`
- `check_weak_password`
- `check_firewall_baseline`
- `remediate_baseline`
- `remediate_firewall`
- `verify_remediation`

不要在 tool 里写完整业务编排。

### 6.3 Skill 只做领域工作流模板

Skill 负责：

- 告诉 orchestrator 如何拆分
- 每个 phase 应调用哪些能力
- 输出格式是什么
- 哪些情况需要审批

### 6.4 Schema 统一结果结构

建议统一检查结果：

- `target`
- `category`
- `status`
- `findings`
- `risk_level`
- `evidence`
- `need_remediation`
- `recommended_actions`

建议统一整改结果：

- `target`
- `action`
- `status`
- `changes_applied`
- `rollback_supported`
- `verification_status`
- `evidence`

这层非常重要。未来场景再多，只要 schema 统一，编排层和汇总层都稳。

### 6.5 Policy 做治理，而不是写死在 prompt

Policy 应承载：

- 高风险动作审批
- 禁止自动整改的资产类型
- 业务时间窗限制
- 最大并发限制
- 可访问路径和命令白名单


## 7. 对 SmartClaw 当前模块的具体改造建议

### 7.1 `smartclaw.agent.runtime`

建议：

- 保留
- 增加 `orchestrator mode`
- 增加 `plan` 和 `phase` 初始化
- 增加 middleware 装配能力

### 7.2 `smartclaw.agent.graph`

建议：

- 保留主图编译能力
- 增加 planner / orchestrator / synthesizer 节点
- 不再只保留 reasoning/action 二段式

### 7.3 `smartclaw.agent.nodes`

建议新增：

- `planning_node`
- `batch_dispatch_node`
- `synthesis_node`
- `approval_gate_node`

### 7.4 `smartclaw.agent.sub_agent`

建议：

- 保留底层执行能力
- 增加批量调度包装层
- 支持 phase/batch metadata
- 支持更标准的任务结果结构

### 7.5 `smartclaw.agent.multi_agent`

建议不要继续沿当前 supervisor 原型直接扩。

理由：

- 现在这套更像实验性模块
- 没有真正进入主 runtime
- 执行模型仍偏串行路由

建议做法：

- 参考 DeerFlow 思想
- 重构成 SmartClaw 自己的 orchestrator 机制
- 不直接把现有 `multi_agent.py` 当未来主线


## 8. 推荐优先保留的 SmartClaw 核心优势

相比 DeerFlow，SmartClaw 自己有几块值得继续当核心竞争力。

### 8.1 MCP 连接管理

`smartclaw.mcp.manager` 的 transport 和 lifecycle 做得比较完整。

建议继续保留，并作为未来所有能力包接第三方系统的统一入口。

### 8.2 Context Engine

`smartclaw.context_engine` 值得保留。

建议将其升级为：

- 主 agent 上下文管理
- subagent 上下文裁剪
- phase 结果汇总压缩
- 证据摘要和任务记忆管理

### 8.3 Observability

`smartclaw.observability` 很适合继续强化。

建议新增采集点：

- plan created
- phase started
- batch dispatched
- subagent completed
- policy blocked
- approval requested
- remediation applied


## 9. 推荐的演进路线

### Phase 1：先补机制，不碰产品壳

只在 SmartClaw 内部补：

- plan state
- todo tool
- phase/batch dispatch
- subagent limit middleware

先不要大动 gateway、前端、CLI。

### Phase 2：把安全业务沉成能力包

先迁移你当前场景：

- 基线检查
- 弱口令检查
- 防火墙基线检查
- 条件化加固
- 验证复检

目标是验证“能力包 + orchestrator”模式成立。

### Phase 3：引入治理机制

补：

- 审批
- 风险分级
- 幂等
- 回滚
- 审计

### Phase 4：统一对外产品入口

此时再让 gateway / UI 对接新的 orchestrator state，而不是一开始就重做界面。


## 10. 最终建议

最终路线应该是：

- **SmartClaw 继续是主系统**
- **DeerFlow 只作为机制参考源**
- **把 DeerFlow 的 planning、batch、subagent limit、middleware 思路迁入 SmartClaw**

也就是说，你后面真正要做的是：

- **重构 SmartClaw 的主运行机制**
- 而不是“集成一个 DeerFlow”

如果继续往下推进，下一步最合理的不是再写泛化建议，而是直接开始做下面两件事：

1. `SmartClaw Orchestrator Mode` 技术设计
2. `业务能力包规范` 首版定义

这两件事才是后续所有业务场景扩展的基础。
