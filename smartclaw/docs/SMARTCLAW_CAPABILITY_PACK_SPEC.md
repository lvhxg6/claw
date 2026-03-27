# SmartClaw 能力包规范

## 1. 目的

能力包用于承接后续业务扩展，避免继续通过修改核心 graph、prompt 或 runtime 来适配每一个新场景。

当前能力包机制已经接入 `smartclaw` 主运行时，职责边界如下：

- `skills`
  - 提供原子工具和操作能力
- `capability pack`
  - 提供业务场景级 prompt、tool policy、schema、默认模式提示
- `orchestrator`
  - 负责 plan、dispatch、phase 执行和结果综合

一句话说：

- `skill` 解决“能做什么”
- `capability pack` 解决“这一类业务应该怎么组织”
- `orchestrator` 解决“当前请求怎么执行”


## 2. 当前实现

当前 Batch 3 已经落地以下能力：

- `manifest.yaml` 发现和加载
- workspace / global 两级能力包目录
- 请求级 `capability_pack` 指定
- 按 `scenario_type` 自动匹配能力包
- `preferred_mode` / `task_profile` 对运行时路由生效
- `allowed_tools` / `denied_tools` 工具过滤
- active pack prompt 和 result schema 注入 system prompt
- pack 级审批门控
- pack 级 schema 校验与 synthesize 重试
- pack 级 task retry 策略
- pack 级 task-group 并发限制

当前能力包是 **运行时内部机制**，不是新的独立 agent 类型。


## 3. 目录约定

推荐目录：

```text
capability_packs/
  security-governance/
    manifest.yaml
    prompt.md
    schema.json
```

默认搜索路径：

- workspace: `{workspace}/capability_packs`
- global: `~/.smartclaw/capability_packs`

优先级：

- workspace 覆盖 global


## 4. manifest 结构

最小示例：

```yaml
name: security-governance
description: Security governance workflows
scenario_types:
  - inspection
  - hardening
preferred_mode: orchestrator
task_profile: multi_stage
allowed_tools:
  - read_file
  - spawn_sub_agent
denied_tools:
  - exec_command
prompt_file: prompt.md
result_schema_file: schema.json
tool_groups:
  inspection:
    - read_file
    - spawn_sub_agent
```

字段说明：

- `name`
  - kebab-case 标识，能力包唯一名
- `description`
  - 简短描述
- `scenario_types`
  - 用于 `scenario_type` 自动匹配
- `preferred_mode`
  - `classic` 或 `orchestrator`
- `task_profile`
  - 用于模式路由的默认 task hint
- `prompt` / `prompt_file`
  - 业务提示词片段
- `result_schema` / `result_schema_file`
  - 结构化结果约束
- `allowed_tools`
  - 白名单；配置后只保留这些工具
- `denied_tools`
  - 黑名单；即使存在也不可用
- `tool_groups`
  - 按业务类别分组，便于后续限流和调度策略增强


## 5. 请求级使用方式

网关请求模型新增：

```json
{
  "message": "执行安全巡检并输出报告",
  "mode": "auto",
  "scenario_type": "inspection",
  "capability_pack": "security-governance"
}
```

运行时处理顺序：

1. 先解析 `capability_pack`
2. 如果未显式指定，则按 `scenario_type` 匹配
3. 把能力包的 `preferred_mode` / `task_profile` 作为默认 hint
4. 过滤 request-scoped tool 集
5. 在 system prompt 末尾附加 active pack 上下文


## 6. 与既有能力的关系

能力包不会替代下面这些机制：

- skills
- MCP tools
- memory / context engine
- classic mode
- orchestrator mode

它只做三件事：

- 给请求附加业务上下文
- 给请求限定工具边界
- 给 orchestrator 提供默认业务提示


## 7. 推荐接入方式

后续新业务场景，优先按下面顺序扩展：

1. 先补原子 tool 或 skill
2. 再定义 capability pack
3. 最后只在必要时补 orchestrator policy

不要优先去改：

- `graph.py`
- `orchestrator_graph.py`
- `runtime.py` 的核心执行流程

除非该场景需要通用机制增强，而不是单场景适配。


## 8. 当前边界

当前 Batch 3 的基础设施和首批治理增强都已经落地，已经可以支撑后续能力包按统一方式扩展。后续仍可继续增强的内容主要是：

- pack 级审批策略
- 更细粒度的审批策略
- pack 级结构化结果自动修复与更强校验
- pack 级记忆提取/事实提取策略

这些属于后续增强项，不影响当前能力包机制使用。
