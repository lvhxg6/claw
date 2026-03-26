# 实现计划：统一 Agent 运行时 + Gateway 功能对齐

## 概述

按依赖顺序实现：先创建 AgentRuntime 核心模块，再集成到 Gateway 和 CLI，最后实现模型切换和一致性验证。所有代码使用 Python，测试使用 pytest + hypothesis。

## 任务

- [x] 1. 实现 AgentRuntime 核心模块
  - [x] 1.1 创建 `smartclaw/smartclaw/agent/runtime.py`，实现 AgentRuntime dataclass
    - 定义 `AgentRuntime` dataclass，包含 `graph`、`registry`、`memory_store`、`summarizer`、`system_prompt`、`mcp_manager`、`model_config` 字段
    - 实现 `tools` 属性（返回 `registry.get_all()`）
    - 实现 `tool_names` 属性（返回 `registry.list_tools()`，已排序）
    - 实现 `close()` 异步方法，逐个关闭 `memory_store` 和 `mcp_manager`，每个用 try/except 包裹，记录错误日志但不抛出异常
    - _需求: 1.1, 5.1, 5.2, 5.5, 6.3_

  - [x] 1.2 实现 `setup_agent_runtime()` 异步工厂函数
    - 在 `smartclaw/smartclaw/agent/runtime.py` 中实现 `setup_agent_runtime(settings, *, stream_callback=None) -> AgentRuntime`
    - 按设计文档顺序初始化：系统工具 → MCP → Skills → Sub-Agent → System Prompt → MemoryStore → AutoSummarizer → build_graph
    - 每个组件初始化失败时记录警告日志并跳过，继续初始化其余组件
    - 复用 `cli.py` 中的 `SYSTEM_PROMPT` 模板（移至 `runtime.py` 或共享常量）
    - _需求: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10_

  - [x] 1.3 编写 AgentRuntime 单元测试 `tests/agent/test_runtime.py`
    - 测试 `setup_agent_runtime()` 返回正确结构（graph、registry、system_prompt 非 None）
    - 测试各功能开关 enabled=False 时对应组件为 None
    - 测试组件初始化失败时的容错行为（mock 抛异常）
    - 测试 `close()` 正常关闭和异常容错
    - _需求: 1.1, 1.7, 1.8, 1.9, 5.2, 5.5_

  - [x] 1.4 编写属性测试：AgentRuntime 结构完整性
    - **Property 1: AgentRuntime 结构完整性**
    - 使用 hypothesis 生成随机 SmartClawSettings（`st.booleans()` 控制各 enabled 字段）
    - 验证返回的 AgentRuntime 始终包含非 None 的 `graph`、`registry`、`system_prompt`、`model_config`
    - 验证 `registry` 中至少包含 8 个基础系统工具
    - 文件: `tests/agent/test_runtime_props.py`
    - **验证: 需求 1.1**

  - [x] 1.5 编写属性测试：功能开关一致性
    - **Property 2: 功能开关一致性**
    - 使用 hypothesis 生成随机 enabled 组合（`st.booleans()` × 4 个功能开关）
    - 验证 skills.enabled=True 且有可加载 skills 时，system_prompt 包含 skills 描述
    - 验证 sub_agent.enabled=True 时，registry 包含 `spawn_sub_agent` 工具
    - 验证 memory.enabled=True 时，memory_store 和 summarizer 均非 None
    - 验证任一功能 enabled=False 时，对应组件不存在或为 None
    - 文件: `tests/agent/test_runtime_props.py`
    - **验证: 需求 1.3, 1.4, 1.5**

  - [x] 1.6 编写属性测试：close() 释放资源
    - **Property 7: close() 释放资源**
    - 使用 hypothesis 生成带/不带 memory_store 和 mcp_manager 的 runtime（`st.booleans()` 控制组件存在性）
    - 验证 close() 后 memory_store 的 close 被调用，mcp_manager 的 close 被调用
    - 文件: `tests/agent/test_runtime_props.py`
    - **验证: 需求 5.2**

  - [x] 1.7 编写属性测试：close() 异常容错
    - **Property 8: close() 异常容错**
    - 使用 hypothesis 生成 close() 会抛异常的 mock 资源（`st.sampled_from([Exception, RuntimeError, OSError])`）
    - 验证 AgentRuntime.close() 不向调用方传播异常，且继续清理其余资源
    - 文件: `tests/agent/test_runtime_props.py`
    - **验证: 需求 5.5**

  - [x] 1.8 编写属性测试：初始化确定性
    - **Property 9: 初始化确定性**
    - 使用 hypothesis 生成随机 SmartClawSettings
    - 连续两次调用 `setup_agent_runtime(settings)` 返回的 AgentRuntime 应具有相同的 `tool_names` 列表和相同的 `system_prompt` 内容
    - 文件: `tests/agent/test_runtime_props.py`
    - **验证: 需求 6.1, 6.2**

- [x] 2. 检查点 - 确保 AgentRuntime 核心模块测试通过
  - 运行 `pytest tests/agent/test_runtime.py tests/agent/test_runtime_props.py -v`，确保所有测试通过，如有问题请询问用户。

- [x] 3. Gateway 集成 AgentRuntime
  - [x] 3.1 重构 `smartclaw/smartclaw/gateway/app.py` 的 `lifespan()` 函数
    - 将现有的内联初始化逻辑替换为调用 `setup_agent_runtime(settings)`
    - 将 `runtime` 存储到 `app.state.runtime`
    - 保留 `app.state.graph`、`app.state.registry`、`app.state.memory_store` 的兼容性赋值（从 runtime 读取）
    - shutdown 阶段调用 `runtime.close()` 替代现有的手动 `memory_store.close()`
    - _需求: 2.1, 5.3_

  - [x] 3.2 修改 `smartclaw/smartclaw/gateway/routers/chat.py` 传入 system_prompt 和 summarizer
    - `chat()` 从 `request.app.state.runtime` 获取 `system_prompt` 和 `summarizer`
    - 在 `invoke()` 调用中传入 `system_prompt=runtime.system_prompt` 和 `summarizer=runtime.summarizer`
    - `chat_stream()` 同样传入 `system_prompt` 和 `summarizer`
    - _需求: 2.2, 2.3, 2.4_

  - [x] 3.3 修改 `smartclaw/smartclaw/gateway/routers/health.py` 使用 runtime 工具数量
    - health 端点返回的 `tools_count` 从 `app.state.runtime.registry.count` 读取
    - _需求: 2.5_

  - [x] 3.4 编写 Gateway 集成测试 `tests/gateway/test_runtime_integration.py`
    - 测试 lifespan 正确调用 `setup_agent_runtime` 并设置 `app.state.runtime`
    - 测试 chat 端点 invoke 调用包含 system_prompt 和 summarizer 参数
    - 测试 chat_stream 端点 invoke 调用包含 system_prompt 和 summarizer 参数
    - 测试 shutdown 阶段调用 `runtime.close()`
    - _需求: 2.1, 2.2, 2.3, 2.4, 5.3_

  - [x] 3.5 编写属性测试：Health 端点工具数量一致性
    - **Property 10: Health 端点工具数量一致性**
    - 使用 hypothesis 生成不同工具数量的 runtime（`st.integers(min_value=0, max_value=50)`）
    - 验证 health 端点返回的 `tools_count` 等于 `AgentRuntime.registry.count`
    - 文件: `tests/gateway/test_runtime_integration_props.py`
    - **验证: 需求 2.5**

- [x] 4. 检查点 - 确保 Gateway 集成测试通过
  - 运行 `pytest tests/gateway/test_runtime_integration.py tests/gateway/test_runtime_integration_props.py -v`，确保所有测试通过，如有问题请询问用户。

- [x] 5. CLI 重构使用 AgentRuntime
  - [x] 5.1 重构 `smartclaw/smartclaw/cli.py` 的 `_run_agent_loop()` 函数
    - 根据 `--no-memory`/`--no-skills`/`--no-sub-agent` 参数临时修改 `settings` 的对应 `enabled` 字段为 `False`
    - 调用 `setup_agent_runtime(settings)` 获取 `AgentRuntime`
    - 从 `runtime` 读取 graph、memory_store、summarizer、system_prompt 用于交互循环
    - 交互循环结束后调用 `runtime.close()` 替代现有的手动 `memory_store.close()`
    - 保持 banner 输出内容不变，从 runtime 对象读取工具数量、skills 状态等
    - 删除 `_run_agent_loop()` 中的内联初始化代码（Skills、Sub-Agent、Memory、System Prompt 构建）
    - _需求: 3.1, 3.2, 3.3, 3.4, 5.4_

  - [x] 5.2 编写 CLI 重构单元测试 `tests/test_cli_runtime.py`
    - 测试 `--no-memory` 参数使 settings.memory.enabled 设为 False
    - 测试 `--no-skills` 参数使 settings.skills.enabled 设为 False
    - 测试 `--no-sub-agent` 参数使 settings.sub_agent.enabled 设为 False
    - 测试 CLI 调用 `setup_agent_runtime` 并使用返回的 runtime 对象
    - _需求: 3.1, 3.2_

  - [x] 5.3 编写属性测试：CLI 命令行参数覆盖
    - **Property 3: CLI 命令行参数覆盖**
    - 使用 hypothesis 生成随机 `--no-memory`、`--no-skills`、`--no-sub-agent` 参数组合（`st.booleans()` × 3）
    - 验证 CLI 在调用 `setup_agent_runtime` 前将 settings 中对应的 `enabled` 字段设为 `False`
    - 验证返回的 AgentRuntime 中对应组件被禁用
    - 文件: `tests/test_cli_runtime_props.py`
    - **验证: 需求 3.2**

- [x] 6. 检查点 - 确保 CLI 重构测试通过
  - 运行 `pytest tests/test_cli_runtime.py tests/test_cli_runtime_props.py -v`，确保所有测试通过，如有问题请询问用户。

- [x] 7. 实现请求级模型切换
  - [x] 7.1 修改 `smartclaw/smartclaw/gateway/models.py` 的 ChatRequest 模型
    - 新增 `model: str | None = Field(default=None, description="可选模型引用，格式 'provider/model'")` 字段
    - _需求: 4.1_

  - [x] 7.2 实现 chat 端点的模型切换逻辑
    - 在 `smartclaw/smartclaw/gateway/routers/chat.py` 的 `chat()` 中：
      - 当 `request_body.model` 为 None 或空字符串时，使用 `runtime.graph`（默认 graph）
      - 当 `request_body.model` 有值时，调用 `parse_model_ref()` 验证格式
      - 验证通过后，创建临时 `ModelConfig`（仅替换 primary），调用 `build_graph(临时 config, runtime.tools)` 构建临时 graph
      - 使用临时 graph 调用 `invoke()`
      - `parse_model_ref()` 抛出 `ValueError` 时返回 HTTP 400
    - `chat_stream()` 实现相同的模型切换逻辑
    - _需求: 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x] 7.3 编写模型切换单元测试 `tests/gateway/test_model_override.py`
    - 测试 model=None 时使用默认 graph
    - 测试 model="" 时使用默认 graph
    - 测试有效 model 引用（如 "openai/gpt-4o"）时构建临时 graph
    - 测试无效 model 引用（如 "invalid"、""、"/"）时返回 HTTP 400
    - 测试临时 graph 使用的工具集与 runtime.tools 一致
    - _需求: 4.1, 4.2, 4.3, 4.5, 4.6_

  - [x] 7.4 编写属性测试：无模型覆盖时使用默认 graph
    - **Property 4: 无模型覆盖时使用默认 graph**
    - 使用 hypothesis 生成 model=None 或 model=""（`st.one_of(st.none(), st.just(""))`）
    - 验证 chat 端点使用 AgentRuntime 中预编译的默认 graph，不创建临时 graph
    - 文件: `tests/gateway/test_model_override_props.py`
    - **验证: 需求 4.2**

  - [x] 7.5 编写属性测试：有效模型覆盖使用相同工具集
    - **Property 5: 有效模型覆盖使用相同工具集**
    - 使用 hypothesis 生成随机有效 model 引用（`st.from_regex(r'[a-z]+/[a-z0-9-]+')`）
    - 验证临时 graph 使用的工具集与 `AgentRuntime.registry` 中的工具集完全一致
    - 文件: `tests/gateway/test_model_override_props.py`
    - **验证: 需求 4.3, 4.6**

  - [x] 7.6 编写属性测试：无效模型引用返回错误
    - **Property 6: 无效模型引用返回错误**
    - 使用 hypothesis 生成随机无效 model 引用（`st.text()` 过滤掉含有效 `/` 分隔的格式）
    - 验证 chat 端点返回 HTTP 400 状态码
    - 文件: `tests/gateway/test_model_override_props.py`
    - **验证: 需求 4.5**

- [x] 8. 检查点 - 确保模型切换测试通过
  - 运行 `pytest tests/gateway/test_model_override.py tests/gateway/test_model_override_props.py -v`，确保所有测试通过，如有问题请询问用户。

- [x] 9. 一致性验证与最终集成
  - [x] 9.1 编写 CLI 与 Gateway 一致性集成测试 `tests/test_runtime_consistency.py`
    - 使用相同的 SmartClawSettings 分别调用 `setup_agent_runtime()`
    - 验证两次返回的 `tool_names` 列表完全一致
    - 验证两次返回的 `system_prompt` 内容完全一致
    - _需求: 6.1, 6.2_

  - [x] 9.2 验证现有测试不被破坏
    - 运行完整测试套件 `pytest tests/ -v`，确保所有现有测试通过
    - 修复因重构导致的任何测试失败
    - _需求: 全部_

- [x] 10. 最终检查点 - 确保全部测试通过
  - 运行 `pytest tests/ -v`，确保所有测试（包括新增和现有测试）全部通过，如有问题请询问用户。

## 备注

- 所有属性测试任务均为必须执行项，不可跳过
- 每个属性测试使用 hypothesis 库，最少运行 100 次迭代
- 每个属性测试用注释标注格式：`# Feature: smartclaw-gateway-full-agent, Property {number}: {property_text}`
- 测试文件遵循项目现有命名规范：单元测试 `test_*.py`，属性测试 `test_*_props.py`
- 检查点任务用于阶段性验证，确保增量开发的正确性
