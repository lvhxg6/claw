# SmartClaw 安全整改方案

**生成时间**: 2025-06-10  
**基于检查报告**: SECURITY_AUDIT_REPORT.md, DEPENDENCY_AUDIT_REPORT.md, SECURITY_CHECK_REPORT_FINAL.md  
**整改阶段**: 规划阶段 (本方案仅规划，不执行修改)

---

## 1. 执行摘要

基于全面的代码安全检查和依赖安全检查，SmartClaw 项目整体安全状况良好（综合评分 4.6/5.0）。高风险问题已整改完成，剩余中低风险问题可通过本方案进一步加固。

### 整改优先级分布

| 优先级 | 数量 | 风险等级 | 状态 |
|--------|------|----------|------|
| P1 (高) | 0 | - | 无待处理高风险 |
| P2 (中) | 3 | 中 | 建议修复 |
| P3 (低) | 2 | 低 | 可选改进 |

---

## 2. 整改行动清单

### 2.1 P2 优先级 (中等风险)

#### 行动 #1: 修复代码中CORS默认配置

| 属性 | 详情 |
|------|------|
| **目标发现** | SECURITY_CHECK_REPORT_FINAL.md - CORS默认配置宽松 |
| **风险描述** | `smartclaw/config/settings.py:245` 中 `cors_origins` 默认值为 `["*"]`，与配置文件不一致。若配置文件被绕过，可能导致任意来源访问 |
| **风险等级** | 🟡 中等 |
| **影响范围** | Gateway CORS策略 |

**建议修复**:
```python
# smartclaw/config/settings.py
class GatewaySettings(BaseSettings):
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:8000", "http://127.0.0.1:8000"]
        # 移除: default_factory=lambda: ["*"]
    )
```

**预期影响**: 确保代码默认值与配置文件安全策略一致，防止配置绕过攻击  
**受影响文件**: `smartclaw/config/settings.py`  
**变更类型**: 默认值修改 (低风险、可逆)  
**需审批**: 否 (与现有配置一致，无破坏性变更)

---

#### 行动 #2: 迁移开发依赖到独立组

| 属性 | 详情 |
|------|------|
| **目标发现** | DEPENDENCY_AUDIT_REPORT.md - 开发依赖未完全隔离 |
| **风险描述** | `[project.optional-dependencies]` 和 `[dependency-groups]` 并存，可能导致开发依赖混入生产环境 |
| **风险等级** | 🟡 中等 |
| **影响范围** | 依赖管理、生产部署 |

**建议修复**:
```toml
# pyproject.toml
# 移除 [project.optional-dependencies] 中的 dev 组
# 确保所有开发依赖仅在 [dependency-groups.dev] 中

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

**预期影响**: 清晰分离生产和开发依赖，减少生产环境攻击面  
**受影响文件**: `pyproject.toml`  
**变更类型**: 依赖配置重组 (低风险、可逆)  
**需审批**: 否

---

#### 行动 #3: 改进PID文件安全

| 属性 | 详情 |
|------|------|
| **目标发现** | SECURITY_CHECK_REPORT_FINAL.md - PID文件位置 |
| **风险描述** | `start.sh:45`, `stop.sh:6` 中 PID 文件存储在 `${RUNTIME_DIR}`，虽非 `/tmp` 但仍可能在共享环境存在风险 |
| **风险等级** | 🟡 中等 |
| **影响范围** | 进程管理、服务启停 |

**建议修复**:
```bash
# start.sh / stop.sh
# 添加PID文件权限控制
echo $! > "$PIDFILE"
chmod 600 "$PIDFILE"  # 仅所有者可读写
```

**预期影响**: 防止其他用户读取或篡改PID文件  
**受影响文件**: `start.sh`, `stop.sh`  
**变更类型**: 权限加固 (低风险、可逆)  
**需审批**: 否

---

### 2.2 P3 优先级 (低风险)

#### 行动 #4: 添加审计日志持久化配置

| 属性 | 详情 |
|------|------|
| **目标发现** | SECURITY_CHECK_REPORT_FINAL.md - 审计日志未持久化 |
| **风险描述** | 安全事件仅输出到控制台，未持久化存储，不利于事后追溯 |
| **风险等级** | 🟢 低 |
| **影响范围** | 日志系统、安全审计 |

**建议修复**:
```yaml
# config/config.yaml
logging:
  level: INFO
  format: json
  file: "${SMARTCLAW_LOG_DIR}/audit.log"  # 添加持久化配置
  
  # 新增审计专用配置
  audit:
    enabled: true
    file: "${SMARTCLAW_LOG_DIR}/security-audit.log"
    retention_days: 90
```

**预期影响**: 安全事件可追溯，满足合规要求  
**受影响文件**: `config/config.yaml`, `smartclaw/config/settings.py`  
**变更类型**: 功能增强 (低风险)  
**需审批**: 否

---

#### 行动 #5: 配置生产环境CORS模板

| 属性 | 详情 |
|------|------|
| **目标发现** | SECURITY_CHECK_REPORT_FINAL.md - 生产CORS需手动配置 |
| **风险描述** | 当前CORS仅允许本地访问，生产部署前需更新 |
| **风险等级** | 🟢 低 |
| **影响范围** | 生产部署 |

**建议修复**:
```yaml
# config/config.yaml
# 添加生产环境配置模板（注释形式）
gateway:
  cors_origins:
    - "http://localhost:8000"
    - "http://127.0.0.1:8000"
  # 生产环境配置示例:
  # cors_origins:
  #   - "https://yourdomain.com"
  #   - "https://app.yourdomain.com"
```

**预期影响**: 提供生产部署指导，减少配置错误  
**受影响文件**: `config/config.yaml`  
**变更类型**: 文档/注释 (无风险)  
**需审批**: 否

---

## 3. 安全加固建议 (非必须)

### 3.1 建议改进项

| 建议 | 优先级 | 说明 |
|------|--------|------|
| 配置密钥管理服务 | P2 | 使用系统密钥环存储API密钥，替代环境变量 |
| API请求频率限制 | P3 | 实现速率限制中间件防暴力破解 |
| TLS/SSL强制 | P3 | 生产环境强制HTTPS |

### 3.2 手动执行任务

以下任务需由运维人员手动执行：

```bash
# 1. 设置.env文件权限
chmod 600 .env

# 2. 配置API密钥（选择一种方式）
# 方式1: 环境变量
export KIMI_API_KEY="your-key"
export GLM_API_KEY="your-key"
export BRAVE_API_KEY="your-key"

# 方式2: 系统密钥环（推荐生产环境）
python -c "import keyring; keyring.set_password('kimi', 'api_key', 'YOUR_KEY')"
```

---

## 4. 执行顺序建议

```
Phase 1 (立即执行):
├── 行动 #3: PID文件权限加固
└── 手动任务: 设置.env权限为600

Phase 2 (本周内):
├── 行动 #1: 修复CORS默认配置
└── 行动 #2: 统一开发依赖管理

Phase 3 (下次迭代):
├── 行动 #4: 审计日志持久化
└── 行动 #5: 生产CORS配置模板
```

---

## 5. 回滚方案

每项整改均提供回滚能力：

| 行动 | 回滚方式 | 预计时间 |
|------|----------|----------|
| CORS默认配置 | 恢复代码中的默认值 | 1分钟 |
| 开发依赖迁移 | 恢复 [project.optional-dependencies] | 2分钟 |
| PID文件权限 | 移除 chmod 命令 | 1分钟 |
| 审计日志配置 | 移除配置项 | 1分钟 |

---

## 6. 剩余风险

整改完成后仍存在的风险：

| 风险 | 可能性 | 影响 | 缓解状态 |
|------|--------|------|----------|
| LangChain生态破坏性更新 | 中 | 中 | 版本上限约束已添加 |
| 新发现CVE未及时发现 | 低 | 高 | CI扫描已配置 |
| API密钥泄露（用户配置不当） | 中 | 高 | 需用户手动配置密钥环 |
| 传递依赖供应链攻击 | 低 | 高 | 锁定文件已缓解 |

---

## 7. 合规检查清单

- [x] 无硬编码API密钥
- [x] 依赖锁定文件完整 (uv.lock)
- [x] 已知CVE已修复 (cryptography, requests, pygments)
- [x] CORS配置已收紧
- [x] 网络绑定已限制 (127.0.0.1)
- [x] 路径访问控制已实施
- [x] SSRF防护已验证
- [x] Shell命令过滤已实施
- [x] 安全审计日志已添加
- [x] CI/CD安全扫描已配置
- [x] Dependabot已启用
- [ ] .env文件权限需手动设置
- [ ] 生产CORS配置需手动更新

---

## 8. 结论

SmartClaw 项目安全基础扎实，已实施多项安全最佳实践。本整改方案针对剩余中低风险项提供具体修复建议，所有建议均为低风险、可逆变更。建议在执行前进行代码审查，并在测试环境验证后部署到生产。

**整改后预期安全评分**: 4.8/5.0

---

*方案生成完成 - 2025-06-10*
