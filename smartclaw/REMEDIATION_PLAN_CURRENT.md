# SmartClaw 安全整改方案

**生成时间**: 2025-06-10  
**基于检查报告**: 
- SECURITY_AUDIT_REPORT.md
- DEPENDENCY_AUDIT_REPORT.md
- SECURITY_CHECK_REPORT_FINAL.md

---

## 1. 整改方案概述

### 1.1 整改目标
基于前期安全检查和依赖安全检查的发现，制定本整改方案，旨在：
- 修复代码中残留的安全配置问题
- 加固依赖版本约束
- 建立自动化安全扫描机制
- 提升整体安全基线

### 1.2 整改原则
- **低风险优先**: 优先实施无破坏性、可回滚的变更
- **配置优先**: 优先通过配置调整而非代码修改来解决问题
- **渐进式**: 分阶段实施，每阶段验证后再进行下一阶段
- **文档化**: 所有变更需记录原因和影响

---

## 2. 优先整改行动清单

### 🔴 P0 - 立即执行（1-2天内）

| # | 整改项 | 目标发现 | 影响文件 | 风险等级 | 需审批 |
|---|--------|----------|----------|----------|--------|
| 1 | 收紧 langchain 版本约束 | 依赖检查 #1 | `pyproject.toml` | 🟢 低 | 否 |
| 2 | 统一开发依赖到 dependency-groups | 依赖检查 #3 | `pyproject.toml` | 🟢 低 | 否 |
| 3 | 修复 CORS 代码默认值 | 安全检查 #2.2 | `smartclaw/config/settings.py` | 🟢 低 | 否 |
| 4 | 更新 uv.lock 锁定文件 | P0整改依赖 | `uv.lock` | 🟢 低 | 否 |

### 🟡 P1 - 短期执行（1周内）

| # | 整改项 | 目标发现 | 影响文件 | 风险等级 | 需审批 |
|---|--------|----------|----------|----------|--------|
| 5 | 添加依赖扫描 CI 工作流 | 依赖检查 #2 | `.github/workflows/security.yml` | 🟢 低 | 是 |
| 6 | 配置 Dependabot 自动更新 | 依赖检查 #4 | `.github/dependabot.yml` | 🟢 低 | 否 |
| 7 | 修复 PID 文件位置 | 安全检查 #2.2 | `start.sh`, `stop.sh` | 🟡 中 | 否 |

### 🟢 P2 - 中期执行（2-4周内）

| # | 整改项 | 目标发现 | 影响文件 | 风险等级 | 需审批 |
|---|--------|----------|----------|----------|--------|
| 8 | 审计日志持久化 | 安全检查 #4.2 | `smartclaw/observability/` | 🟡 中 | 是 |
| 9 | 添加 API 速率限制中间件 | 安全检查 #4.2 | `smartclaw/gateway/` | 🟡 中 | 是 |
| 10 | 配置加密支持评估 | 安全检查 #4.2 | 配置文件 | 🟢 低 | 是 |

---

## 3. 详细整改方案

### 3.1 P0 整改详情

#### 整改项 1: 收紧 langchain 版本约束

**目标发现**: DEPENDENCY_AUDIT_REPORT.md #1 - 宽松版本约束

**当前状态**:
```toml
# pyproject.toml
dependencies = [
    "langchain-openai",      # 无版本约束
    "langchain-anthropic",   # 无版本约束
]
```

**整改方案**:
```toml
# pyproject.toml
dependencies = [
    "langchain-openai>=1.0.0,<2.0.0",
    "langchain-anthropic>=1.0.0,<2.0.0",
]
```

**预期影响**:
- 防止自动更新引入破坏性变更
- 明确版本兼容性边界
- 需要执行 `uv lock` 更新锁定文件

**回滚方案**: 恢复原始 pyproject.toml 并重新锁定

---

#### 整改项 2: 统一开发依赖到 dependency-groups

**目标发现**: DEPENDENCY_AUDIT_REPORT.md #3 - 开发依赖未隔离

**当前状态**:
```toml
[project.optional-dependencies]
dev = ["pytest>=8.0.0", "pytest-asyncio>=0.23.0", ...]

[dependency-groups]
dev = ["types-pyyaml>=6.0.12.20250915"]
```

**整改方案**:
```toml
# 移除 [project.optional-dependencies] 中的 dev 组
# 统一迁移到 [dependency-groups]
[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-playwright>=0.4.0",
    "mypy>=1.9.0",
    "ruff>=0.3.0",
    "hypothesis>=6.98.0",
    "types-pyyaml>=6.0.12.20250915",
]
```

**预期影响**:
- 开发依赖与生产依赖完全分离
- 生产部署时不会安装测试工具
- 需要更新开发环境设置文档

**回滚方案**: 恢复 optional-dependencies 配置

---

#### 整改项 3: 修复 CORS 代码默认值

**目标发现**: SECURITY_CHECK_REPORT_FINAL.md #2.2 - CORS默认配置宽松

**当前状态**:
```python
# smartclaw/config/settings.py:245
cors_origins: List[str] = ["*"]  # 代码默认值过于宽松
```

**整改方案**:
```python
# smartclaw/config/settings.py:245
cors_origins: List[str] = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]  # 默认仅允许本地访问
```

**预期影响**:
- 代码默认值与配置文件保持一致
- 防止配置覆盖失效时的安全风险
- 无破坏性变更（配置文件已覆盖此值）

**回滚方案**: 恢复原始默认值

---

#### 整改项 4: 更新 uv.lock 锁定文件

**目标发现**: P0整改依赖

**整改方案**:
```bash
# 执行命令
uv lock
```

**预期影响**:
- 锁定文件反映新的版本约束
- 确保构建可复现性

**回滚方案**: 从 git 恢复原始 uv.lock

---

### 3.2 P1 整改详情

#### 整改项 5: 添加依赖扫描 CI 工作流

**目标发现**: DEPENDENCY_AUDIT_REPORT.md #2 - 缺少自动化依赖扫描

**整改方案**:
```yaml
# .github/workflows/security.yml
name: Security Scan

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]
  schedule:
    - cron: '0 0 * * 1'  # 每周一运行

jobs:
  dependency-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      
      - name: Install uv
        uses: astral-sh/setup-uv@v3
      
      - name: Run pip-audit
        run: |
          uv pip install pip-audit
          uv run pip-audit --desc --format=json --output=audit.json || true
      
      - name: Upload audit results
        uses: actions/upload-artifact@v4
        if: always()
        with:
          name: audit-results
          path: audit.json
```

**预期影响**:
- 自动检测新发现的 CVE 漏洞
- 每周定期扫描依赖安全
- 需要 GitHub Actions 启用权限

**回滚方案**: 删除工作流文件

---

#### 整改项 6: 配置 Dependabot 自动更新

**目标发现**: DEPENDENCY_AUDIT_REPORT.md #4 - 未配置依赖更新自动化

**整改方案**:
```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
    open-pull-requests-limit: 10
    reviewers:
      - "team-security"
    labels:
      - "dependencies"
      - "security"
    commit-message:
      prefix: "deps"
      include: "scope"
```

**预期影响**:
- 自动创建依赖更新 PR
- 及时获取安全补丁
- 需要配置审查人员

**回滚方案**: 删除 dependabot.yml 文件

---

#### 整改项 7: 修复 PID 文件位置

**目标发现**: SECURITY_CHECK_REPORT_FINAL.md #2.2 - PID文件存储在/tmp

**当前状态**:
```bash
# start.sh:45
PID_FILE="/tmp/smartclaw.pid"

# stop.sh:6
PID_FILE="/tmp/smartclaw.pid"
```

**整改方案**:
```bash
# 创建安全的 PID 目录
PID_DIR="${HOME}/.smartclaw/run"
mkdir -p "$PID_DIR"
PID_FILE="$PID_DIR/smartclaw.pid"
```

**预期影响**:
- PID 文件存储在用户私有目录
- 防止共享主机上的权限问题
- 需要创建目录的初始化逻辑

**回滚方案**: 恢复 /tmp 路径

---

### 3.3 P2 整改详情

#### 整改项 8: 审计日志持久化

**目标发现**: SECURITY_CHECK_REPORT_FINAL.md #4.2 - 审计日志未持久化

**整改方案**:
```python
# smartclaw/observability/audit_logger.py
import json
import os
from datetime import datetime
from pathlib import Path
import structlog

logger = structlog.get_logger()

AUDIT_LOG_PATH = Path(os.getenv("SMARTCLAW_AUDIT_LOG", "logs/audit.log"))

def log_security_event(event_type: str, details: dict):
    """记录安全事件到持久化存储"""
    event = {
        "timestamp": datetime.utcnow().isoformat(),
        "event_type": event_type,
        **details
    }
    
    # 写入文件
    AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIT_LOG_PATH, "a") as f:
        f.write(json.dumps(event) + "\n")
    
    # 同时输出到结构化日志
    logger.warning("security_event", **event)
```

**预期影响**:
- 安全事件持久化存储
- 支持后续安全分析
- 需要磁盘空间管理策略

**回滚方案**: 禁用文件输出，仅保留控制台日志

---

#### 整改项 9: 添加 API 速率限制中间件

**目标发现**: SECURITY_CHECK_REPORT_FINAL.md #4.2 - API请求频率限制

**整改方案**:
```python
# smartclaw/gateway/rate_limiter.py
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
import time
from collections import defaultdict

class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 60):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.requests = defaultdict(list)
    
    async def dispatch(self, request: Request, call_next):
        client_ip = request.client.host
        now = time.time()
        
        # 清理过期记录
        self.requests[client_ip] = [
            req_time for req_time in self.requests[client_ip]
            if now - req_time < 60
        ]
        
        # 检查限流
        if len(self.requests[client_ip]) >= self.requests_per_minute:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        
        self.requests[client_ip].append(now)
        return await call_next(request)
```

**预期影响**:
- 防止 API 暴力破解
- 防止资源耗尽攻击
- 需要监控误报情况

**回滚方案**: 移除中间件注册

---

#### 整改项 10: 配置加密支持评估

**目标发现**: SECURITY_CHECK_REPORT_FINAL.md #4.2 - 配置加密支持

**整改方案**:
评估以下方案，选择最适合的实现：

**方案 A: python-dotenv + 加密**
- 使用 Fernet 对称加密存储敏感值
- 密钥通过环境变量或密钥环提供

**方案 B: 集成 Vault**
- 使用 HashiCorp Vault 管理密钥
- 适合大规模部署

**方案 C: 系统密钥环增强**
- 增强现有 keyring 集成
- 将 .env 中的敏感值迁移到系统密钥环

**建议**: 优先实施方案 C，逐步迁移到方案 B

**预期影响**:
- 敏感配置不再以明文存储
- 需要密钥管理流程
- 增加运维复杂度

**回滚方案**: 恢复明文配置

---

## 4. 执行顺序建议

```
第1天:  P0整改
        ├── 整改项1: 收紧版本约束
        ├── 整改项2: 统一开发依赖
        ├── 整改项3: 修复CORS默认值
        └── 整改项4: 更新uv.lock

第2-3天: 验证P0
         └── 运行完整测试套件

第4-7天: P1整改
         ├── 整改项5: CI安全扫描
         ├── 整改项6: Dependabot配置
         └── 整改项7: PID文件位置

第2-4周: P2整改（按需）
         ├── 整改项8: 审计日志持久化
         ├── 整改项9: API速率限制
         └── 整改项10: 配置加密评估
```

---

## 5. 风险与缓解

| 整改阶段 | 潜在风险 | 缓解措施 |
|----------|----------|----------|
| P0 | 版本约束导致依赖冲突 | 先在开发环境测试 |
| P0 | 开发依赖迁移影响CI | 同步更新CI配置 |
| P1 | CI扫描误报 | 配置适当的忽略规则 |
| P1 | Dependabot PR过多 | 限制PR数量和频率 |
| P2 | 审计日志磁盘耗尽 | 配置日志轮转 |
| P2 | 速率限制影响正常用户 | 配置白名单和阈值调整 |

---

## 6. 验收标准

### P0 验收
- [ ] `pyproject.toml` 中 langchain 包有明确版本上限
- [ ] `[project.optional-dependencies]` 中无 dev 组
- [ ] `[dependency-groups.dev]` 包含所有开发依赖
- [ ] `smartclaw/config/settings.py` 中 cors_origins 默认值为本地地址
- [ ] `uv.lock` 已更新且 CI 通过

### P1 验收
- [ ] `.github/workflows/security.yml` 存在且运行成功
- [ ] `.github/dependabot.yml` 配置正确
- [ ] PID 文件存储在用户目录而非 /tmp

### P2 验收
- [ ] 安全事件写入持久化存储
- [ ] API 速率限制中间件生效
- [ ] 配置加密方案文档化

---

## 7. 附录

### 7.1 相关文件清单

**将被修改的文件**:
1. `pyproject.toml` - 依赖配置
2. `smartclaw/config/settings.py` - CORS默认值
3. `uv.lock` - 依赖锁定
4. `start.sh` - PID文件路径
5. `stop.sh` - PID文件路径

**将被创建的文件**:
1. `.github/workflows/security.yml` - CI安全扫描
2. `.github/dependabot.yml` - 自动依赖更新
3. `smartclaw/observability/audit_logger.py` - 审计日志（P2）
4. `smartclaw/gateway/rate_limiter.py` - 速率限制（P2）

### 7.2 回滚程序

如需回滚任何整改：
```bash
# 1. 从 git 恢复特定文件
git checkout HEAD -- pyproject.toml uv.lock

# 2. 或恢复整个提交
git revert <commit-hash>

# 3. 重新锁定依赖
uv lock

# 4. 验证恢复
uv run pytest
```

---

*方案生成时间: 2025-06-10*  
*方案版本: 1.0*  
*下次审查时间: 整改完成后*
