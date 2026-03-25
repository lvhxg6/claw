"""SmartClaw CLI — interactive command-line interface.

All features enabled by default. Just run:
    python -m smartclaw.cli

Optional overrides:
    python -m smartclaw.cli --session my-chat   # use a specific session name
    python -m smartclaw.cli --no-memory         # disable memory persistence
    python -m smartclaw.cli --no-skills         # disable skills loading
    python -m smartclaw.cli --no-sub-agent      # disable sub-agent tool
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid

from smartclaw.config.loader import load_config
from smartclaw.config.settings import SmartClawSettings
from smartclaw.credentials import load_dotenv
from smartclaw.observability.logging import get_logger, setup_logging

SYSTEM_PROMPT = """\
You are SmartClaw, a helpful AI assistant with access to tools.

Tool usage guidelines:
- Use `web_fetch` to fetch content from a specific URL.
- Use `web_search` to search the web. If it fails, fall back to `web_fetch`.
- Use `exec_command` to run shell commands on the local system.
- Use `read_file`, `write_file`, `edit_file`, `append_file`, `list_directory` for file operations.
- Use `spawn_sub_agent` to delegate complex subtasks to a child agent (if available).
- When a tool returns an error, try an alternative approach instead of giving up.
- Always respond in the same language as the user's input.
{skills_section}"""


async def _run_agent_loop(settings: SmartClawSettings, args: argparse.Namespace) -> None:
    """Run the interactive agent loop with all features enabled by default."""
    from smartclaw.agent.graph import build_graph, invoke
    from smartclaw.tools.registry import ToolRegistry, create_system_tools

    logger = get_logger("cli")

    workspace = settings.agent_defaults.workspace
    system_registry = create_system_tools(workspace)

    # --- Skills (default ON) ---
    skills_summary = ""
    if settings.skills.enabled and not args.no_skills:
        try:
            from smartclaw.skills.loader import SkillsLoader
            from smartclaw.skills.registry import SkillsRegistry

            ws_dir = settings.skills.workspace_dir.replace("{workspace}", workspace)
            loader = SkillsLoader(workspace_dir=ws_dir, global_dir=settings.skills.global_dir)
            skills_reg = SkillsRegistry(loader=loader, tool_registry=system_registry)
            skills_reg.load_and_register_all()
            skills_summary = loader.build_skills_summary()
            if skills_summary:
                logger.info("skills_loaded", count=len(skills_reg.list_skills()))
        except Exception as exc:
            logger.warning("skills_load_failed", error=str(exc))

    # --- Sub-Agent (default ON) ---
    if settings.sub_agent.enabled and not args.no_sub_agent:
        try:
            from smartclaw.agent.sub_agent import SpawnSubAgentTool

            sem = asyncio.Semaphore(settings.sub_agent.max_concurrent)
            tool = SpawnSubAgentTool(
                default_model=settings.model.primary,
                max_depth=settings.sub_agent.max_depth,
                timeout_seconds=settings.sub_agent.default_timeout_seconds,
                semaphore=sem,
                concurrency_timeout=float(settings.sub_agent.concurrency_timeout_seconds),
            )
            system_registry.register(tool)
        except Exception as exc:
            logger.warning("sub_agent_setup_failed", error=str(exc))

    tools = system_registry.get_all()
    prompt = SYSTEM_PROMPT.format(
        skills_section=f"\n\nAvailable skills:\n{skills_summary}" if skills_summary else ""
    )

    # --- Memory (default ON, auto session) ---
    memory_store = None
    summarizer = None
    session_key = None

    if settings.memory.enabled and not args.no_memory:
        session_key = args.session or f"cli-{uuid.uuid4().hex[:8]}"
        from smartclaw.memory.store import MemoryStore
        from smartclaw.memory.summarizer import AutoSummarizer

        memory_store = MemoryStore(db_path=settings.memory.db_path)
        await memory_store.initialize()
        summarizer = AutoSummarizer(
            store=memory_store, model_config=settings.model,
            message_threshold=settings.memory.summary_threshold,
            keep_recent=settings.memory.keep_recent,
            token_percent_threshold=settings.memory.summarize_token_percent,
            context_window=settings.memory.context_window,
        )

    graph = build_graph(settings.model, tools=tools)


    # --- Banner ---
    print("\n🦀 SmartClaw CLI")
    print("=" * 50)
    print(f"Model:     {settings.model.primary}")
    print(f"Tools:     {len(system_registry.get_all())} ({', '.join(system_registry.list_tools())})")
    if session_key:
        hist = await memory_store.get_history(session_key) if memory_store else []
        summ = await memory_store.get_summary(session_key) if memory_store else ""
        print(f"Memory:    ON (session: {session_key}, {len(hist)} messages)")
        if summ:
            print(f"  Summary: {summ[:80]}...")
    else:
        print("Memory:    OFF")
    print(f"Skills:    {'ON' if skills_summary else 'OFF'}")
    print(f"Sub-Agent: {'ON' if system_registry.get('spawn_sub_agent') else 'OFF'}")
    print("=" * 50)
    print("Commands: /history /summary /clear /tools /help /quit")
    print()

    while True:
        try:
            user_input = input("You > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not user_input:
            continue

        # --- Slash commands ---
        if user_input.startswith("/"):
            cmd = user_input.lower()
            if cmd in ("/quit", "/exit", "/q"):
                print("Bye!")
                break
            if cmd == "/history" and memory_store and session_key:
                hist = await memory_store.get_history(session_key)
                print(f"\n📜 History ({len(hist)} messages):")
                for i, m in enumerate(hist):
                    print(f"  [{i}] {m.type}: {str(m.content)[:120]}")
                print()
                continue
            if cmd == "/summary" and memory_store and session_key:
                summ = await memory_store.get_summary(session_key)
                print(f"\n📝 Summary: {summ or '(none)'}\n")
                continue
            if cmd == "/clear" and memory_store and session_key:
                await memory_store.truncate_history(session_key, 0)
                await memory_store.set_summary(session_key, "")
                print("🗑️  Session cleared.\n")
                continue
            if cmd == "/tools":
                print(f"\n🔧 Tools ({len(tools)}):")
                for t in sorted(tools, key=lambda x: x.name):
                    print(f"  - {t.name}: {t.description[:80]}")
                print()
                continue
            if cmd == "/help":
                print("\n📖 Commands:")
                print("  /history  — Show conversation history")
                print("  /summary  — Show conversation summary")
                print("  /clear    — Clear session history and summary")
                print("  /tools    — List all available tools")
                print("  /help     — Show this help")
                print("  /quit     — Exit\n")
                continue
            print(f"Unknown command: {user_input}. Type /help for available commands.\n")
            continue

        if user_input.lower() in ("quit", "exit", "q"):
            print("Bye!")
            break

        try:
            result = await invoke(
                graph, user_input,
                max_iterations=settings.agent_defaults.max_tool_iterations,
                system_prompt=prompt,
                session_key=session_key,
                memory_store=memory_store,
                summarizer=summarizer,
            )
            if result.get("error"):
                print(f"\n❌ Error: {result['error']}")
            elif result.get("final_answer"):
                print(f"\nAgent > {result['final_answer']}")
            else:
                print("\n⚠️  No response")
            print(f"  (iterations: {result.get('iteration', 0)})\n")
        except Exception as e:
            print(f"\n❌ Exception: {e}\n")

    if memory_store:
        await memory_store.close()


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="SmartClaw CLI — all features ON by default")
    parser.add_argument("--session", type=str, default=None,
                        help="Session name (auto-generated if not specified)")
    parser.add_argument("--no-memory", action="store_true", help="Disable memory persistence")
    parser.add_argument("--no-skills", action="store_true", help="Disable skills loading")
    parser.add_argument("--no-sub-agent", action="store_true", help="Disable sub-agent tool")
    parser.add_argument("--browser", action="store_true", help="Enable browser tools")
    args = parser.parse_args()

    try:
        load_dotenv()
        settings = load_config()
        setup_logging(settings.logging)
        get_logger("cli").info("SmartClaw CLI starting", version="0.1.0")
        asyncio.run(_run_agent_loop(settings, args))
    except FileNotFoundError as exc:
        print(f"❌ Config not found: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"❌ Failed to start: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
