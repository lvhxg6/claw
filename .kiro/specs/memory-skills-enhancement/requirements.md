# 需求文档：记忆系统与 Skills 热加载增强

## 简介

基于对 OpenClaw 和 Deer-Flow 的对比分析（详见 `docs/memory-skills-hotreload-comparison.md`），SmartClaw 当前在以下方面存在不足：(1) 缺乏长期记忆支持，无法从 Markdown 文件加载用户知识；(2) 没有 Bootstrap Files 机制，无法定义 Agent 人格和用户信息；(3) Skills 系统不支持热加载，修改 SKILL.md 后需要重启服务；(4) 配置文件变更后需要手动重启。

本功能从 OpenClaw 和 Deer-Flow 中吸收最佳实践，为 SmartClaw 实现：(1) MEMORY.md 长期记忆支持；(2) Bootstrap Files 机制（SOUL.md、USER.md、TOOLS.md）；(3) 基于 watchdog 的 Skills 热加载；(4) 配置文件热加载；(5) memory/ 目录自动索引；(6) sqlite-vec 向量检索（Hybrid Search）；(7) 可选的 LLM 自动事实提取。

## 术语表

- **MEMORY.md**: 工作空间根目录下的长期记忆文件，用户手写的知识和事实，加载到 Agent 上下文
- **Bootstrap_Files**: 启动时加载的配置文件集合，包括 SOUL.md、USER.md、TOOLS.md 等，用于定义 Agent 身份和行为
- **SOUL.md**: Agent 人格定义文件，包含核心价值观、行为边界和沟通风格
- **USER.md**: 用户信息文件，包含用户名称、时区、偏好等个性化信息
- **TOOLS.md**: 工具配置说明文件，包含工具使用指南和本地配置
- **SkillsWatcher**: 基于 watchdog 的文件监听器，监听 SKILL.md 文件变化并触发热加载
- **ConfigWatcher**: 配置文件监听器，监听 config.yaml 变化并触发配置重载
- **MemoryLoader**: 记忆加载器，负责从 MEMORY.md 和 memory/ 目录加载 Markdown 文件
- **MemoryIndexManager**: 记忆索引管理器，负责 Markdown 分块、向量化和检索
- **sqlite_vec**: SQLite 向量扩展，用于存储和检索向量嵌入
- **Hybrid_Search**: 混合搜索算法，结合 BM25 关键词搜索和向量语义搜索
- **BM25**: Best Matching 25 算法，基于词频的关键词检索算法
- **Embedding_Provider**: 向量嵌入提供商，将文本转换为向量表示（如 OpenAI、Ollama）
- **FactExtractor**: 事实提取器，使用 LLM 从对话中自动提取结构化事实
- **Debounce**: 防抖机制，在指定时间窗口内合并多次触发为一次执行
- **SkillsVersion**: Skills 版本号，基于时间戳的单调递增版本标识

## 需求

### 需求 1：MEMORY.md 长期记忆支持

**用户故事：** 作为用户，我希望能够在工作空间根目录创建 MEMORY.md 文件记录长期知识，Agent 在对话时能够参考这些信息，以提供更个性化和准确的回答。

#### 验收标准

1. THE MemoryLoader SHALL 在 Agent 启动时扫描工作空间根目录，查找 `MEMORY.md` 或 `memory.md` 文件（大小写不敏感，优先使用大写版本）
2. WHEN MEMORY.md 文件存在时，THE MemoryLoader SHALL 读取文件内容并解析为结构化文本块
3. THE MemoryLoader SHALL 对 MEMORY.md 文件大小进行限制，最大不超过 2MB，超过时记录警告日志并截断
4. THE MemoryLoader SHALL 将加载的记忆内容注入到 Agent 的系统提示词中，放置在 skills_section 之前
5. THE MemoryLoader SHALL 支持通过配置项 `memory.enabled`（默认 true）控制是否启用记忆加载
6. WHEN MEMORY.md 文件不存在时，THE MemoryLoader SHALL 静默跳过，不影响 Agent 正常启动
7. THE MemoryLoader SHALL 在加载成功后记录 INFO 级别日志，包含文件路径和内容大小

### 需求 2：Bootstrap Files 机制

**用户故事：** 作为用户，我希望能够通过 SOUL.md 定义 Agent 的人格特征，通过 USER.md 提供我的个人信息，使 Agent 的回答更符合我的期望和习惯。

#### 验收标准

1. THE BootstrapLoader SHALL 支持以下 Bootstrap 文件，按优先级从高到低查找：工作空间级（`<workspace>/`）、全局级（`~/.smartclaw/`）
2. THE BootstrapLoader SHALL 支持加载以下文件类型：
   - `SOUL.md` — Agent 人格定义，加载到系统提示词开头
   - `USER.md` — 用户信息，加载到系统提示词中
   - `TOOLS.md` — 工具配置说明，加载到工具描述部分
3. WHEN 同一文件在多个级别存在时，THE BootstrapLoader SHALL 使用工作空间级文件覆盖全局级文件
4. THE BootstrapLoader SHALL 对每个 Bootstrap 文件大小进行限制，最大不超过 512KB
5. THE BootstrapLoader SHALL 实现文件缓存机制，基于文件修改时间（mtime）判断是否需要重新加载
6. THE BootstrapLoader SHALL 支持通过配置项 `bootstrap.enabled`（默认 true）控制是否启用 Bootstrap 加载
7. THE BootstrapLoader SHALL 在加载 SOUL.md 时，将内容作为系统提示词的第一部分，优先级高于默认 SYSTEM_PROMPT
8. THE BootstrapLoader SHALL 在加载 USER.md 时，将内容注入到系统提示词的用户上下文部分
9. WHEN Bootstrap 文件包含无效内容（如二进制数据）时，THE BootstrapLoader SHALL 记录警告日志并跳过该文件

### 需求 3：Skills 热加载

**用户故事：** 作为开发者，我希望修改 SKILL.md 文件后无需重启服务，系统能够自动检测变化并重新加载技能，以提高开发效率。

#### 验收标准

1. THE SkillsWatcher SHALL 使用 watchdog 库监听以下目录中的 SKILL.md 文件变化：
   - `<workspace>/skills/` — 工作空间级技能
   - `~/.smartclaw/skills/` — 全局级技能
2. THE SkillsWatcher SHALL 监听以下文件事件：创建（add）、修改（change）、删除（unlink）
3. THE SkillsWatcher SHALL 实现防抖机制，默认防抖时间为 250ms，在防抖窗口内的多次变化合并为一次重载
4. THE SkillsWatcher SHALL 维护 SkillsVersion 版本号，每次重载时更新为当前时间戳，保证单调递增
5. THE SkillsWatcher SHALL 忽略以下目录：`.git`、`__pycache__`、`venv`、`.venv`、`node_modules`、`.idea`、`.vscode`
6. WHEN 检测到 SKILL.md 变化时，THE SkillsWatcher SHALL 调用 SkillsLoader.reload() 方法重新加载所有技能
7. THE SkillsWatcher SHALL 支持通过配置项 `skills.hot_reload`（默认 true）控制是否启用热加载
8. THE SkillsWatcher SHALL 支持通过配置项 `skills.debounce_ms`（默认 250）配置防抖时间
9. THE SkillsWatcher SHALL 在重载成功后记录 INFO 级别日志，包含变化的文件路径和新版本号
10. IF 重载过程中发生错误，THEN THE SkillsWatcher SHALL 记录 ERROR 级别日志并保持使用上一个有效版本的技能

### 需求 4：配置文件热加载

**用户故事：** 作为运维人员，我希望修改 config.yaml 后无需重启服务，系统能够自动应用新配置，以减少服务中断时间。

#### 验收标准

1. THE ConfigWatcher SHALL 使用 watchdog 库监听 `config.yaml` 文件变化
2. THE ConfigWatcher SHALL 实现防抖机制，默认防抖时间为 500ms
3. WHEN 检测到 config.yaml 变化时，THE ConfigWatcher SHALL 重新解析配置文件并验证配置有效性
4. IF 新配置验证通过，THEN THE ConfigWatcher SHALL 更新运行时配置并发布 `config_reloaded` 事件
5. IF 新配置验证失败，THEN THE ConfigWatcher SHALL 记录 ERROR 级别日志并保持使用当前配置
6. THE ConfigWatcher SHALL 支持以下配置项的热更新：
   - `providers.*` — LLM 提供商配置
   - `memory.*` — 记忆系统配置
   - `skills.*` — 技能系统配置
   - `logging.level` — 日志级别
7. THE ConfigWatcher SHALL 不支持以下配置项的热更新（需要重启）：
   - `gateway.host` — API 网关主机
   - `gateway.port` — API 网关端口
8. THE ConfigWatcher SHALL 支持通过配置项 `config.hot_reload`（默认 true）控制是否启用配置热加载
9. THE ConfigWatcher SHALL 在配置重载成功后记录 INFO 级别日志，包含变更的配置项列表

### 需求 5：memory/ 目录自动索引

**用户故事：** 作为用户，我希望能够在 memory/ 目录下组织多个 Markdown 文件作为知识库，系统能够自动索引这些文件并在需要时检索相关内容。

#### 验收标准

1. THE MemoryLoader SHALL 扫描 `<workspace>/memory/` 目录下的所有 `.md` 文件（递归扫描子目录）
2. THE MemoryLoader SHALL 对每个 Markdown 文件进行分块处理，默认按 512 tokens 分块，重叠 64 tokens
3. THE MemoryLoader SHALL 为每个分块计算内容哈希（SHA-256 前 16 位），用于增量更新检测
4. THE MemoryLoader SHALL 支持通过配置项 `memory.chunk_tokens`（默认 512）配置分块大小
5. THE MemoryLoader SHALL 支持通过配置项 `memory.chunk_overlap`（默认 64）配置分块重叠
6. THE MemoryLoader SHALL 监听 memory/ 目录变化，当文件新增、修改或删除时自动更新索引
7. THE MemoryLoader SHALL 对 memory/ 目录总大小进行限制，最大不超过 50MB，超过时记录警告并跳过新文件
8. THE MemoryLoader SHALL 在索引完成后记录 INFO 级别日志，包含文件数量和分块数量

### 需求 6：sqlite-vec 向量检索

**用户故事：** 作为用户，我希望系统能够基于语义相似度检索记忆内容，而不仅仅是关键词匹配，以获得更准确的相关信息。

#### 验收标准

1. THE MemoryIndexManager SHALL 使用 sqlite-vec 扩展存储向量嵌入，与现有 SQLite 记忆存储统一
2. THE MemoryIndexManager SHALL 支持以下 Embedding Provider：
   - OpenAI（text-embedding-3-small，默认）
   - Ollama（本地模型）
   - 无 Provider 时降级为纯 BM25 关键词搜索
3. THE MemoryIndexManager SHALL 实现 Hybrid Search 算法，结合 BM25 和向量搜索：
   - 默认向量权重 0.7，关键词权重 0.3
   - 支持通过配置项 `memory.vector_weight` 和 `memory.text_weight` 调整权重
4. THE MemoryIndexManager SHALL 支持 MMR（Maximal Marginal Relevance）去重，避免返回高度相似的结果
5. THE MemoryIndexManager SHALL 支持通过配置项 `memory.top_k`（默认 5）配置返回结果数量
6. THE MemoryIndexManager SHALL 在检索时自动选择可用的 Embedding Provider，优先使用配置的 Provider，不可用时降级
7. WHEN 执行向量检索时，THE MemoryIndexManager SHALL 记录 DEBUG 级别日志，包含查询文本、检索耗时和结果数量
8. THE MemoryIndexManager SHALL 支持通过配置项 `memory.embedding_provider`（默认 "auto"）指定 Embedding Provider

### 需求 7：LLM 自动事实提取（可选）

**用户故事：** 作为用户，我希望系统能够自动从对话中提取重要事实并保存到记忆中，无需我手动维护 MEMORY.md 文件。

#### 验收标准

1. THE FactExtractor SHALL 在对话结束后（会话关闭或超过 5 分钟无活动）触发事实提取
2. THE FactExtractor SHALL 使用 LLM 分析对话内容，提取以下类型的事实：
   - 用户偏好（如编程语言、工具选择）
   - 项目信息（如项目名称、技术栈）
   - 工作上下文（如当前任务、目标）
3. THE FactExtractor SHALL 为每个提取的事实分配置信度分数（0.0-1.0），仅保存置信度高于 0.7 的事实
4. THE FactExtractor SHALL 对提取的事实进行去重，基于内容相似度判断是否为重复事实
5. THE FactExtractor SHALL 将提取的事实保存到 `<workspace>/.smartclaw/facts.json` 文件
6. THE FactExtractor SHALL 支持通过配置项 `memory.auto_extract`（默认 false）控制是否启用自动事实提取
7. THE FactExtractor SHALL 支持通过配置项 `memory.max_facts`（默认 100）限制保存的事实数量
8. WHEN 事实数量超过限制时，THE FactExtractor SHALL 按置信度排序，删除置信度最低的事实
9. THE FactExtractor SHALL 在提取完成后记录 INFO 级别日志，包含提取的事实数量和保存路径
