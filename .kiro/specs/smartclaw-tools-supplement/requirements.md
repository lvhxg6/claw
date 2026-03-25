# Requirements Document

## Introduction

SmartClaw 是一个基于 LangChain + LangGraph 的 Python AI Agent 项目。当前工具集相对于 PicoClaw 缺失 3 个 P1 核心工具：`edit_file`（文件编辑）、`append_file`（文件追加）和 `web_fetch`（URL 内容抓取）。本需求文档定义这 3 个工具的功能、安全和集成要求，确保与现有工具体系（`SmartClawTool` 基类、`PathPolicy` 安全策略、`ToolRegistry` 注册机制）保持一致。

## Glossary

- **SmartClaw**: 基于 LangChain + LangGraph 的 Python AI Agent 项目
- **PicoClaw**: Go 语言实现的参考 AI Agent 项目，提供本需求的参考实现
- **SmartClawTool**: SmartClaw 中所有非浏览器工具的抽象基类，继承 LangChain `BaseTool`，提供 `_safe_run` 异步错误包装
- **PathPolicy**: SmartClaw 的文件系统安全策略引擎，基于白名单/黑名单 glob 模式控制路径访问
- **PathDeniedError**: 当路径违反 PathPolicy 安全策略时抛出的异常
- **ToolRegistry**: SmartClaw 的工具注册中心，管理工具的注册、发现和列表
- **EditFileTool**: 通过 old_text → new_text 精确替换方式编辑文件的工具
- **AppendFileTool**: 向文件末尾追加内容的工具
- **WebFetchTool**: 获取 URL 内容并转为可读文本的工具
- **SSRF**: Server-Side Request Forgery，服务端请求伪造攻击

## Requirements

### Requirement 1: EditFileTool — 文件精确替换编辑

**User Story:** As an AI Agent, I want to edit files by replacing exact text matches, so that I can make precise modifications to existing files without rewriting the entire content.

#### Acceptance Criteria

1. WHEN the Agent provides a valid file path, old_text, and new_text, THE EditFileTool SHALL read the file, replace the single occurrence of old_text with new_text, and write the result back to the file.
2. WHEN old_text does not exist in the target file, THE EditFileTool SHALL return an error message indicating that old_text was not found.
3. WHEN old_text appears more than once in the target file, THE EditFileTool SHALL return an error message indicating the number of occurrences and requesting more context to make the match unique.
4. WHEN the file path violates the PathPolicy, THE EditFileTool SHALL return an error message without reading or modifying the file.
5. WHEN the target file does not exist, THE EditFileTool SHALL return an error message indicating the file was not found.
6. THE EditFileTool SHALL accept three required parameters: path (string), old_text (string), and new_text (string).
7. THE EditFileTool SHALL use the `_safe_run` wrapper from SmartClawTool to catch and log all unexpected exceptions.

### Requirement 2: AppendFileTool — 文件内容追加

**User Story:** As an AI Agent, I want to append content to the end of a file, so that I can add new content without overwriting existing file content.

#### Acceptance Criteria

1. WHEN the Agent provides a valid file path and content, THE AppendFileTool SHALL append the content to the end of the file.
2. WHEN the target file does not exist, THE AppendFileTool SHALL create the file (including parent directories) and write the content.
3. WHEN the file path violates the PathPolicy, THE AppendFileTool SHALL return an error message without reading or modifying the file.
4. THE AppendFileTool SHALL accept two required parameters: path (string) and content (string).
5. THE AppendFileTool SHALL use the `_safe_run` wrapper from SmartClawTool to catch and log all unexpected exceptions.

### Requirement 3: WebFetchTool — URL 内容抓取

**User Story:** As an AI Agent, I want to fetch web page content and convert it to readable text, so that I can access and process online information.

#### Acceptance Criteria

1. WHEN the Agent provides a valid HTTP or HTTPS URL, THE WebFetchTool SHALL fetch the content and return extracted readable text.
2. WHEN the URL scheme is not HTTP or HTTPS, THE WebFetchTool SHALL return an error message indicating only HTTP and HTTPS URLs are allowed.
3. WHEN the URL points to a private or local network address (loopback, RFC 1918, link-local), THE WebFetchTool SHALL return an error message to prevent SSRF attacks.
4. WHEN the response content type is HTML, THE WebFetchTool SHALL strip script tags, style tags, and HTML tags, then normalize whitespace to produce readable plain text.
5. WHEN the response content type is JSON, THE WebFetchTool SHALL return the JSON content with indented formatting.
6. WHEN the response content exceeds the configured maximum character limit, THE WebFetchTool SHALL truncate the text and append a truncation indicator.
7. WHEN the HTTP request fails or times out, THE WebFetchTool SHALL return an error message describing the failure.
8. WHEN the response body exceeds the configured maximum byte limit, THE WebFetchTool SHALL return an error message indicating the size limit was exceeded.
9. THE WebFetchTool SHALL accept one required parameter url (string) and one optional parameter max_chars (integer, default 50000).
10. THE WebFetchTool SHALL enforce a configurable request timeout (default 60 seconds).
11. THE WebFetchTool SHALL use the `_safe_run` wrapper from SmartClawTool to catch and log all unexpected exceptions.

### Requirement 4: 工具注册集成

**User Story:** As a system integrator, I want the new tools to be automatically registered in the ToolRegistry, so that the Agent Graph can discover and use them without manual configuration.

#### Acceptance Criteria

1. THE `create_system_tools()` factory function SHALL register EditFileTool, AppendFileTool, and WebFetchTool in the returned ToolRegistry.
2. THE EditFileTool and AppendFileTool SHALL receive the same PathPolicy instance as the existing filesystem tools (ReadFileTool, WriteFileTool, ListDirectoryTool).
3. WHEN `create_system_tools()` is called, THE ToolRegistry SHALL contain all 8 system tools: read_file, write_file, list_directory, edit_file, append_file, exec_command, web_search, and web_fetch.
