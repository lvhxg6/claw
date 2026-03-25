"""E2E test: Agent uses shell tool to query system info."""

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

    # Build tools and graph
    registry = create_system_tools(settings.agent_defaults.workspace)
    tools = registry.get_all()
    graph = build_graph(settings.model, tools=tools)

    print(f"Model: {settings.model.primary}")
    print(f"Tools: {registry.list_tools()}")
    print("=" * 60)

    # Send request
    query = "请帮我查询当前系统的内存使用情况和磁盘使用情况，用中文回答"
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
