# Implementation Plan: 吸收 DeerFlow 四大优势能力

## Overview

增量实现五个主要领域：(1) 增强 Supervisor 提示词，(2) 增强 SpawnSubAgentTool 描述，(3) 澄清中断机制（ask_clarification 工具 + AgentState 扩展 + action_node 拦截 + API 层），(4) 基于哈希滑动窗口的循环检测（LoopDetector + action_node/build_graph 集成），(5) 增强系统提示词。每个任务递增构建，属性测试使用 `hypothesis`。

## Tasks

- [x] 1. 增强 Supervisor 提示词和 SpawnSubAgentTool 描述
  - [x] 1.1 增强 `_SUPERVISOR_SYSTEM_PROMPT` in `smartclaw/smartclaw/agent/multi_agent.py`
    - 在现有提示词基础上追加决策树指导块（单 Agent 直接分配、多步骤顺序分解、并行批量规划、结果综合）
    - 追加批量规划指导，说明何时并行分配及 JSON 响应格式示例
    - 追加至少 2 个正面示例 + 2 个反面示例（用户请求、JSON 响应、简要解释）
    - 追加失败处理策略块（错误重分配、不完整结果补充、全部失败综合部分结果）
    - 保持 `{"agent": "<name>"}` 和 `{"agent": "done", "answer": "..."}` 格式不变
    - 总长度控制在 3000 Token 以内
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

  - [x] 1.2 增强 `SpawnSubAgentTool.description` in `smartclaw/smartclaw/agent/sub_agent.py`
    - 包含"何时使用"指南（独立上下文复杂子任务、不同工具集专业任务、可并行独立子任务）
    - 包含"何时不使用"指南（简单单步工具调用、需要当前对话上下文、需要紧密交互）
    - 包含任务描述编写指南（明确目标、必要背景、期望输出格式）
    - 总长度控制在 500 字符以内
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

- [x] 2. Checkpoint — 确保所有测试通过
  - 确保所有测试通过，如有问题请询问用户。

- [x] 3. 澄清中断机制 — 工具与状态层
  - [x] 3.1 创建 `AskClarificationTool` in `smartclaw/smartclaw/tools/clarification.py`
    - 定义 `AskClarificationInput` Pydantic model（question: str, options: list[str] | None）
    - 定义 `AskClarificationTool` BaseTool（name="ask_clarification"）
    - `_arun` 方法返回占位字符串（实际逻辑由 action_node 拦截）
    - _Requirements: 3.1_

  - [x] 3.2 扩展 `AgentState` in `smartclaw/smartclaw/agent/state.py`
    - 新增 `ClarificationRequest` TypedDict（question: str, options: list[str] | None）
    - 在 `AgentState` 中新增 `clarification_request: ClarificationRequest | None` 字段
    - _Requirements: 3.3_

  - [x] 3.3 修改 `action_node` 拦截 ask_clarification in `smartclaw/smartclaw/agent/nodes.py`
    - 遍历 tool_calls 时检查 `tool_name == "ask_clarification"`
    - 若匹配：提取 question 和 options，写入返回字典的 `clarification_request` 字段
    - 生成 ToolMessage 内容为 `"Clarification requested: {question}"`
    - 跳过同一批次中 ask_clarification 之后的工具调用
    - _Requirements: 3.2_

  - [x] 3.4 修改 `should_continue` 路由扩展 in `smartclaw/smartclaw/agent/nodes.py`
    - 在 error/final_answer 检查之后、tool_calls 检查之前，新增 `clarification_request` 检查
    - 当 `clarification_request` 非 None 时返回 `"end"`
    - _Requirements: 3.4_

  - [x] 3.5 编写澄清机制属性测试 in `smartclaw/tests/agent/test_clarification_props.py`
    - **Property 1: ask_clarification 拦截不变性**
    - **Validates: Requirements 3.2**
    - **Property 2: clarification_request 路由终止**
    - **Validates: Requirements 3.4**

- [x] 4. 澄清中断机制 — API 层与工具注册
  - [x] 4.1 扩展 API 模型 in `smartclaw/smartclaw/gateway/models.py`
    - 新增 `ClarificationData` Pydantic model（question: str, options: list[str] | None）
    - 在 `ChatResponse` 中新增 `clarification: ClarificationData | None = None` 字段
    - _Requirements: 3.5_

  - [x] 4.2 修改同步端点和 SSE 端点 in `smartclaw/smartclaw/gateway/routers/chat.py`
    - 同步 `chat` 端点：从 result 提取 `clarification_request`，映射到 `ChatResponse.clarification`
    - SSE `chat_stream` 端点：在 done 事件之前检查 `clarification_request`，发送 `clarification` 事件类型
    - 在 `_format_sse` 中处理 `clarification` hook_point
    - _Requirements: 3.5, 3.6, 3.8_

  - [x] 4.3 注册 AskClarificationTool in `smartclaw/smartclaw/tools/registry.py`
    - 在 `create_system_tools` 中导入并注册 `AskClarificationTool`
    - _Requirements: 3.7_

- [x] 5. Checkpoint — 确保所有测试通过
  - 确保所有测试通过，如有问题请询问用户。

- [x] 6. 基于哈希滑动窗口的循环检测
  - [x] 6.1 创建 `LoopDetector` 类 in `smartclaw/smartclaw/agent/loop_detector.py`
    - 定义 `LoopStatus` 枚举（OK, WARN, STOP）
    - 实现 `LoopDetector` 类，构造参数：window_size=20, warn_threshold=3, stop_threshold=5
    - 实现 `compute_hash` 静态方法：确定性 JSON 序列化 + SHA-256 前 16 位十六进制
    - 实现 `record` 方法：记录工具调用哈希，返回 LoopStatus
    - 内部使用 `deque(maxlen=window_size)` 作为滑动窗口
    - _Requirements: 4.1, 4.2, 4.3, 4.6_

  - [x] 6.2 集成 LoopDetector 到 `action_node` in `smartclaw/smartclaw/agent/nodes.py`
    - `action_node` 新增可选参数 `loop_detector: LoopDetector | None = None`
    - 每次工具调用执行后调用 `loop_detector.record(tool_name, tool_args)`
    - WARN：追加警告消息提示 LLM 检测到重复行为
    - STOP：设置 error 字段为循环检测错误信息
    - _Requirements: 4.4, 4.5, 4.7_

  - [x] 6.3 集成 LoopDetector 到 `build_graph` in `smartclaw/smartclaw/agent/graph.py`
    - `build_graph` 新增可选参数 `loop_detector: LoopDetector | None = None`
    - 将 loop_detector 传递给 `_action` 闭包
    - _Requirements: 4.8_

  - [x] 6.4 编写循环检测属性测试 in `smartclaw/tests/agent/test_loop_detector_props.py`
    - **Property 3: ToolCallHash 确定性**
    - **Validates: Requirements 4.2**
    - **Property 4: 滑动窗口有界性**
    - **Validates: Requirements 4.3**
    - **Property 5: 循环检测阈值正确性**
    - **Validates: Requirements 4.4, 4.5**
    - **Property 6: action_node 循环检测集成**
    - **Validates: Requirements 4.7**

- [x] 7. Checkpoint — 确保所有测试通过
  - 确保所有测试通过，如有问题请询问用户。

- [x] 8. 增强系统提示词
  - [x] 8.1 增强 `SYSTEM_PROMPT` in `smartclaw/smartclaw/agent/runtime.py`
    - 以独立指导块追加结构化思考指导（理解意图 → 评估澄清需求 → 制定计划 → 选择工具 → 执行验证）
    - 追加澄清工作流优先级指导（歧义请求、缺少关键参数、破坏性操作优先 ask_clarification）
    - 追加工具使用决策树（缩进列表，每个工具的适用场景和优先级）
    - 追加错误恢复指导（分析错误 → 尝试替代 → 多次失败说明情况）
    - 不修改现有工具使用说明部分，确保向后兼容
    - 总长度（不含 skills_section）控制在 2000 字符以内
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

- [x] 9. 集成到 invoke 初始状态
  - [x] 9.1 更新 `invoke` 函数的 `initial_state` in `smartclaw/smartclaw/agent/graph.py`
    - 在 `initial_state` 字典中添加 `clarification_request: None`
    - 确保新字段与 AgentState TypedDict 一致
    - _Requirements: 3.3_

- [x] 10. Final checkpoint — 确保所有测试通过
  - 确保所有测试通过，如有问题请询问用户。

## Notes

- 标记 `*` 的子任务为可选，可跳过以加速 MVP
- 每个任务引用具体需求以确保可追溯性
- Checkpoint 确保每个主要领域完成后的增量验证
- 属性测试验证通用正确性属性（使用 `hypothesis`）
- 设计文档中的 6 个正确性属性分布在任务 3.5（Property 1-2）和 6.4（Property 3-6）中
