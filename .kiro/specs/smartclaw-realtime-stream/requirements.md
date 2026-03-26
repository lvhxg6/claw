# 需求文档：SSE 实时流式展示 Agent 执行全过程

## 简介

当前 SmartClaw Gateway 的 `/api/chat/stream` SSE 端点仅在开始时发送一个 `thinking` 事件，然后等待 `invoke()` 完全执行完毕后才发送 `done` 事件。Agent 执行过程中的工具调用、LLM 推理等中间步骤对用户完全不可见，导致用户体验差、感知延迟高。

本功能通过在 Agent 执行过程中实时推送中间事件到 SSE 流，让用户在前端看到完整的"思考 → 调用工具 → 得到结果 → 继续思考 → 最终回答"全过程，实现真正的流式体验。

## 术语表

- **SSE_Stream**: Server-Sent Events 流式连接，Gateway 通过 `/api/chat/stream` 端点向前端推送实时事件的通道
- **Hook_Registry**: SmartClaw 的生命周期钩子注册系统（`hooks/registry.py`），支持 `tool:before`、`tool:after`、`llm:before`、`llm:after` 等钩子点
- **Event_Queue**: 每个 SSE 请求独立创建的 `asyncio.Queue` 实例，用于在 hook handler 和 SSE generator 之间传递事件
- **Hook_Handler**: 注册到 Hook_Registry 的异步回调函数，负责将 hook 事件写入 Event_Queue
- **Chat_Stream_Endpoint**: Gateway 的 `POST /api/chat/stream` SSE 端点，负责接收用户消息并以 SSE 格式返回 Agent 执行过程中的所有事件
- **Chat_Endpoint**: Gateway 的 `POST /api/chat` 同步端点，等待 Agent 执行完毕后一次性返回完整结果
- **Debug_UI**: SmartClaw 的前端调试界面（`gateway/static/index.html`），用于展示聊天交互和调试信息
- **SSE_Event**: 通过 SSE 协议推送的单个事件，包含 `event` 类型字段和 JSON 格式的 `data` 字段

## 需求

### 需求 1：SSE 事件队列桥接机制

**用户故事：** 作为开发者，我希望 Chat_Stream_Endpoint 能够通过 Event_Queue 实时接收 Agent 执行过程中的 hook 事件，以便将中间步骤推送给前端。

#### 验收标准

1. WHEN 一个 SSE 流请求到达 Chat_Stream_Endpoint 时，THE Chat_Stream_Endpoint SHALL 创建一个独立的 Event_Queue 实例（容量上限 200 条）
2. WHEN Event_Queue 创建完成后，THE Chat_Stream_Endpoint SHALL 为所有相关钩子点（`tool:before`、`tool:after`、`llm:before`、`llm:after`、`agent:start`、`agent:end`）注册临时 Hook_Handler
3. THE Hook_Handler SHALL 将接收到的 HookEvent 转换为字典格式并写入 Event_Queue
4. IF Event_Queue 已满，THEN THE Hook_Handler SHALL 丢弃该事件而非阻塞（使用 `put_nowait` 并捕获 `QueueFull` 异常）
5. WHEN `invoke()` 执行完毕且所有事件已推送后，THE Chat_Stream_Endpoint SHALL 从所有钩子点注销临时 Hook_Handler
6. WHEN SSE 连接断开或请求结束后，THE Chat_Stream_Endpoint SHALL 从所有钩子点注销临时 Hook_Handler，确保无资源泄漏

### 需求 2：SSE 中间事件类型定义与推送

**用户故事：** 作为前端开发者，我希望 SSE 流推送结构化的中间事件，以便前端能够解析并展示 Agent 执行的每个步骤。

#### 验收标准

1. WHEN Hook_Registry 触发 `llm:before` 钩子时，THE SSE_Stream SHALL 推送一个 `event: thinking` 类型的 SSE_Event，data 包含 `{"status": "reasoning", "iteration": <当前迭代轮次>}`
2. WHEN Hook_Registry 触发 `tool:before` 钩子时，THE SSE_Stream SHALL 推送一个 `event: tool_call` 类型的 SSE_Event，data 包含 `{"tool_name": "<工具名>", "args": <工具参数字典>, "tool_call_id": "<调用ID>"}`
3. WHEN Hook_Registry 触发 `tool:after` 钩子时，THE SSE_Stream SHALL 推送一个 `event: tool_result` 类型的 SSE_Event，data 包含 `{"tool_name": "<工具名>", "result": "<结果摘要，最长256字符>", "duration_ms": <耗时毫秒>, "success": <布尔值>}`
4. WHEN Hook_Registry 触发 `agent:start` 钩子时，THE SSE_Stream SHALL 推送一个 `event: iteration` 类型的 SSE_Event，data 包含 `{"current": <当前轮次>, "max": <最大轮次>}`
5. WHEN `invoke()` 成功完成时，THE SSE_Stream SHALL 推送一个 `event: done` 类型的 SSE_Event，data 包含 `{"session_key": "<会话ID>", "response": "<最终回答>", "iterations": <总迭代次数>}`
6. IF `invoke()` 执行过程中发生异常，THEN THE SSE_Stream SHALL 推送一个 `event: error` 类型的 SSE_Event，data 包含 `{"error": "<错误信息>"}`
7. THE SSE_Stream 的每个 SSE_Event 的 data 字段 SHALL 使用 JSON 格式编码，且使用 `ensure_ascii=False` 以支持中文内容

### 需求 3：SSE Generator 事件消费与推送

**用户故事：** 作为开发者，我希望 SSE generator 能够并发地从 Event_Queue 消费事件并推送给客户端，同时等待 `invoke()` 执行完毕后发送最终结果。

#### 验收标准

1. THE SSE generator SHALL 使用 `asyncio.create_task` 将 `invoke()` 作为后台任务执行，同时从 Event_Queue 读取事件
2. WHILE `invoke()` 任务尚未完成，THE SSE generator SHALL 以最长 1 秒的超时从 Event_Queue 读取事件并逐条推送
3. WHEN `invoke()` 任务完成后，THE SSE generator SHALL 排空 Event_Queue 中剩余的事件并全部推送
4. WHEN 所有中间事件推送完毕后，THE SSE generator SHALL 推送 `done` 或 `error` 事件作为最终事件
5. IF SSE 客户端断开连接，THEN THE SSE generator SHALL 取消 `invoke()` 任务并清理资源

### 需求 4：前端实时展示 Agent 执行过程

**用户故事：** 作为用户，我希望在 Debug_UI 的聊天区域实时看到 Agent 的思考过程、工具调用和工具结果，以便了解 Agent 正在做什么。

#### 验收标准

1. WHEN Debug_UI 收到 `thinking` 类型的 SSE_Event 时，THE Debug_UI SHALL 更新当前流式消息的文本为"⏳ 思考中...（第 N 轮）"，其中 N 为 iteration 值
2. WHEN Debug_UI 收到 `tool_call` 类型的 SSE_Event 时，THE Debug_UI SHALL 在聊天区域插入一条工具调用消息，显示工具名称和参数
3. WHEN Debug_UI 收到 `tool_result` 类型的 SSE_Event 时，THE Debug_UI SHALL 在聊天区域插入一条工具结果消息，显示结果摘要、耗时和成功/失败状态
4. WHEN Debug_UI 收到 `iteration` 类型的 SSE_Event 时，THE Debug_UI SHALL 更新当前流式消息的文本为"🔄 迭代 N/M"，其中 N 为当前轮次，M 为最大轮次
5. WHEN Debug_UI 收到 `done` 类型的 SSE_Event 时，THE Debug_UI SHALL 将流式消息更新为最终回答文本，移除加载动画，并显示迭代次数
6. WHEN Debug_UI 收到 `error` 类型的 SSE_Event 时，THE Debug_UI SHALL 将流式消息标记为错误样式并显示错误信息
7. THE Debug_UI SHALL 在每次收到新的 SSE_Event 后自动滚动聊天区域到底部

### 需求 5：向后兼容性保障

**用户故事：** 作为已有集成方，我希望同步 Chat_Endpoint 的行为和接口保持不变，以便现有调用方无需修改代码。

#### 验收标准

1. THE Chat_Endpoint（`POST /api/chat`）SHALL 保持现有的请求/响应格式不变（ChatRequest / ChatResponse）
2. THE Chat_Endpoint SHALL 继续同步等待 `invoke()` 完成后返回完整结果
3. THE SSE_Stream 的 `done` 事件 data 格式 SHALL 与当前已有的 `done` 事件 data 格式保持兼容，包含 `session_key`、`response`、`iterations` 字段
4. THE Hook_Handler 的注册和注销 SHALL 不影响 Hook_Registry 中已有的其他 handler（如 Debug SSE 广播 handler）
5. IF Chat_Stream_Endpoint 的 Event_Queue 机制发生异常，THEN THE Chat_Stream_Endpoint SHALL 回退到当前行为（仅发送 `thinking` + `done` 事件），确保基本功能可用

### 需求 6：SSE 事件数据格式规范

**用户故事：** 作为前端开发者，我希望所有 SSE 事件遵循统一的数据格式规范，以便前端能够可靠地解析和处理。

#### 验收标准

1. THE SSE_Stream 推送的每个事件 SHALL 包含 `event` 字段（事件类型）和 `data` 字段（JSON 字符串）
2. THE `thinking` 事件的 data SHALL 包含 `status`（字符串）和 `iteration`（整数）字段
3. THE `tool_call` 事件的 data SHALL 包含 `tool_name`（字符串）、`args`（对象）和 `tool_call_id`（字符串）字段
4. THE `tool_result` 事件的 data SHALL 包含 `tool_name`（字符串）、`result`（字符串，最长 256 字符）、`duration_ms`（数值）和 `success`（布尔值）字段
5. THE `iteration` 事件的 data SHALL 包含 `current`（整数）和 `max`（整数）字段
6. THE `done` 事件的 data SHALL 包含 `session_key`（字符串）、`response`（字符串）和 `iterations`（整数）字段
7. THE `error` 事件的 data SHALL 包含 `error`（字符串）字段
8. FOR ALL SSE_Event 类型，THE SSE_Stream 的 JSON 序列化 SHALL 使用 `ensure_ascii=False` 以正确传输中文等非 ASCII 字符
