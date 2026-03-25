"""Shared pytest fixtures and configuration for SmartClaw tests."""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add custom CLI options."""
    parser.addoption(
        "--run-e2e",
        action="store_true",
        default=False,
        help="Run agent-level E2E tests (requires LLM API keys)",
    )
    parser.addoption(
        "--run-network",
        action="store_true",
        default=False,
        help="Run tests that require real network access",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip e2e and network tests unless explicitly enabled."""
    if not config.getoption("--run-e2e"):
        skip_e2e = pytest.mark.skip(reason="Need --run-e2e to run")
        for item in items:
            if "e2e" in item.keywords:
                item.add_marker(skip_e2e)

    if not config.getoption("--run-network"):
        skip_net = pytest.mark.skip(reason="Need --run-network to run")
        for item in items:
            if "network" in item.keywords:
                item.add_marker(skip_net)
