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


async def _run_agent_loop(settings: SmartClawSettings, args: argparse.Namespace) -> None:
    """Run the interactive agent loop with all features enabled by default."""
    from smartclaw.agent.graph import invoke
    from smartclaw.agent.runtime import setup_agent_runtime

    logger = get_logger("cli")

    # Apply --no-* flags to settings before runtime initialization
    if args.no_memory:
        settings.memory.enabled = False
    if args.no_skills:
        settings.skills.enabled = False
    if args.no_sub_agent:
        settings.sub_agent.enabled = False

    runtime = await setup_agent_runtime(settings)

    graph = runtime.graph
    memory_store = runtime.memory_store
    summarizer = runtime.summarizer
    prompt = runtime.system_prompt
    tools = runtime.tools

    # Session key (only when memory is active)
    session_key = None
    if memory_store is not None:
        session_key = args.session or f"cli-{uuid.uuid4().hex[:8]}"

    # --- Banner ---
    print("\n🦀 SmartClaw CLI")
    print("=" * 50)
    print(f"Model:     {settings.model.primary}")
    print(f"Tools:     {len(runtime.tools)} ({', '.join(runtime.tool_names)})")
    if session_key:
        hist = await memory_store.get_history(session_key) if memory_store else []
        summ = await memory_store.get_summary(session_key) if memory_store else ""
        print(f"Memory:    ON (session: {session_key}, {len(hist)} messages)")
        if summ:
            print(f"  Summary: {summ[:80]}...")
    else:
        print("Memory:    OFF")
    print(f"Skills:    {'ON' if 'Available skills:' in runtime.system_prompt else 'OFF'}")
    print(f"Sub-Agent: {'ON' if 'spawn_sub_agent' in runtime.tool_names else 'OFF'}")
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
            print("  ⏳ thinking...", end="", flush=True)
            result = await invoke(
                graph, user_input,
                max_iterations=settings.agent_defaults.max_tool_iterations,
                system_prompt=prompt,
                session_key=session_key,
                memory_store=memory_store,
                summarizer=summarizer,
            )

            # Show tool call trace
            from langchain_core.messages import AIMessage as _AI, ToolMessage as _TM
            msgs = result.get("messages", [])
            tool_calls_shown = []
            for m in msgs:
                if isinstance(m, _AI) and m.tool_calls:
                    for tc in m.tool_calls:
                        name = tc.get("name", "?")
                        args_str = str(tc.get("args", {}))
                        if len(args_str) > 80:
                            args_str = args_str[:77] + "..."
                        tool_calls_shown.append(f"  🔧 {name}({args_str})")

            if tool_calls_shown:
                print(f"\r{'':50}")  # clear thinking line
                for line in tool_calls_shown:
                    print(line)

            if result.get("error"):
                if not tool_calls_shown:
                    print(f"\r{'':50}")
                print(f"  ❌ Error: {result['error']}")
            elif result.get("final_answer"):
                if not tool_calls_shown:
                    print(f"\r{'':50}")
                print(f"\nAgent > {result['final_answer']}")
            else:
                print("\n  ⚠️  No response")
            print(f"  ({result.get('iteration', 0)} iterations)\n")
        except Exception as e:
            print(f"\n❌ Exception: {e}\n")

    await runtime.close()


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
