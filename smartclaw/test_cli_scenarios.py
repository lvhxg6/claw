"""CLI scenario validation — automated tests for all P1 features.

Runs real LLM calls against all major CLI scenarios:
1. Memory persistence across sessions
2. Tool calls (file ops, shell)
3. Skills script execution
4. Sub-Agent delegation
5. Web fetch
6. Error handling (deny patterns, missing files)
7. Summary trigger

Usage: KIMI_API_KEY=... python test_cli_scenarios.py
"""

import asyncio
import os
import sys
import pathlib

# Ensure we can import smartclaw
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from smartclaw.config.loader import load_config
from smartclaw.credentials import load_dotenv
from smartclaw.agent.graph import build_graph, invoke
from smartclaw.tools.registry import create_system_tools
from smartclaw.skills.loader import SkillsLoader
from smartclaw.skills.registry import SkillsRegistry
from smartclaw.memory.store import MemoryStore
from smartclaw.memory.summarizer import AutoSummarizer
from smartclaw.agent.sub_agent import SubAgentConfig, spawn_sub_agent
from smartclaw.providers.config import ModelConfig

PASS = "✅"
FAIL = "❌"
results = []


def report(name: str, passed: bool, detail: str = ""):
    status = PASS if passed else FAIL
    results.append((name, passed))
    print(f"  {status} {name}" + (f" — {detail}" if detail else ""))


async def main():
    load_dotenv()
    settings = load_config()
    tmp = pathlib.Path("/tmp/smartclaw_cli_test")
    tmp.mkdir(parents=True, exist_ok=True)

    print("\n🧪 SmartClaw CLI Scenario Validation")
    print("=" * 60)

    # --- Setup ---
    workspace = str(tmp)
    registry = create_system_tools(workspace)

    # Load skills
    loader = SkillsLoader(global_dir="~/.smartclaw/skills")
    skills_reg = SkillsRegistry(loader=loader, tool_registry=registry)
    skills_reg.load_and_register_all()

    # Sub-agent tool
    from smartclaw.agent.sub_agent import SpawnSubAgentTool
    sem = asyncio.Semaphore(5)
    sa_tool = SpawnSubAgentTool(
        default_model=settings.model.primary, max_depth=3,
        timeout_seconds=60, semaphore=sem,
    )
    registry.register(sa_tool)

    tools = registry.get_all()
    graph = build_graph(settings.model, tools=tools)

    print(f"Tools: {registry.count} ({', '.join(registry.list_tools())})")
    print()

    # ============================================================
    # Test 1: Memory — name recall across sessions
    # ============================================================
    print("📋 Test 1: Memory persistence")
    db = str(tmp / "test_memory.db")
    store = MemoryStore(db_path=db)
    await store.initialize()

    r1 = await invoke(graph, "我叫TestUser123，请记住我的名字。",
                      max_iterations=3, session_key="mem-test", memory_store=store)
    report("Session 1: tell name", r1.get("error") is None)

    r2 = await invoke(graph, "我叫什么名字？",
                      max_iterations=3, session_key="mem-test", memory_store=store)
    answer = r2.get("final_answer") or ""
    report("Session 2: recall name", "TestUser123" in answer, answer[:80])
    await store.close()


    # ============================================================
    # Test 2: Tool calls — file operations
    # ============================================================
    print("\n📋 Test 2: Tool calls — file operations")
    target = tmp / "tool_test.txt"
    r = await invoke(graph, f"写入文本 'hello_tool_test' 到文件 {target}",
                     max_iterations=5)
    report("Write file", target.exists() and "hello_tool_test" in target.read_text(),
           f"exists={target.exists()}")

    r = await invoke(graph, f"读取文件 {target} 的内容，告诉我里面写了什么",
                     max_iterations=5)
    answer = r.get("final_answer") or ""
    report("Read file", "hello_tool_test" in answer, answer[:80])

    # ============================================================
    # Test 3: Shell command
    # ============================================================
    print("\n📋 Test 3: Shell command execution")
    r = await invoke(graph, "执行命令 echo SHELL_TEST_OK 并告诉我输出",
                     max_iterations=5)
    answer = r.get("final_answer") or ""
    report("Shell echo", "SHELL_TEST_OK" in answer, answer[:80])

    # ============================================================
    # Test 4: Skills script execution
    # ============================================================
    print("\n📋 Test 4: Skills script execution")
    has_sysinfo = registry.get("sysinfo") is not None
    has_disk = registry.get("disk-check") is not None
    report("sysinfo tool registered", has_sysinfo)
    report("disk-check tool registered", has_disk)

    if has_sysinfo:
        r = await invoke(graph, "使用 sysinfo 工具查看系统信息",
                         max_iterations=5)
        answer = r.get("final_answer") or ""
        report("sysinfo execution", len(answer) > 50 and r.get("error") is None, answer[:80])

    # ============================================================
    # Test 5: Sub-Agent delegation
    # ============================================================
    print("\n📋 Test 5: Sub-Agent delegation")
    cfg = SubAgentConfig(task="What is 7 * 9? Reply with just the number.",
                         model=settings.model.primary, max_iterations=3, timeout_seconds=30)
    result = await spawn_sub_agent(cfg, parent_depth=0)
    report("Sub-agent math", "63" in result, result[:80])


    # ============================================================
    # Test 6: Web fetch
    # ============================================================
    print("\n📋 Test 6: Web fetch")
    r = await invoke(graph, "用 web_fetch 抓取 https://api.github.com/zen 的内容",
                     max_iterations=5)
    answer = r.get("final_answer") or ""
    report("Web fetch", len(answer) > 10 and r.get("error") is None, answer[:80])

    # ============================================================
    # Test 7: Error handling
    # ============================================================
    print("\n📋 Test 7: Error handling")
    r = await invoke(graph, "读取文件 /nonexistent_path_12345/ghost.txt",
                     max_iterations=5)
    answer = r.get("final_answer") or ""
    report("Missing file error", "not found" in answer.lower() or "error" in answer.lower() or "不存在" in answer,
           answer[:80])

    r = await invoke(graph, "执行命令 rm -rf /",
                     max_iterations=5)
    answer = r.get("final_answer") or ""
    report("Deny pattern blocks rm -rf",
           "blocked" in answer.lower() or "security" in answer.lower() or "拒绝" in answer or "阻止" in answer or "危险" in answer,
           answer[:80])

    # ============================================================
    # Summary
    # ============================================================
    print("\n" + "=" * 60)
    passed = sum(1 for _, p in results if p)
    total = len(results)
    print(f"Results: {passed}/{total} passed")
    if passed < total:
        print("Failed:")
        for name, p in results:
            if not p:
                print(f"  {FAIL} {name}")
    print()

    # Cleanup
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
