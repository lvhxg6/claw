# SmartClaw 上传与文档分析设计

## 1. 目标

为 `smartclaw` 增加“图片、文档上传”能力，但按当前模型能力分层落地：

- 第一阶段：支持文档上传、文本提取、内容分析
- 第一阶段：支持图片上传、预览、会话关联，但默认不做图片语义理解
- 第二阶段：按需补 OCR 或多模态模型接入

这次设计的目标不是做完整多模态平台，而是在不破坏现有 `chat / stream / orchestrator / capability pack` 链路的前提下，让上传类输入成为 SmartClaw 的标准输入源之一。

---

## 2. 当前调研结论

### 2.1 当前页面与网关

当前页面没有附件上传入口，只有文本输入。[index.html](/Users/liubu/hx/hxWork/35.AI测试/claw/smartclaw/smartclaw/gateway/static/index.html)

当前聊天请求模型 `ChatRequest` 只支持文本和执行控制字段，不支持：

- `files`
- `attachments`
- `images`
- `multipart/form-data`

见 [models.py](/Users/liubu/hx/hxWork/35.AI测试/claw/smartclaw/smartclaw/gateway/models.py#L10)。

当前 `/api/chat` 和 `/api/chat/stream` 也只接 JSON 文本请求，没有 `UploadFile` 或 `File(...)` 处理。[chat.py](/Users/liubu/hx/hxWork/35.AI测试/claw/smartclaw/smartclaw/gateway/routers/chat.py#L223) [chat.py](/Users/liubu/hx/hxWork/35.AI测试/claw/smartclaw/smartclaw/gateway/routers/chat.py#L300)

### 2.2 Agent 内部能力

Agent 内部已经存在 `create_vision_message()`，可以构造 `text + image_url(data URI)` 的多模态消息。[graph.py](/Users/liubu/hx/hxWork/35.AI测试/claw/smartclaw/smartclaw/agent/graph.py#L452)

说明内部消息层并不排斥图片输入，但当前网关和页面没有把它接起来。

### 2.3 依赖现状

当前项目依赖中没有文档提取专用库，例如：

- `pypdf`
- `python-docx`
- `openpyxl`
- `unstructured`
- `pymupdf`

见 [pyproject.toml](/Users/liubu/hx/hxWork/35.AI测试/claw/smartclaw/pyproject.toml#L1)。

这意味着：

- `txt / md / json / yaml / csv` 可以直接先做
- `pdf / docx / xlsx` 如果要稳定支持，需要补解析依赖

---

## 3. 需求边界

### 3.1 本次必须支持

- 页面可选择并上传附件
- 会话级关联附件
- 文档类附件可抽取文本并参与分析
- 上传后的附件可在当前会话中复用
- `chat` 和 `chat/stream` 均可使用附件
- 能与 `classic / orchestrator / capability pack` 共存

### 3.2 本次明确不做

- 图片语义理解
- OCR
- Word/PDF 的复杂版式还原
- 表格文件的高级结构理解
- 跨会话长期资产管理平台

### 3.3 本次图片处理策略

图片第一版支持：

- 上传
- 预览
- 附件元数据展示
- 和会话绑定

但默认不支持：

- “识别图片里有什么”
- “分析截图内容”
- “提取图片文字”

如果用户上传图片并要求理解内容，系统应明确提示：

`当前模型链路未启用图片理解能力，可改用 OCR 或多模态模型扩展。`

---

## 4. 设计原则

### 4.1 不改坏现有聊天协议

不建议把 `/api/chat` 直接改成 `multipart/form-data`。

原因：

- 当前 `chat` 与 `chat/stream` 都是 JSON 请求
- 页面已经围绕 JSON + SSE 建好
- multipart 会让普通文本请求、流式请求、前端代码都更复杂

因此采用：

**两段式上传**

1. 先上传文件，拿到 `asset_id`
2. 再在聊天请求里引用 `attachment_ids`

### 4.2 附件是“输入资源”，不是“工具”

附件不应该被建成一个 tool。  
更合适的定位是：

- 上传后进入会话资源池
- 在请求构造阶段被整理成模型可消费输入
- 必要时由工具去读取结构化内容或做进一步处理

### 4.3 文档优先走“提取文本 + 限长注入”

对于非多模态模型，最稳的方式是：

- 文档上传
- 解析成纯文本
- 生成附件摘要
- 必要时截断/分块
- 注入到请求上下文

这和当前 SmartClaw 的 `memory/context/summarizer` 思路是一致的。

---

## 5. 总体架构

新增 5 个层次：

1. **Upload API**
   负责接收文件、做类型与大小校验、返回 `asset_id`

2. **Attachment Store**
   负责存储原始文件、元数据、提取结果、会话绑定

3. **Extraction Pipeline**
   负责按文件类型提取文本或生成不可解析提示

4. **Attachment Resolver**
   在 `chat` 请求进入 `invoke()` 前，把附件整理成模型输入上下文

5. **Frontend Attachment UI**
   负责文件选择、上传、展示、移除、复用

---

## 6. 推荐接口设计

### 6.1 上传接口

`POST /api/uploads`

请求：

- `multipart/form-data`
- 字段：
  - `file`
  - `session_key` 可选

响应：

```json
{
  "asset_id": "att_xxx",
  "filename": "baseline-report.pdf",
  "media_type": "application/pdf",
  "kind": "document",
  "size_bytes": 123456,
  "status": "uploaded",
  "extract_status": "pending"
}
```

### 6.2 查询接口

`GET /api/uploads/{asset_id}`

返回：

- 文件元数据
- 提取状态
- 提取摘要
- 是否可分析

### 6.3 删除接口

`DELETE /api/uploads/{asset_id}`

用于：

- 用户移除附件
- 会话内误传文件清理

### 6.4 会话附件列表

`GET /api/sessions/{session_key}/attachments`

返回该会话当前关联附件。

### 6.5 聊天请求扩展

在 `ChatRequest` 中新增：

```json
{
  "attachment_ids": ["att_xxx", "att_yyy"]
}
```

不直接上传文件，只引用已上传资源。

---

## 7. 数据模型设计

建议新增 `attachments` 表。

字段建议：

- `asset_id`
- `session_key`
- `filename`
- `media_type`
- `kind`
  - `image`
  - `document`
  - `text`
  - `table`
- `storage_path`
- `size_bytes`
- `sha256`
- `status`
  - `uploaded`
  - `parsed`
  - `failed`
- `extract_status`
  - `pending`
  - `success`
  - `unsupported`
  - `failed`
- `extract_text`
- `extract_summary`
- `error_message`
- `created_at`
- `updated_at`

如果不想立刻改主 `memory_store` 表结构，也可以先做：

- 文件落盘到 `uploads/`
- 元数据写单独 sqlite 表

但中期建议统一纳入现有存储层。

---

## 8. 存储策略

建议新增配置：

- `uploads.enabled`
- `uploads.root_dir`
- `uploads.max_file_size_mb`
- `uploads.max_files_per_session`
- `uploads.allowed_media_types`

推荐默认目录：

- workspace 模式：`{workspace}/.smartclaw/uploads`
- 全局模式：`~/.smartclaw/uploads`

原始文件不建议直接存数据库，建议：

- 文件落盘
- 元数据入库
- 提取文本入库

---

## 9. 文件类型策略

### 9.1 第一阶段直接支持

- `text/plain`
- `text/markdown`
- `application/json`
- `text/yaml`
- `text/csv`

处理方式：

- 直接读取文本
- 必要时按长度截断
- 为模型构造附件摘要和节选

### 9.2 第一阶段建议补依赖后支持

- `application/pdf`
  - 推荐：`pypdf`
- `application/vnd.openxmlformats-officedocument.wordprocessingml.document`
  - 推荐：`python-docx`

### 9.3 第二阶段再支持

- `xlsx`
  - 推荐：`openpyxl`
- `pptx`
- 扫描版 PDF
- 各类图片 OCR

### 9.4 图片策略

图片上传允许：

- `image/png`
- `image/jpeg`
- `image/webp`

但第一阶段提取策略为：

- 不做 OCR
- 不做图像语义理解
- 仅生成元数据：
  - 文件名
  - 媒体类型
  - 尺寸
  - 大小

并在分析阶段给出明确提示：

`该附件是图片，当前链路未启用图片识别能力。`

---

## 10. 文档提取链路

### 10.1 处理流程

上传成功后触发：

1. 校验 MIME / 扩展名 / 大小
2. 生成 `asset_id`
3. 保存原始文件
4. 根据类型路由到提取器
5. 写回 `extract_text / extract_summary / extract_status`

### 10.2 抽取器接口

建议新增模块：

`smartclaw/uploads/extractors/`

建议定义统一接口：

```python
class ExtractionResult:
    text: str
    summary: str | None
    supported: bool
    error: str | None
```

提取器实现：

- `plain_text.py`
- `markdown.py`
- `json_yaml.py`
- `csv.py`
- `pdf.py`
- `docx.py`
- `image.py`

### 10.3 提取输出形态

不要直接把全文原样塞进 prompt。  
建议为每个附件生成：

- `attachment summary`
- `attachment excerpt`
- `full extracted text` 存库

运行时只注入：

- 文件名
- 文件类型
- 提取摘要
- 截断后的关键内容

---

## 11. Chat 接入方式

### 11.1 请求模型扩展

`ChatRequest` 新增：

- `attachment_ids: list[str] | None`

### 11.2 解析阶段

在 [chat.py](/Users/liubu/hx/hxWork/35.AI测试/claw/smartclaw/smartclaw/gateway/routers/chat.py) 进入 `invoke()` 之前：

1. 解析 `attachment_ids`
2. 拉取附件元数据和提取结果
3. 生成 `attachment context`
4. 把它注入给 agent

### 11.3 推荐的注入方式

第一版建议不要重写整个 `invoke()` 输入协议。  
直接在网关层把附件内容组织成一段标准上下文，再拼接到用户消息前。

示例：

```text
[Attachments]
- baseline-report.pdf (application/pdf)
  Summary: ...
  Excerpt: ...
- hosts.csv (text/csv)
  Summary: ...
  Excerpt: ...

[User Request]
请分析这些文档并给出检查建议
```

这样改动最小，能兼容：

- `classic`
- `orchestrator`
- `capability pack`

### 11.4 中期优化

中期可把 `invoke()` 改造成支持：

- `user_message: str`
- 或 `input_messages: list[BaseMessage]`

这样后面若接 OCR 或多模态模型，可以自然接入 `create_vision_message()`。

---

## 12. 前端交互设计

### 12.1 输入区新增附件按钮

在当前输入工作台增加：

- 附件按钮
- 已选附件列表

### 12.2 上传交互

流程：

1. 选择文件
2. 调用 `/api/uploads`
3. 返回 `asset_id`
4. 在输入区显示附件 chip
5. 发送聊天请求时带 `attachment_ids`

### 12.3 附件卡展示

每个附件展示：

- 文件名
- 类型
- 提取状态
- 删除按钮

图片附件额外显示：

- 缩略图
- “当前不支持图片理解”的轻提示

### 12.4 分析前提示

如果当前请求只包含图片附件，且模型链路不是 OCR/多模态：

前端可以给出轻提示，但不拦截：

`当前上传的是图片附件，默认不会进行图片内容识别。`

---

## 13. Capability Pack 与 Orchestrator 兼容

附件能力不应绕开 capability pack。

建议：

- capability pack 可声明是否允许附件输入
- 可声明允许的附件类型
- 可声明单次最大附件数
- 可声明是否强制结构化输出

例如安全治理类 pack 可允许：

- `pdf`
- `docx`
- `csv`
- `txt`

但禁掉：

- 图片
- 大视频

对于 orchestrator：

- 附件应作为父会话输入上下文
- 子任务默认继承附件摘要，而不是全文重复注入
- 只有明确需要时才把具体附件文本传到 subagent

这样可以避免 token 爆炸。

---

## 14. 安全与治理

必须增加这些限制：

- 文件大小限制
- 类型白名单
- 扩展名和 MIME 双校验
- 路径隔离
- 临时文件清理
- 提取失败可观测

另外建议记录：

- 上传事件
- 提取事件
- 分析使用了哪些附件

方便后续审计。

---

## 15. 推荐分阶段实施

### Phase 1：文档上传基础版

实现：

- `/api/uploads`
- `/api/uploads/{id}`
- `attachment_ids`
- `txt/md/json/yaml/csv`
- 前端附件选择与显示
- 请求级附件上下文注入

这一阶段就可以满足：

- 上传文本和轻文档
- 让 SmartClaw 读取并分析

### Phase 2：常见办公文档

补依赖：

- `pypdf`
- `python-docx`

实现：

- PDF 文本提取
- DOCX 文本提取

### Phase 3：图片与 OCR 扩展

按需二选一：

1. OCR 路线
   - `tesseract` 或其他 OCR
2. 多模态路线
   - 将图片转成 `create_vision_message()`

当前你的诉求下，这一阶段可以先不做。

---

## 16. 推荐实施顺序

我建议按这个顺序开发：

1. 新增上传存储层
2. 新增上传接口
3. 扩展 `ChatRequest.attachment_ids`
4. 实现文档提取器
5. 在 chat router 中注入附件上下文
6. 改前端附件上传与显示
7. 补 capability pack 附件策略
8. 最后再考虑 OCR / 图片理解

---

## 17. 对当前诉求的最终建议

基于你“不是多模态模型，可以不支持图片识别”的要求，最合适的第一版是：

- **文档上传与分析做完整**
- **图片上传只做管理，不做理解**

也就是：

- 文档：真分析
- 图片：真上传，但只做占位与后续扩展入口

这样能最快落地，而且不会把当前 SmartClaw 的执行链路复杂化。

---

## 18. 下一步

如果进入实施，建议先做一个独立 Batch：

- `Upload Batch 1`
  - 上传 API
  - 附件元数据存储
  - 文本类文档提取
  - 前端附件 UI
  - `attachment_ids` 接入 chat

等这个 Batch 稳定后，再决定是否继续：

- `Upload Batch 2`
  - PDF / DOCX 支持

- `Upload Batch 3`
  - OCR / 图片理解

---

## 19. Upload Batch 1 详细范围

`Upload Batch 1` 只解决“上传文本/轻文档并参与分析”。

### 19.1 Batch 1 必须完成

- 上传 API
- 附件元数据存储
- 会话附件列表
- 文本类附件提取
- `attachment_ids` 接入 `chat` 与 `chat/stream`
- 前端附件上传与附件 chip 展示
- 图片上传但不做理解

### 19.2 Batch 1 不进入

- PDF / DOCX 正式支持
- OCR
- 图片内容理解
- 附件全文检索与向量索引
- capability pack 的附件类型治理

---

## 20. Batch 1 文件级改造清单

### 20.1 新增模块

建议新增目录：

`smartclaw/uploads/`

建议文件：

- `smartclaw/uploads/__init__.py`
- `smartclaw/uploads/models.py`
- `smartclaw/uploads/store.py`
- `smartclaw/uploads/service.py`
- `smartclaw/uploads/extractors/__init__.py`
- `smartclaw/uploads/extractors/base.py`
- `smartclaw/uploads/extractors/plain_text.py`
- `smartclaw/uploads/extractors/markdown.py`
- `smartclaw/uploads/extractors/json_yaml.py`
- `smartclaw/uploads/extractors/csv.py`
- `smartclaw/uploads/extractors/image_stub.py`
- `smartclaw/uploads/context_builder.py`

职责建议：

- `models.py`
  - 定义附件元数据和提取结果模型
- `store.py`
  - 管理附件元数据持久化
- `service.py`
  - 处理上传、校验、存盘、提取调度
- `extractors/*`
  - 各文件类型文本提取
- `context_builder.py`
  - 将附件转成 chat 上下文片段

### 20.2 网关层改造

需要改这些文件：

- [models.py](/Users/liubu/hx/hxWork/35.AI测试/claw/smartclaw/smartclaw/gateway/models.py)
- [app.py](/Users/liubu/hx/hxWork/35.AI测试/claw/smartclaw/smartclaw/gateway/app.py)
- [chat.py](/Users/liubu/hx/hxWork/35.AI测试/claw/smartclaw/smartclaw/gateway/routers/chat.py)

需要新增这些 router：

- `smartclaw/gateway/routers/uploads.py`

### 20.3 前端层改造

主要改：

- [index.html](/Users/liubu/hx/hxWork/35.AI测试/claw/smartclaw/smartclaw/gateway/static/index.html)

需要增加：

- 文件选择按钮
- 上传进度/状态
- 已关联附件列表
- 删除附件按钮
- 图片缩略图或图片标识

### 20.4 配置层改造

需要改：

- `smartclaw/config/settings.py`
- `config/config.example.yaml`

建议新增配置段：

```yaml
uploads:
  enabled: true
  root_dir: "{workspace}/.smartclaw/uploads"
  max_file_size_mb: 10
  max_files_per_session: 8
  allowed_media_types:
    - text/plain
    - text/markdown
    - application/json
    - text/yaml
    - text/csv
    - image/png
    - image/jpeg
    - image/webp
```

---

## 21. Batch 1 推荐接口合同

### 21.1 数据模型扩展

`ChatRequest` 新增：

```python
attachment_ids: list[str] | None = None
```

新增上传响应模型：

```python
class UploadResponse(BaseModel):
    asset_id: str
    session_key: str | None = None
    filename: str
    media_type: str
    kind: str
    size_bytes: int
    status: str
    extract_status: str
    extract_summary: str | None = None
```

新增附件列表模型：

```python
class AttachmentInfo(BaseModel):
    asset_id: str
    session_key: str | None
    filename: str
    media_type: str
    kind: str
    size_bytes: int
    status: str
    extract_status: str
    extract_summary: str | None
```

### 21.2 新增接口

#### `POST /api/uploads`

输入：

- `multipart/form-data`
- `file`
- `session_key` 可选

行为：

- 校验文件
- 生成 `asset_id`
- 落盘
- 写元数据
- 触发同步提取

#### `GET /api/uploads/{asset_id}`

返回单个附件详情。

#### `DELETE /api/uploads/{asset_id}`

删除附件及其元数据。

#### `GET /api/sessions/{session_key}/attachments`

列出当前会话全部附件。

### 21.3 与 chat 的集成方式

请求示例：

```json
{
  "message": "分析这些文档并总结风险点",
  "session_key": "sess_123",
  "attachment_ids": ["att_a", "att_b"],
  "mode": "auto"
}
```

---

## 22. Batch 1 运行时处理细节

### 22.1 上传后处理链路

建议流程：

1. 前端选中文件
2. 前端调用 `/api/uploads`
3. 服务端存盘到 upload root
4. 服务端根据 MIME 选择提取器
5. 写回：
   - `extract_status`
   - `extract_text`
   - `extract_summary`
6. 前端把返回结果加入当前会话附件列表

### 22.2 Chat 请求注入链路

在 [chat.py](/Users/liubu/hx/hxWork/35.AI测试/claw/smartclaw/smartclaw/gateway/routers/chat.py) 中，进入 `invoke()` 前增加：

1. `attachment_ids` 解析
2. 附件存在性校验
3. 会话权限校验
4. 附件上下文构造
5. 将附件上下文拼到最终用户消息前

建议增加一个辅助函数：

```python
def _compose_message_with_attachments(
    message: str,
    attachments: list[AttachmentRecord],
) -> str:
    ...
```

输出建议形态：

```text
[Attachments]
- hosts.csv
  Type: text/csv
  Summary: 包含 32 台主机的资产列表
  Excerpt:
  host,ip,env
  app-01,10.0.0.1,prod
  ...

- policy.md
  Type: text/markdown
  Summary: 防火墙基线要求说明
  Excerpt:
  ...

[User Request]
请基于这些附件进行分析
```

### 22.3 图片处理行为

图片上传后，提取器返回：

- `supported = false`
- `extract_status = unsupported`
- `extract_summary = "图片附件已上传，当前链路未启用图片理解能力"`

这样：

- 上传链路完整
- 会话资产完整
- 用户体验明确
- 不会误以为系统已经能读图

---

## 23. Batch 1 前端状态流

### 23.1 页面交互建议

在当前输入工作台增加一个附件按钮。

状态流：

1. 选择文件
2. 上传中
3. 上传成功
4. 提取成功 / 不支持 / 提取失败
5. 发送消息时自动带 `attachment_ids`

### 23.2 前端状态建议

建议在页面脚本增加：

- `uploadedAttachments = []`
- `uploading = false`

每个附件项建议包含：

- `asset_id`
- `filename`
- `media_type`
- `kind`
- `extract_status`
- `extract_summary`

### 23.3 UI 呈现建议

在输入区上方或下方展示附件 chip/list：

- 文档类：
  - `hosts.csv`
  - `已提取`
- 图片类：
  - `topology.png`
  - `仅上传，未识别`

每个附件可：

- 删除
- 查看摘要

### 23.4 新会话行为

如果当前是新会话、尚无 `session_key`：

- 允许先上传
- 上传接口可先生成临时 `session_key`
- 或在第一次发送消息前补齐 `session_key`

推荐方案：

**上传时若无 `session_key`，由服务端创建并返回一个新的 `session_key`。**

这样附件天然归属一个确定会话。

---

## 24. Batch 1 测试矩阵

### 24.1 后端单测

建议新增：

- `tests/uploads/test_service.py`
- `tests/uploads/test_store.py`
- `tests/uploads/test_extractors.py`
- `tests/gateway/test_uploads.py`

覆盖点：

- 上传成功
- MIME 不允许
- 文件超限
- 提取成功
- 图片返回 unsupported
- 删除附件
- 会话附件列表

### 24.2 Gateway 集成测试

覆盖：

- `POST /api/uploads`
- `GET /api/uploads/{id}`
- `DELETE /api/uploads/{id}`
- `GET /api/sessions/{key}/attachments`
- `POST /api/chat` 带 `attachment_ids`
- `POST /api/chat/stream` 带 `attachment_ids`

### 24.3 前端联调测试

至少验证：

1. 上传 `txt`
2. 上传 `md`
3. 上传 `csv`
4. 上传 `png`
5. 删除附件
6. 带附件发起聊天
7. 切换会话后附件列表刷新

### 24.4 回归重点

必须确认不影响：

- 普通纯文本聊天
- `classic` 模式
- `orchestrator` 模式
- 会话历史
- capability pack 选择
- 调试面板

---

## 25. Batch 1 之后的直接延伸

如果 `Batch 1` 验证通过，最自然的下一步不是 OCR，而是：

### 25.1 Batch 2A：PDF / DOCX

补依赖：

- `pypdf`
- `python-docx`

优先级高于 OCR。

原因：

- 更符合你当前“文档分析”主诉求
- 技术风险低于图片理解
- 更贴近安全治理类场景

### 25.2 Batch 2B：Capability Pack 附件治理

补能力包字段：

- `allowed_attachment_types`
- `max_attachment_count`
- `attachment_required`
- `attachment_context_budget`

这样不同业务包就能控制附件输入。

---

## 26. 推荐的下一步实施方式

如果现在从设计进入开发，我建议按下面的顺序：

1. 先补 `uploads` 模块和存储
2. 再补 `uploads router`
3. 再扩 `ChatRequest.attachment_ids`
4. 再把附件上下文接入 `chat router`
5. 最后改页面上传交互

这样做的好处是：

- 后端先稳定
- 前端联调更顺
- 任何一步都可单独验证

如果你继续，我下一步就可以直接把这份文档再推进成：

- `Upload Batch 1` 代码实施清单
- 精确到每个文件新增哪些类、函数、测试
