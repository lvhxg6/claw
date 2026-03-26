"""Cross-feature scenario validation — complex multi-feature interactions.

Tests that combine multiple P1 features in realistic workflows:
1. Memory + Tools: tool results persist, follow-up references them
2. Memory + Skills: skill execution results remembered across turns
3. Sub-Agent + Tools: sub-agent uses tools, parent gets result
4. Memory + Summary + Tools: long tool-heavy conversation triggers summary
5. Skills + Memory + Follow-up: skill output persisted, queried later
6. Multi-tool chain: write → edit → read in one conversation
7. Sub-Agent + Memory: sub-agent result persisted in parent memory
8. Error recovery: tool error → agent retries with different approach

Usage: KIMI_API_KEY=... python test_cli_cross_scenarios.py
"""

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from smartclaw.config.loader import load_config
from smartclaw.credentials import load_dotenv
from smartclaw.agent.graph import build_graph, invoke
from smartclaw.tools.registry import create_system_tools
from smartclaw.skills.loader import SkillsLoader
from smartclaw.skills.registry import SkillsRegistry
from smartclaw.memory.store import MemoryStore
from smartclaw.memory.summarizer import AutoSummarizer
from smartclaw.agent.sub_agent import SpawnSubAgentTool, SubAgentConfig, spawn_sub_agent

PASS = "✅"
FAIL = "❌"
results = []


def report(name: str, passed: bool, detail: str = ""):
    status = PASS if passed else FAIL
    results.append((name, passed))
    print(f"  {status} {name}" + (f" — {detail[:100]}" if detail else ""))


async def main():
    load_dotenv()
    settings = load_config()
    tmp = pathlib.Path("/tmp/smartclaw_cross_test")
    tmp.mkdir(parents=True, exist_ok=True)

    print("\n🧪 SmartClaw Cross-Feature Scenario Validation")
    print("=" * 60)

    workspace = str(tmp)
    registry = create_system_tools(workspace)

    loader = SkillsLoader(global_dir="~/.smartclaw/skills")
    skills_reg = SkillsRegistry(loader=loader, tool_registry=registry)
    skills_reg.load_and_register_all()

    sem = asyncio.Semaphore(5)
    sa_tool = SpawnSubAgentTool(
        default_model=settings.model.primary, max_depth=3,
        timeout_seconds=60, semaphore=sem,
    )
    registry.register(sa_tool)

    tools = registry.get_all()
    graph = build_graph(settings.model, tools=tools)
    print(f"Tools: {registry.count}\n")

    # ============================================================
    # Scenario 1: Memory + Tools — tool results persist across turns
    # ============================================================
    print("📋 Scenario 1: Memory + Tools — tool results persist")
    db1 = str(tmp / "cross1.db")
    store1 = MemoryStore(db_path=db1)
    await store1.initialize()

    # Turn 1: execute shell, get hostname
    r1 = await invoke(graph, "执行 hostname 命令，告诉我主机名是什么",
                      max_iterations=5, session_key="cross1", memory_store=store1)
    answer1 = r1.get("final_answer") or ""
    report("Turn 1: get hostname via shell", len(answer1) > 5 and r1.get("error") is None, answer1)

    # Turn 2: ask about the hostname from memory (no tool call needed)
    r2 = await invoke(graph, "刚才查到的主机名是什么？",
                      max_iterations=3, session_key="cross1", memory_store=store1)
    answer2 = r2.get("final_answer") or ""
    # Should recall hostname from memory without re-executing
    report("Turn 2: recall hostname from memory", len(answer2) > 3, answer2)
    await store1.close()


    # ============================================================
    # Scenario 2: Multi-tool chain — write → edit → read
    # ============================================================
    print("\n📋 Scenario 2: Multi-tool chain — write → edit → read")
    target = tmp / "chain_test.txt"
    db2 = str(tmp / "cross2.db")
    store2 = MemoryStore(db_path=db2)
    await store2.initialize()

    r = await invoke(graph,
        f"请完成以下三步操作：1) 写入 'version=1.0' 到 {target}  2) 把 '1.0' 替换为 '2.0'  3) 读取文件确认内容",
        max_iterations=10, session_key="cross2", memory_store=store2)
    answer = r.get("final_answer") or ""
    file_ok = target.exists() and "2.0" in target.read_text()
    report("Write → Edit → Read chain", file_ok and "2.0" in answer, answer)

    # Follow-up: ask what version is in the file (from memory)
    r = await invoke(graph, "文件里现在的版本号是多少？",
                     max_iterations=3, session_key="cross2", memory_store=store2)
    answer = r.get("final_answer") or ""
    report("Follow-up: recall version from memory", "2.0" in answer, answer)
    await store2.close()

    # ============================================================
    # Scenario 3: Skills + Memory — skill output remembered
    # ============================================================
    print("\n📋 Scenario 3: Skills + Memory — skill output remembered")
    db3 = str(tmp / "cross3.db")
    store3 = MemoryStore(db_path=db3)
    await store3.initialize()

    r = await invoke(graph, "用 sysinfo 工具查看系统信息",
                     max_iterations=5, session_key="cross3", memory_store=store3)
    answer = r.get("final_answer") or ""
    report("Skill execution with memory", len(answer) > 50, answer)

    r = await invoke(graph, "刚才查到的CPU型号是什么？",
                     max_iterations=3, session_key="cross3", memory_store=store3)
    answer = r.get("final_answer") or ""
    report("Recall skill result from memory", "M4" in answer or "Apple" in answer or "CPU" in answer.upper(), answer)
    await store3.close()


    # ============================================================
    # Scenario 4: Sub-Agent + Tools — sub-agent uses tools
    # ============================================================
    print("\n📋 Scenario 4: Sub-Agent + Tools — sub-agent uses shell")
    from smartclaw.tools.shell import ShellTool
    cfg = SubAgentConfig(
        task="Run 'uname -m' and tell me the CPU architecture. Reply with just the architecture name.",
        model=settings.model.primary,
        tools=[ShellTool()],
        max_iterations=5, timeout_seconds=30,
    )
    result = await spawn_sub_agent(cfg, parent_depth=0)
    report("Sub-agent uses shell tool", "arm64" in result.lower() or "x86" in result.lower() or "aarch" in result.lower(), result)

    # ============================================================
    # Scenario 5: Memory + Summary trigger — many turns
    # ============================================================
    print("\n📋 Scenario 5: Memory + Summary — many turns trigger summary")
    db5 = str(tmp / "cross5.db")
    store5 = MemoryStore(db_path=db5)
    await store5.initialize()
    summarizer5 = AutoSummarizer(
        store=store5, model_config=settings.model,
        message_threshold=6, keep_recent=2,
    )

    # Rapid-fire 4 turns to exceed threshold (each turn = 2+ messages)
    topics = [
        "Python的GIL是什么？",
        "Rust的所有权系统怎么工作？",
        "Go的goroutine和channel有什么优势？",
        "TypeScript和JavaScript的主要区别是什么？",
    ]
    for topic in topics:
        await invoke(graph, topic, max_iterations=3,
                     session_key="cross5", memory_store=store5, summarizer=summarizer5)

    summary = await store5.get_summary("cross5")
    history = await store5.get_history("cross5")
    report("Summary generated after many turns",
           len(summary) > 20,
           f"summary_len={len(summary)}, history_len={len(history)}")

    # Ask about earlier topic (should be in summary)
    r = await invoke(graph, "我们之前讨论了哪些编程语言？",
                     max_iterations=3, session_key="cross5",
                     memory_store=store5, summarizer=summarizer5)
    answer = r.get("final_answer") or ""
    report("Recall from summary context",
           any(lang in answer for lang in ["Python", "Rust", "Go", "TypeScript"]),
           answer)
    await store5.close()

    # ============================================================
    # Scenario 6: Error recovery chain — tool error → agent retries
    # ============================================================
    print("\n📋 Scenario 6: Error recovery — agent retries on failure")
    db6 = str(tmp / "cross6.db")
    store6 = MemoryStore(db_path=db6)
    await store6.initialize()

    # Ask to read a non-existent file, then create it — agent should recover
    r = await invoke(graph,
        f"先读取 {tmp}/recovery_test.txt 的内容，如果文件不存在就创建它并写入 'recovered_ok'，然后再读取确认",
        max_iterations=8, session_key="cross6", memory_store=store6)
    answer = r.get("final_answer") or ""
    recovery_file = tmp / "recovery_test.txt"
    report("Error recovery: read-fail → create → read",
           recovery_file.exists() and "recovered_ok" in recovery_file.read_text(),
           answer)
    await store6.close()

    # ============================================================
    # Scenario 7: Concurrent sub-agents
    # ============================================================
    print("\n📋 Scenario 7: Concurrent sub-agents")
    from smartclaw.tools.shell import ShellTool

    tasks_cfg = [
        SubAgentConfig(
            task="Run 'echo TASK_A_DONE' and return the output.",
            model=settings.model.primary, tools=[ShellTool()],
            max_iterations=3, timeout_seconds=30,
        ),
        SubAgentConfig(
            task="Run 'echo TASK_B_DONE' and return the output.",
            model=settings.model.primary, tools=[ShellTool()],
            max_iterations=3, timeout_seconds=30,
        ),
    ]
    concurrent_results = await asyncio.gather(
        spawn_sub_agent(tasks_cfg[0], parent_depth=0),
        spawn_sub_agent(tasks_cfg[1], parent_depth=0),
    )
    report("Concurrent sub-agent A", "TASK_A_DONE" in concurrent_results[0], concurrent_results[0][:80])
    report("Concurrent sub-agent B", "TASK_B_DONE" in concurrent_results[1], concurrent_results[1][:80])

    # ============================================================
    # Scenario 8: Full integration — memory + tools + skills + summary
    # ============================================================
    print("\n📋 Scenario 8: Full integration — all features combined")
    db8 = str(tmp / "cross8.db")
    store8 = MemoryStore(db_path=db8)
    await store8.initialize()
    summarizer8 = AutoSummarizer(
        store=store8, model_config=settings.model,
        message_threshold=8, keep_recent=2,
    )

    # Turn 1: write a file
    r = await invoke(graph, f"写入 'integration_v1' 到 {tmp}/integration.txt",
                     max_iterations=5, session_key="cross8",
                     memory_store=store8, summarizer=summarizer8)
    report("Full: write file", (tmp / "integration.txt").exists(), r.get("final_answer", "")[:60])

    # Turn 2: shell command
    r = await invoke(graph, "执行 whoami 命令",
                     max_iterations=5, session_key="cross8",
                     memory_store=store8, summarizer=summarizer8)
    answer = r.get("final_answer") or ""
    report("Full: shell command", len(answer) > 2, answer[:60])

    # Turn 3: edit the file
    r = await invoke(graph, f"把 {tmp}/integration.txt 中的 'v1' 替换为 'v2'",
                     max_iterations=5, session_key="cross8",
                     memory_store=store8, summarizer=summarizer8)
    content = (tmp / "integration.txt").read_text() if (tmp / "integration.txt").exists() else ""
    report("Full: edit file", "v2" in content, content[:60])

    # Turn 4: recall from memory
    r = await invoke(graph, "我之前写入的文件叫什么名字？",
                     max_iterations=3, session_key="cross8",
                     memory_store=store8, summarizer=summarizer8)
    answer = r.get("final_answer") or ""
    report("Full: recall file name from memory", "integration" in answer.lower(), answer[:60])
    await store8.close()

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
