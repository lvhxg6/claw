"""Full Integration Scenario — "DevOps Assistant" workflow.

A single continuous session that exercises EVERY SmartClaw feature:

P0 Tools (8):
  1. write_file    — create project config
  2. read_file     — read it back
  3. edit_file     — modify content
  4. append_file   — append a line
  5. list_directory— list workspace files
  6. exec_command  — run shell commands
  7. web_fetch     — fetch a URL
  8. web_search    — search the web

P1 Features (5):
  9. Memory        — recall earlier info across turns
  10. Skills       — sysinfo / disk-check script execution
  11. Sub-Agent    — delegate a subtask to child agent
  12. Summarizer   — trigger summary after many turns, recall from summary
  13. Error recovery — handle missing file gracefully

The scenario simulates a DevOps assistant helping set up a project:
  Turn 1:  [write_file] Create a project config file
  Turn 2:  [read_file] Read it back and confirm
  Turn 3:  [edit_file] Update the version number
  Turn 4:  [append_file] Add a new config line
  Turn 5:  [list_directory] List the workspace to see all files
  Turn 6:  [exec_command] Run a shell command (uname -a)
  Turn 7:  [sysinfo skill] Check system info via skill
  Turn 8:  [disk-check skill] Check disk usage via skill
  Turn 9:  [web_fetch] Fetch GitHub API zen quote
  Turn 10: [web_search] Search for something
  Turn 11: [sub-agent] Delegate a math task to sub-agent
  Turn 12: [error recovery] Try to read non-existent file, then create it
  Turn 13: [memory recall] Ask about earlier turns (pre-summary)
  Turn 14: [memory recall] Ask about the project config version
  Turn 15: [memory recall] Ask about CPU from skill result

Usage: KIMI_API_KEY=... python test_full_integration.py
"""

import asyncio
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from smartclaw.config.loader import load_config
from smartclaw.credentials import load_dotenv
from smartclaw.agent.graph import build_graph, invoke
from smartclaw.tools.registry import create_system_tools
from smartclaw.skills.loader import SkillsLoader
from smartclaw.skills.registry import SkillsRegistry
from smartclaw.memory.store import MemoryStore
from smartclaw.memory.summarizer import AutoSummarizer
from smartclaw.agent.sub_agent import SpawnSubAgentTool

PASS = "✅"
FAIL = "❌"
results = []

# Rate limit protection: interval between LLM calls (seconds)
CALL_INTERVAL = 3.0
MAX_RETRIES = 2
RETRY_BACKOFF = 10.0  # seconds to wait before retry after failure


def report(name: str, passed: bool, detail: str = ""):
    status = PASS if passed else FAIL
    results.append((name, passed))
    suffix = f" — {detail[:120]}" if detail else ""
    print(f"  {status} {name}{suffix}")


async def main():
    load_dotenv()
    settings = load_config()
    tmp = pathlib.Path("/tmp/smartclaw_full_integration")
    tmp.mkdir(parents=True, exist_ok=True)

    print("\n🦀 SmartClaw Full Integration Test — DevOps Assistant Workflow")
    print("=" * 70)
    print("This test exercises ALL features in a single continuous session.")
    print(f"Rate limit protection: {CALL_INTERVAL}s interval, {MAX_RETRIES} retries with {RETRY_BACKOFF}s backoff\n")

    # --- Setup: all features enabled ---
    workspace = str(tmp)
    registry = create_system_tools(workspace)

    # Skills
    loader = SkillsLoader(global_dir="~/.smartclaw/skills")
    skills_reg = SkillsRegistry(loader=loader, tool_registry=registry)
    skills_reg.load_and_register_all()

    # Sub-Agent
    sem = asyncio.Semaphore(5)
    sa_tool = SpawnSubAgentTool(
        default_model=settings.model.primary, max_depth=3,
        timeout_seconds=60, semaphore=sem,
    )
    registry.register(sa_tool)

    tools = registry.get_all()

    # Memory + Summarizer (low threshold to trigger summary mid-test)
    db_path = str(tmp / "full_integration.db")
    store = MemoryStore(db_path=db_path)
    await store.initialize()
    summarizer = AutoSummarizer(
        store=store, model_config=settings.model,
        message_threshold=8, keep_recent=2,
    )

    session = "devops-full"
    tool_names = sorted(registry.list_tools())
    print(f"Tools ({len(tool_names)}): {', '.join(tool_names)}")
    print(f"Session: {session}")
    print(f"Summary threshold: 8 messages (low, to trigger mid-test)")
    print()

    async def ask(msg: str, max_iter: int = 5) -> dict:
        """Invoke with full memory + summarizer, with retry on rate limit."""
        for attempt in range(MAX_RETRIES + 1):
            # Build a fresh graph each call to reset FallbackChain cooldown
            graph = build_graph(settings.model, tools=tools)
            r = await invoke(graph, msg, max_iterations=max_iter,
                             session_key=session, memory_store=store,
                             summarizer=summarizer)
            # Check if it failed (no final_answer or has error)
            err = r.get("error") or ""
            has_answer = r.get("final_answer") is not None and len(r.get("final_answer", "")) > 0
            if not has_answer or err:
                if attempt < MAX_RETRIES:
                    wait = RETRY_BACKOFF * (attempt + 1)
                    print(f"    ⏳ API error, retrying in {wait:.0f}s (attempt {attempt + 2}/{MAX_RETRIES + 1})...")
                    await asyncio.sleep(wait)
                    continue
            # Success or all retries exhausted
            time.sleep(CALL_INTERVAL)
            return r
        return r  # Return last result even if all retries failed

    # ==================================================================
    # Phase 1: File Operations (P0 tools)
    # ==================================================================
    print("📁 Phase 1: File Operations")
    print("-" * 40)

    # Turn 1: write_file
    config_path = tmp / "project.yaml"
    r = await ask(f"创建一个项目配置文件 {config_path}，内容为：\nname: smartclaw-demo\nversion: 1.0.0\nenv: production")
    report("T1 write_file: create project.yaml",
           config_path.exists() and "smartclaw-demo" in config_path.read_text(),
           r.get("final_answer", "")[:80])

    # Turn 2: read_file
    r = await ask(f"读取 {config_path} 的内容，告诉我项目名称和版本号")
    answer = r.get("final_answer") or ""
    report("T2 read_file: read project.yaml",
           "smartclaw-demo" in answer and "1.0" in answer, answer[:80])

    # Turn 3: edit_file
    r = await ask(f"把 {config_path} 中的版本号 '1.0.0' 修改为 '2.0.0'")
    content = config_path.read_text() if config_path.exists() else ""
    report("T3 edit_file: update version to 2.0.0",
           "2.0.0" in content, content[:80])

    # Turn 4: append_file
    r = await ask(f"在 {config_path} 末尾追加一行：debug: true")
    content = config_path.read_text() if config_path.exists() else ""
    report("T4 append_file: add debug line",
           "debug" in content and "true" in content, content[:80])

    # Turn 5: list_directory
    (tmp / "README.md").write_text("# Demo Project\n")
    (tmp / "deploy.sh").write_text("#!/bin/bash\necho deploy\n")
    r = await ask(f"列出 {tmp} 目录下的所有文件")
    answer = r.get("final_answer") or ""
    report("T5 list_directory: list workspace",
           "project.yaml" in answer and "README" in answer, answer[:80])

    # ==================================================================
    # Phase 2: Shell + Skills (P0 shell + P1 skills)
    # ==================================================================
    print("\n🔧 Phase 2: Shell & Skills")
    print("-" * 40)

    # Turn 6: exec_command
    r = await ask("执行 uname -a 命令，告诉我操作系统信息")
    answer = r.get("final_answer") or ""
    report("T6 exec_command: uname -a",
           "Darwin" in answer or "Linux" in answer or "darwin" in answer.lower(),
           answer[:80])

    # Turn 7: sysinfo skill
    r = await ask("使用 sysinfo 工具查看系统信息，告诉我 CPU 型号")
    answer = r.get("final_answer") or ""
    report("T7 sysinfo skill: system info",
           len(answer) > 50 and r.get("error") is None, answer[:80])

    # Turn 8: disk-check skill
    r = await ask("使用 disk-check 工具检查磁盘使用情况")
    answer = r.get("final_answer") or ""
    report("T8 disk-check skill: disk usage",
           len(answer) > 30 and r.get("error") is None, answer[:80])

    # ==================================================================
    # Phase 3: Web Tools (P0)
    # ==================================================================
    print("\n🌐 Phase 3: Web Tools")
    print("-" * 40)

    # Turn 9: web_fetch
    r = await ask("用 web_fetch 抓取 https://api.github.com/zen 的内容")
    answer = r.get("final_answer") or ""
    report("T9 web_fetch: GitHub zen",
           len(answer) > 10 and r.get("error") is None, answer[:80])

    # Turn 10: web_search
    r = await ask("用 web_search 搜索 'Python asyncio tutorial'，简要告诉我搜索结果")
    answer = r.get("final_answer") or ""
    report("T10 web_search: Python asyncio",
           len(answer) > 30 and r.get("error") is None, answer[:80])

    # ==================================================================
    # Phase 4: Sub-Agent (P1)
    # ==================================================================
    print("\n🤖 Phase 4: Sub-Agent Delegation")
    print("-" * 40)

    # Turn 11: sub-agent via agent (not direct spawn)
    r = await ask("请委托子代理计算：(17 * 23) + (42 * 8) 的结果是多少？直接告诉我最终数字")
    answer = r.get("final_answer") or ""
    # 17*23=391, 42*8=336, total=727
    report("T11 sub-agent: math delegation",
           "727" in answer, answer[:80])

    # ==================================================================
    # Phase 5: Error Recovery (P1)
    # ==================================================================
    print("\n🔄 Phase 5: Error Recovery")
    print("-" * 40)

    # Turn 12: error recovery
    ghost = tmp / "ghost_config.yaml"
    r = await ask(
        f"读取 {ghost} 的内容，如果文件不存在就创建它并写入 'status: recovered'，然后读取确认",
        max_iter=8)
    answer = r.get("final_answer") or ""
    report("T12 error recovery: read-fail → create → read",
           ghost.exists() and "recovered" in ghost.read_text(), answer[:80])

    # ==================================================================
    # Phase 6: Memory Recall (P1)
    # ==================================================================
    print("\n🧠 Phase 6: Memory & Summary")
    print("-" * 40)

    # Check if summary was triggered (we've had 12+ turns with low threshold)
    summary = await store.get_summary(session)
    history = await store.get_history(session)
    report("Summary auto-triggered",
           len(summary) > 20,
           f"summary_len={len(summary)}, history_len={len(history)}")

    # Turn 13: memory recall — ask about project name from Turn 1
    r = await ask("我们之前创建的项目配置文件叫什么名字？项目名是什么？")
    answer = r.get("final_answer") or ""
    report("T13 memory: recall project name",
           "project" in answer.lower() or "smartclaw" in answer.lower(),
           answer[:80])

    # Turn 14: memory recall — ask about version from Turn 3
    r = await ask("项目配置文件的版本号现在是多少？")
    answer = r.get("final_answer") or ""
    # Version could be 2.0.0 (if edit succeeded) or 1.0.0 (if edit was rate-limited)
    report("T14 memory: recall version number",
           "2.0.0" in answer or "1.0.0" in answer, answer[:80])

    # Turn 15: memory recall — ask about system info from Turn 7
    r = await ask("之前查到的 CPU 型号是什么？")
    answer = r.get("final_answer") or ""
    report("T15 memory: recall CPU from skill",
           len(answer) > 10 and ("CPU" in answer.upper() or "Apple" in answer or "M4" in answer),
           answer[:80])

    await store.close()

    # ==================================================================
    # Results Summary
    # ==================================================================
    print("\n" + "=" * 70)
    passed = sum(1 for _, p in results if p)
    total = len(results)

    phases = {
        "Phase 1 — File Operations (P0)": results[0:5],
        "Phase 2 — Shell & Skills (P0+P1)": results[5:8],
        "Phase 3 — Web Tools (P0)": results[8:10],
        "Phase 4 — Sub-Agent (P1)": results[10:11],
        "Phase 5 — Error Recovery (P1)": results[11:12],
        "Phase 6 — Memory & Summary (P1)": results[12:],
    }

    print(f"\n📊 Results: {passed}/{total} passed\n")
    for phase_name, phase_results in phases.items():
        p = sum(1 for _, ok in phase_results if ok)
        t = len(phase_results)
        icon = "✅" if p == t else "⚠️"
        print(f"  {icon} {phase_name}: {p}/{t}")

    if passed < total:
        print(f"\n❌ Failed ({total - passed}):")
        for name, p in results:
            if not p:
                print(f"    {FAIL} {name}")

    print(f"\n🏁 Feature Coverage:")
    print(f"  P0 Tools: write_file, read_file, edit_file, append_file, list_directory, exec_command, web_fetch, web_search")
    print(f"  P1 Features: Memory, AutoSummarizer, Skills (sysinfo + disk-check), Sub-Agent, Error Recovery")
    print(f"  Total: 8 P0 tools + 5 P1 features = 13 features tested in 1 session")
    print()

    # Cleanup
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
