"""E2E test: Agent uses web_fetch tool to fetch a web page."""

import asyncio

from smartclaw.config.loader import load_config
from smartclaw.credentials import load_dotenv
from smartclaw.observability.logging import setup_logging
from smartclaw.agent.graph import build_graph, invoke
from smartclaw.tools.registry import create_system_tools


async def main() -> None:
    load_dotenv()
    settings = load_config()
    setup_logging(settings.logging)

    registry = create_system_tools(settings.agent_defaults.workspace)
    tools = registry.get_all()
    graph = build_graph(settings.model, tools=tools)

    print(f"Model: {settings.model.primary}")
    print(f"Tools: {registry.list_tools()}")
    print("=" * 60)

    query = "请用 web_fetch 工具抓取 https://api.github.com/zen 的内容，告诉我 GitHub 返回了什么哲学名言"
    print(f"Query: {query}\n")

    result = await invoke(graph, query, max_iterations=10)

    if result.get("error"):
        print(f"❌ Error: {result['error']}")
    elif result.get("final_answer"):
        print(f"Agent Answer:\n{result['final_answer']}")
    else:
        print("⚠️  No response")

    print(f"\n(iterations: {result.get('iteration', 0)})")


if __name__ == "__main__":
    asyncio.run(main())
