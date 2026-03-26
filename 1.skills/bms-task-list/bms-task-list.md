---
name: bms-task-list
description: 查询 BMS（Ultra-Smart 安全基线管理系统）统一任务列表。当用户提到查看任务、任务列表、BMS任务、扫描任务、资产任务等关键词时触发。通过 opencli bms task:list 命令执行查询，支持分页和多种筛选条件。
---

# BMS 任务列表查询

## 前置条件

执行任务查询前，先检查登录状态：

```bash
opencli bms whoami
```

如果显示"未登录"，先执行登录：

```bash
opencli bms login --username <账号> --password <密码> --url <BMS地址>
```

## 查询任务列表

### 基础查询（默认第1页，每页10条）

```bash
opencli bms task:list
```

### 分页查询

```bash
opencli bms task:list --page <页码> --page_size <每页数量>
```

### 按状态筛选

```bash
opencli bms task:list --plan_state <状态>
```

常见状态值：`已完成`、`进行中`、`等待中`、`失败`

### 完整参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| --page | 页码 | 1 |
| --page_size | 每页数量 | 10 |
| --plan_state | 计划状态筛选 | 不限 |
| --plan_property | 计划属性筛选 | 不限 |
| --plan_source | 计划来源筛选 | 不限 |
| --template_type | 模板类型筛选 | 不限 |

## 返回字段说明

| 字段 | 说明 |
|------|------|
| No | 序号 |
| TaskName | 任务名称 |
| State | 任务状态 |
| Progress | 执行进度 |
| IpNum | 涉及 IP 数量 |
| StartTime | 开始时间 |
| LastTaskId | 最近任务 ID |

## 典型用法示例

```bash
# 查看第2页，每页20条
opencli bms task:list --page 2 --page_size 20

# 只看进行中的任务
opencli bms task:list --plan_state 进行中

# 查看已完成任务，第1页
opencli bms task:list --plan_state 已完成 --page_size 20
```

## 注意事项

- token 有时效，过期后需重新执行 `opencli bms login`
- BMS 系统使用国密 SM2/SM4 加密，登录密码会自动加密后发送，无需手动处理
- 该账号的 JWT tenant 为空字符串属于正常情况，系统已自动处理
