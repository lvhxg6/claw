---
name: dify-knowledge-search
description: 通过 Dify 知识库检索相关信息并基于检索结果进行润色回答。当用户提出需要查询知识库的问题时触发，使用 opencli dify retrieve 命令检索知识库，然后根据返回的文档片段整理、润色后给出高质量回答。适用于用户提到"查一下知识库"、"检索"、"知识库里有没有"、"帮我查"等场景。
---

# Dify 知识库检索与智能回答

本 skill 提供基于 Dify 知识库的检索能力，通过 opencli dify retrieve 命令查询知识库，并对检索结果进行润色整理后回答用户问题。

## 触发条件

- 用户提到需要从知识库中查找信息："查一下知识库"、"检索一下"、"知识库里有没有"、"帮我查"
- 用户提出的问题可能需要知识库中的文档来回答
- 用户明确要求使用 Dify 知识库

## 前置条件

- opencli 已安装且 dify 插件已注册
- Dify API 配置已完成（base_url、api_key）
- 用户需要提供知识库 ID（dataset_id），或者使用默认知识库

## 工作流程

### Step 1: 确认检索参数

从用户的问题中提取：
1. 检索关键词（query）：从用户问题中提炼核心关键词
2. 知识库 ID（dataset_id）：用户指定或使用默认值
3. 返回数量（top_k）：默认 5，用户可指定

如果用户没有提供 dataset_id，询问用户要检索哪个知识库。

### Step 2: 执行检索

使用以下命令执行知识库检索：

```bash
opencli dify retrieve --dataset_id <dataset_id> --query "<关键词>" --top_k <数量>
```

可用参数：
- `--dataset_id`（必填）：知识库 ID
- `--query`（必填）：检索关键词
- `--top_k`（可选，默认 5）：返回结果数量
- `--search_method`（可选，默认 semantic_search）：检索方法，可选 keyword_search / semantic_search / full_text_search / hybrid_search
- `--score_threshold`（可选）：相关性得分阈值，0-1 之间

### Step 3: 分析检索结果

检索结果为表格格式，包含：
- Score：相关性得分
- DocumentName：来源文档名
- Content：匹配的文档片段内容

对结果进行分析：
- 按 Score 从高到低关注结果
- 识别与用户问题最相关的片段
- 如果结果不够理想（Score 过低或内容不相关），可以调整关键词重新检索

### Step 4: 润色回答

基于检索到的文档片段，进行润色整理后回答用户：

1. 综合多个相关片段的信息，形成完整的回答
2. 用自然流畅的语言组织内容，而不是简单罗列检索结果
3. 如果检索结果中有矛盾信息，指出并说明
4. 在回答末尾注明信息来源文档名称
5. 如果检索结果无法完全回答用户问题，明确说明哪些部分是基于知识库的，哪些是补充说明

### 回答格式

回答时遵循以下格式：

- 直接回答用户的问题，语言自然流畅
- 关键信息加以强调
- 如有操作步骤，使用有序列表
- 末尾标注来源：`📚 来源：<文档名1>、<文档名2>`

### 检索失败处理

- 如果返回"网络连接失败"：检查 Dify API 配置是否正确
- 如果返回"未找到相关结果"：建议用户换个关键词或检查 dataset_id
- 如果返回"API Key 无效"：提示用户重新配置 API Key

## 示例交互

用户："帮我查一下知识库里关于 opencli 怎么安装的"

执行：
```bash
opencli dify retrieve --dataset_id 6808a7a7-17a3-47d7-9ff1-80825903b87d --query "opencli 安装"
```

回答示例：
> opencli 的安装步骤如下：
> 1. 首先确保已安装 Node.js 环境
> 2. 通过 npm 全局安装：`npm install -g @jackwener/opencli`
> 3. 安装完成后执行 `opencli --help` 验证
>
> 📚 来源：opencli_bms_integration.md
