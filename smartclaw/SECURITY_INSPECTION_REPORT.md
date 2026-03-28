# SmartClaw 安全检查报告

**检查时间**: 2025年1月
**检查范围**: 本地工作区代码、配置文件、安全策略

---

## 1. 总体摘要

SmartClaw 项目整体安全架构良好，具备多层安全防护机制。主要安全特性包括：
- 路径安全策略 (PathPolicy) - 阻止敏感目录访问
- Shell 命令安全过滤 - 阻止危险命令执行
- SSRF 防护 - 阻止访问内网地址
- API 密钥管理 - 支持环境变量和系统密钥环
- CORS 配置 - 限制跨域来源

**总体评级**: 🟡 中低风险（发现2个中风险问题，建议修复）

---

## 2. 按严重级别分组的问题

### 🔴 高风险 (0)

未发现高风险安全问题。

### 🟡 中风险 (2)

#### 2.1 CORS 配置过于宽松
- **严重程度**: 中
- **证据**: `smartclaw/config/settings.py` 第 245 行
  ```python
  cors_origins: list[str] = Field(default_factory=lambda: ["*"])
  ```
- **影响路径**: `smartclaw/gateway/app.py` 第 186-193 行
- **风险说明**: 默认允许所有来源 (`["*"]`) 访问 API，可能导致 CSRF 攻击或敏感信息泄露。虽然生产环境可通过配置覆盖，但默认配置不安全。
- **建议修复**: 将默认值改为 `["http://localhost:8000", "http://127.0.0.1:8000"]`，与 `config/config.yaml` 中的配置保持一致。

#### 2.2 Shell 命令注入风险
- **严重程度**: 中
- **证据**: `smartclaw/tools/shell.py` 第 82-84 行
  ```python
  proc = await asyncio.create_subprocess_shell(
      command,
      stdout=asyncio.subprocess.PIPE,
      stderr=asyncio.subprocess.PIPE,
      cwd=cwd,
  )
  ```
- **影响路径**: `smartclaw/tools/shell.py`
- **风险说明**: 使用 `create_subprocess_shell` 执行用户输入的命令，虽然有过滤模式，但仍存在命令注入风险。例如 `echo "$(rm -rf /)"` 可能绕过简单的正则过滤。
- **建议修复**: 
  - 优先使用 `create_subprocess_exec` 配合参数列表
  - 或增加更严格的命令白名单机制
  - 对命令进行更严格的字符过滤（如禁止 `$()` 和反引号）

### 🟢 低风险 (3)

#### 3.1 文件上传大小限制
- **严重程度**: 低
- **证据**: `smartclaw/config/settings.py` 第 186 行
  ```python
  max_file_size_mb: int = Field(default=10, description="Maximum upload size in MB")
  ```
- **风险说明**: 10MB 上传限制在大多数情况下合理，但缺乏针对特定文件类型的细粒度控制。
- **建议**: 考虑为不同文件类型设置不同的大小限制。

#### 3.2 浏览器会话事件缓冲区
- **严重程度**: 低
- **证据**: `smartclaw/browser/session.py` 第 58-66 行
  ```python
  console_messages: deque[ConsoleEntry] = field(
      default_factory=lambda: deque(maxlen=500)
  )
  ```
- **风险说明**: 事件缓冲区有固定大小限制，但在高并发场景下可能占用较多内存。
- **建议**: 考虑添加基于时间的过期策略。

#### 3.3 临时 PID 文件位置
- **严重程度**: 低
- **证据**: `start.sh` 第 45 行, `stop.sh` 第 6 行
  ```bash
  echo $! > /tmp/smartclaw.pid
  PIDFILE="/tmp/smartclaw.pid"
  ```
- **风险说明**: PID 文件存储在 `/tmp` 目录，在共享主机上可能被其他用户访问或篡改。
- **建议**: 使用 `$HOME/.smartclaw/` 或 `/var/run/` (需要权限) 存储 PID 文件。

---

## 3. 安全亮点 ✅

### 3.1 路径安全策略 (PathPolicy)
- **文件**: `smartclaw/security/path_policy.py`
- **优点**: 
  - 默认阻止敏感目录 (`~/.ssh`, `~/.aws`, `/etc/shadow` 等)
  - 支持白名单/黑名单机制
  - 解析符号链接防止绕过
  - 记录安全审计日志

### 3.2 SSRF 防护
- **文件**: `smartclaw/tools/web_fetch.py` 第 63-89 行
- **优点**:
  - 检查私有 IP、回环地址、链路本地地址
  - 解析主机名到 IP 进行验证
  - 限制只允许 HTTP/HTTPS 协议

### 3.3 Shell 命令过滤
- **文件**: `smartclaw/tools/shell.py` 第 22-37 行
- **优点**:
  - 默认阻止危险命令 (`rm -rf`, `sudo`, `shutdown`, `dd`, `mkfs` 等)
  - 可配置的拒绝模式
  - 记录被阻止的命令到审计日志

### 3.4 API 密钥管理
- **文件**: `smartclaw/credentials.py`
- **优点**:
  - 支持环境变量和系统密钥环双重机制
  - `.env` 文件已被 `.gitignore` 排除
  - 提供安全的密钥设置接口

### 3.5 文件上传安全
- **文件**: `smartclaw/uploads/service.py`
- **优点**:
  - 媒体类型白名单验证
  - 文件大小限制
  - SHA256 哈希验证
  - 会话级别的文件数量限制

---

## 4. 剩余盲点

1. **依赖安全扫描**: 未对 `pyproject.toml` 中的依赖进行已知漏洞扫描
2. **密钥泄露检测**: 未扫描代码历史中的潜在密钥泄露
3. **容器安全**: 项目支持容器化部署，但未检查 Dockerfile 安全
4. **TLS/SSL 配置**: Gateway 默认使用 HTTP，未强制 HTTPS
5. **审计日志持久化**: 安全事件日志仅输出到控制台，未持久化存储

---

## 5. 建议的后续修复操作

| 优先级 | 操作 | 目标文件 |
|--------|------|----------|
| P1 | 修复 CORS 默认配置 | `smartclaw/config/settings.py` |
| P1 | 增强 Shell 命令安全 | `smartclaw/tools/shell.py` |
| P2 | 移动 PID 文件位置 | `start.sh`, `stop.sh` |
| P2 | 添加依赖漏洞扫描 | CI/CD 流程 |
| P3 | 添加 HTTPS 支持 | `smartclaw/gateway/app.py` |
| P3 | 审计日志持久化 | `smartclaw/observability/` |

---

## 6. 结论

SmartClaw 项目具有较好的安全基础架构，PathPolicy、SSRF 防护、Shell 命令过滤等核心安全机制实现完善。发现的主要问题是默认 CORS 配置过于宽松和 Shell 命令执行的潜在注入风险，建议优先修复。

**建议操作**:
1. 立即修复 CORS 默认配置
2. 评估 Shell 命令执行方式的安全性
3. 建立定期的依赖安全扫描流程
