---
name: project-health-check
description: 对指定项目目录进行全面健康检查。依次调用 list_directory、exec_command、write_file 等多个工具，检查目录结构、Git 状态、项目规模、最近修改文件，最终生成健康报告。当用户提到"项目检查"、"健康检查"、"项目状态"等关键词时触发。
---

# 项目健康检查 Skill

对指定的项目目录进行全面健康检查，需要依次调用多个工具完成以下步骤：

## 工作流程

### Step 1: 列出项目目录结构
使用 `list_directory` 工具列出项目根目录下的文件和文件夹，了解项目结构。

### Step 2: 检查 Git 状态
使用 `exec_command` 工具执行以下命令：
```bash
cd {project_path} && git status --short && echo "---COMMITS---" && git log --oneline -5
```
获取 Git 工作区状态和最近 5 次提交记录。

### Step 3: 统计项目规模
使用 `exec_command` 工具执行以下命令：
```bash
cd {project_path} && echo "文件数量:" && find . -type f | grep -v '.git/' | wc -l && echo "目录数量:" && find . -type d | grep -v '.git/' | wc -l && echo "磁盘占用:" && du -sh . 2>/dev/null
```

### Step 4: 查找最近修改的文件
使用 `exec_command` 工具执行：
```bash
cd {project_path} && find . -type f -not -path './.git/*' -mtime -1 | head -20
```
列出最近 24 小时内修改过的文件。

### Step 5: 生成健康报告
将以上所有信息整理成一份结构化的健康报告，使用 `write_file` 工具写入到 `{project_path}/HEALTH_REPORT.md`。

报告格式：
```markdown
# 项目健康报告
生成时间: <当前时间>

## 目录结构
<Step 1 的结果>

## Git 状态
<Step 2 的结果>

## 项目规模
<Step 3 的结果>

## 最近修改
<Step 4 的结果>

## 总结
<根据以上信息给出的健康评估>
```

## 注意事项
- 如果用户没有指定项目路径，询问用户
- 如果项目不是 Git 仓库，跳过 Git 状态检查，在报告中注明
- 如果某个步骤执行失败，记录错误信息并继续执行后续步骤
- 报告使用中文
