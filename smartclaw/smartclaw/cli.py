"""SmartClaw CLI — interactive command-line interface for testing P0 features.

Usage:
    uv run python -m smartclaw.cli
    uv run python -m smartclaw.cli --browser   # with browser tools
    uv run python -m smartclaw.cli --no-browser # without browser (default)
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from smartclaw.config.loader import load_config
from smartclaw.config.settings import SmartClawSettings
from smartclaw.credentials import load_dotenv
from smartclaw.observability.logging import get_logger, setup_logging


async def _run_agent_loop(settings: SmartClawSettings, use_browser: bool) -> None:
    """Run the interactive agent loop."""
    from smartclaw.agent.graph import build_graph, invoke
    from smartclaw.tools.registry import ToolRegistry, create_system_tools

    logger = get_logger("cli")

    SYSTEM_PROMPT = """You are SmartClaw, a helpful AI assistant with access to tools.

Tool usage guidelines:
- Use `web_fetch` to fetch content from a specific URL (e.g., weather APIs, documentation pages).
  For weather queries, try: https://wttr.in/{city}?format=3
- Use `web_search` to search the web (requires TAVILY_API_KEY). If it fails, fall back to `web_fetch`.
- Use `exec_command` to run shell commands on the local system.
- Use `read_file`, `write_file`, `edit_file`, `append_file`, `list_directory` for file operations.
- When a tool returns an error, try an alternative approach instead of giving up.
- Always respond in the same language as the user's input."""

    # Build system tools
    workspace = settings.agent_defaults.workspace
    system_registry = create_system_tools(workspace)
    tools = system_registry.get_all()

    logger.info(
        "tools_loaded",
        system_tools=system_registry.count,
        browser_enabled=use_browser,
    )

    # Build agent graph
    graph = build_graph(settings.model, tools=tools)
    logger.info("agent_graph_ready")

    print("\n🦀 SmartClaw CLI — P0 Demo")
    print("=" * 50)
    print(f"Model: {settings.model.primary}")
    print(f"Tools: {system_registry.list_tools()}")
    print(f"Browser: {'enabled' if use_browser else 'disabled'}")
    print("=" * 50)
    print("Type your message (or 'quit' to exit):\n")

    while True:
        try:
            user_input = input("You > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("Bye!")
            break

        try:
            result = await invoke(
                graph,
                user_input,
                max_iterations=settings.agent_defaults.max_tool_iterations,
                system_prompt=SYSTEM_PROMPT,
            )

            # Display result
            if result.get("error"):
                print(f"\n❌ Error: {result['error']}")
            elif result.get("final_answer"):
                print(f"\nAgent > {result['final_answer']}")
            else:
                print("\n⚠️  No response from agent")

            print(f"  (iterations: {result.get('iteration', 0)})\n")

        except Exception as e:
            print(f"\n❌ Exception: {e}\n")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="SmartClaw CLI Demo")
    parser.add_argument("--browser", action="store_true", help="Enable browser tools")
    parser.add_argument("--no-browser", action="store_true", default=True, help="Disable browser tools (default)")
    args = parser.parse_args()

    use_browser = args.browser

    try:
        load_dotenv()
        settings = load_config()
        setup_logging(settings.logging)

        logger = get_logger("cli")
        logger.info("SmartClaw CLI starting", version="0.1.0")

        asyncio.run(_run_agent_loop(settings, use_browser))

    except FileNotFoundError as exc:
        print(f"❌ Config file not found: {exc}")
        print("  Copy config/config.example.yaml to config/config.yaml and set your API keys in .env")
        sys.exit(1)
    except Exception as exc:
        print(f"❌ Failed to start: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
